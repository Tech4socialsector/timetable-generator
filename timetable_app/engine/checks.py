"""Hard-constraint verification of a finished (possibly hand-edited) timetable.

Works on plain dicts so it can check solver output, imported timetables and
manual moves alike.

entry: {name, session_key, section_key, course_code, category, term_id,
        day_index, slot_index, duration, room_id, faculty_ids: [..], cohorts: [..],
        session_type}
ctx:   Context built from the plan's data.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .week import DEFAULT_WEEK, Week

STACKABLE = ("CONSTRAINED", "GROUPED")


@dataclass
class Context:
	terms: dict[str, tuple[date, date]] = field(default_factory=dict)  # TERM_ID -> (start, end)
	choice_types: dict[str, str] = field(default_factory=dict)  # category id lower -> choice type
	rooms: dict[str, dict] = field(default_factory=dict)  # id -> {name, type, capacity, lab_type, slots:set}
	faculty_slots: dict[str, set[int]] = field(default_factory=dict)  # faculty id -> abs slots
	sections: dict[str, dict] = field(default_factory=dict)  # section_key -> {capacity, lab_type}
	week: Week = DEFAULT_WEEK

	def terms_overlap(self, a: str, b: str) -> bool:
		ta, tb = self.terms.get((a or "FULL").upper()), self.terms.get((b or "FULL").upper())
		if ta is None or tb is None:
			return True
		return ta[0] <= tb[1] and tb[0] <= ta[1]

	def choice(self, category: str) -> str:
		return self.choice_types.get((category or "").lower(), "NONE")


def occupied(e: dict, slots_per_day: int = DEFAULT_WEEK.slots_per_day) -> list[int]:
	start = int(e["day_index"]) * slots_per_day + int(e["slot_index"])
	return list(range(start, start + int(e.get("duration") or 1)))


def cohorts_may_share(ctx: Context, a: dict, b: dict) -> bool:
	"""True if two sessions with a common cohort are allowed at the same time."""
	if a.get("course_code") and a.get("course_code") == b.get("course_code"):
		return True  # sections of the same course split the cohort
	ca, cb = ctx.choice(a.get("category")), ctx.choice(b.get("category"))
	if "COMPLETE" in (ca, cb):
		return True  # offered to whichever cohorts are free
	if (a.get("category") or "").lower() == (b.get("category") or "").lower() and ca in STACKABLE:
		return True  # students pick one course of the category
	return False


def check_entries(entries: list[dict], ctx: Context) -> list[dict]:
	issues: list[dict] = []
	spd = ctx.week.slots_per_day
	where = ctx.week.label

	def add(rule, message, *names, slot=None):
		issues.append({"rule": rule, "level": "error", "message": message, "entries": list(names),
					   "day_index": None if slot is None else slot // spd,
					   "slot_index": None if slot is None else slot % spd})  # fmt: skip

	by_slot: dict[int, list[dict]] = defaultdict(list)
	for e in entries:
		slots = occupied(e, spd)
		if slots[0] // spd != slots[-1] // spd or slots[-1] >= ctx.week.total or int(e["slot_index"]) >= spd:
			add("day_boundary", f"{e['session_key']} runs past the end of the day.", e["name"])
		for s in slots:
			by_slot[s].append(e)

		# room suitability / availability
		room = ctx.rooms.get(e.get("room_id") or "")
		ctype = ctx.choice(e.get("category"))
		if not e.get("room_id"):
			if ctype not in ("VIRTUAL_STAFFED", "VIRTUAL_OPEN"):
				add("no_room", f"{e['session_key']} has no room.", e["name"])
		elif room is None:
			add("unknown_room", f"{e['session_key']} uses unknown room '{e['room_id']}'.", e["name"])
		else:
			req = ctx.sections.get(e.get("section_key"), {})
			if e.get("session_type") == "LAB":
				if room["type"] not in ("LAB", "EITHER") or (req.get("lab_type") and room.get("lab_type") != req.get("lab_type")):
					add("room_type", f"{e['session_key']} needs lab '{req.get('lab_type')}' but is in {room['name']}.", e["name"])
			else:
				if room["type"] not in ("CLASSROOM", "EITHER"):
					add("room_type", f"{e['session_key']} is a theory session but {room['name']} is a lab.", e["name"])
				elif (req.get("capacity") or 0) > (room.get("capacity") or 0):
					add("room_capacity", f"{e['session_key']} needs {req.get('capacity')} seats; {room['name']} has {room.get('capacity')}.", e["name"])
			missing = [s for s in slots if s not in room["slots"]]
			if missing:
				add("room_unavailable", f"{room['name']} is not available on {where(missing[0])} ({e['session_key']}).", e["name"], slot=missing[0])

		# faculty availability (VIRTUAL_OPEN has no faculty)
		if ctype != "VIRTUAL_OPEN":
			for fid in e.get("faculty_ids") or []:
				avail = ctx.faculty_slots.get(fid)
				if avail is None:
					continue
				missing = [s for s in slots if s not in avail]
				if missing:
					add("faculty_unavailable", f"{fid} is not available on {where(missing[0])} ({e['session_key']}).", e["name"], slot=missing[0])

	# pairwise clashes per slot
	seen = set()
	for slot, items in by_slot.items():
		for a, b in itertools.combinations(items, 2):
			if not ctx.terms_overlap(a.get("term_id"), b.get("term_id")):
				continue
			pair = tuple(sorted((a["name"], b["name"])))
			if a.get("room_id") and a.get("room_id") == b.get("room_id") and ("room",) + pair not in seen:
				seen.add(("room",) + pair)
				name = ctx.rooms.get(a["room_id"], {}).get("name", a["room_id"])
				add("room_double_booked", f"{name} has {a['session_key']} and {b['session_key']} on {where(slot)}.", *pair, slot=slot)
			if ctx.choice(a.get("category")) != "VIRTUAL_OPEN" and ctx.choice(b.get("category")) != "VIRTUAL_OPEN":
				common_f = set(a.get("faculty_ids") or []) & set(b.get("faculty_ids") or [])
				if common_f and ("fac",) + pair not in seen:
					seen.add(("fac",) + pair)
					add("faculty_double_booked", f"{', '.join(sorted(common_f))} teaches {a['session_key']} and {b['session_key']} on {where(slot)}.", *pair, slot=slot)
			common_c = (set(a.get("cohorts") or []) & set(b.get("cohorts") or [])) - {"ALL", ""}
			if common_c and not cohorts_may_share(ctx, a, b) and ("coh",) + pair not in seen:
				seen.add(("coh",) + pair)
				add("cohort_clash", f"Cohort {', '.join(sorted(common_c))} has {a['session_key']} and {b['session_key']} on {where(slot)}.", *pair, slot=slot)

	# same section twice on one day
	per_day: dict[tuple, list[dict]] = defaultdict(list)
	for e in entries:
		per_day[(e["section_key"], int(e["day_index"]))].append(e)
	for (sk, d), items in per_day.items():
		if len(items) > 1:
			day = ctx.week.days[d] if 0 <= d < len(ctx.week.days) else f"day {d}"
			add("same_day", f"{sk} has {len(items)} sessions on {day}.", *[i["name"] for i in items])
	return issues


def free_slots(entries: list[dict], ctx: Context, kind: str, key: str, term_id: str | None = None) -> list[int]:
	"""Absolute slots (0-35) where a cohort / faculty / room is free."""
	busy: set[int] = set()
	for e in entries:
		if term_id and not ctx.terms_overlap(term_id, e.get("term_id")):
			continue
		hit = (
			(kind == "cohort" and key in (e.get("cohorts") or []))
			or (kind == "faculty" and key in (e.get("faculty_ids") or []))
			or (kind == "room" and key == e.get("room_id"))
		)
		if hit:
			busy.update(occupied(e, ctx.week.slots_per_day))
	allowed = set(range(ctx.week.total))
	if kind == "faculty" and key in ctx.faculty_slots:
		allowed &= ctx.faculty_slots[key]
	if kind == "room" and key in ctx.rooms:
		allowed &= ctx.rooms[key]["slots"]
	return sorted(allowed - busy)
