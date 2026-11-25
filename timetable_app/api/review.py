"""Review & adjust: grid data, manual moves with conflict checks, free slots, approval."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from timetable_app.api.common import (
	build_context,
	check_plan,
	check_version,
	entry_dicts,
	is_manager,
	loads,
	require_manager,
	week_payload,
)
from timetable_app.engine.checks import check_entries, free_slots, occupied

EDITABLE = ("Draft", "Changes Requested")


def _hhmm(t) -> str:
	"""timedelta / time / '6:30:00' -> '06:30'"""
	if not t:
		return ""
	parts = str(t).split(":")
	return f"{int(parts[0]):02d}:{parts[1]}" if len(parts) >= 2 else str(t)


@frappe.whitelist()
def get_version(version: str) -> dict:
	v = check_version(version)
	doc = frappe.get_doc("TT Version", version)
	plan = frappe.get_doc("TT Plan", v.plan)
	data = doc.as_dict(no_default_fields=False)
	for f in ("progress", "weights", "violations", "checks", "stats"):
		data[f] = loads(data.get(f), [] if f in ("violations", "checks") else {})
	data.pop("hint", None)
	data.pop("log", None)
	data["has_log"] = bool(doc.log)
	data["editable"] = doc.approval_status in EDITABLE and doc.run_status == "Completed" and is_manager()
	data["slots"] = [{"slot_index": s.slot_index, "label": s.label, "start_time": _hhmm(s.start_time), "end_time": _hhmm(s.end_time), "regular": s.regular} for s in plan.slots]
	data["plan_status"] = plan.status
	data["week"] = week_payload(v.plan)
	data["active_version"] = plan.active_version
	return data


@frappe.whitelist()
def get_entries(version: str) -> dict:
	v = check_version(version)
	entries = entry_dicts(version)
	categories = {c.category_id: c.choice_type for c in frappe.get_all("TT Category", filters={"plan": v.plan}, fields=["category_id", "choice_type"], limit_page_length=0)}
	faculty = {f.faculty_id: f.faculty_name for f in frappe.get_all("TT Faculty", filters={"plan": v.plan}, fields=["faculty_id", "faculty_name"], limit_page_length=0)}
	rooms = frappe.get_all("TT Room", filters={"plan": v.plan}, fields=["room_id", "room_name", "building", "capacity", "room_type", "lab_type"], order_by="room_name asc", limit_page_length=0)
	return {"entries": entries, "categories": categories, "faculty": faculty, "rooms": rooms}


@frappe.whitelist()
def get_log(version: str) -> str:
	check_version(version)
	return frappe.db.get_value("TT Version", version, "log") or ""


def _load_entry(name: str) -> tuple[dict, dict]:
	row = frappe.db.get_value("TT Entry", name, ["version"], as_dict=True)
	if not row:
		frappe.throw(_("Session not found."), frappe.DoesNotExistError)
	v = check_version(row.version, "write")
	return row, v


def _conflicts_for(candidate: dict, others: list[dict], ctx) -> list[dict]:
	"""Hard issues that involve the candidate entry."""
	spd = ctx.week.slots_per_day
	slots = set(occupied(candidate, spd))
	nearby = [o for o in others if o["name"] != candidate["name"] and (slots & set(occupied(o, spd)) or o["section_key"] == candidate["section_key"])]
	return [i for i in check_entries([candidate, *nearby], ctx) if candidate["name"] in i["entries"]]


def _room_suits(e: dict, room: dict, ctx) -> bool:
	req = ctx.sections.get(e["section_key"], {})
	if e["session_type"] == "LAB":
		return room["type"] in ("LAB", "EITHER") and (not req.get("lab_type") or room.get("lab_type") == req.get("lab_type"))
	return room["type"] in ("CLASSROOM", "EITHER") and (room.get("capacity") or 0) >= (req.get("capacity") or 0)


@frappe.whitelist()
def move_options(entry: str) -> dict:
	"""For every possible start slot: is it clash-free, and which rooms are free and suitable."""
	_row, v = _load_entry(entry)
	entries = entry_dicts(v.name)
	ctx = build_context(v.plan)
	me = next(e for e in entries if e["name"] == entry)
	dur = int(me["duration"] or 1)
	needs_room = bool(me["room_id"]) or ctx.choice(me["category"]) not in ("VIRTUAL_STAFFED", "VIRTUAL_OPEN")
	busy: dict[int, set[str]] = {}
	for o in entries:
		if o["name"] != entry and o["room_id"] and ctx.terms_overlap(me["term_id"], o["term_id"]):
			for sl in occupied(o, ctx.week.slots_per_day):
				busy.setdefault(sl, set()).add(o["room_id"])
	suitable = [rid for rid, r in ctx.rooms.items() if _room_suits(me, r, ctx)] if needs_room else []
	options = []
	week = ctx.week
	for start in range(week.total):
		d, s = week.split(start)
		if s + dur > week.slots_per_day:
			continue
		span = range(start, start + dur)
		people = [i for i in _conflicts_for({**me, "day_index": d, "slot_index": s, "room_id": ""}, entries, ctx)
				  if i["rule"] not in ("no_room", "unknown_room", "room_type", "room_capacity", "room_unavailable")]  # fmt: skip
		free_rooms = [rid for rid in suitable if all(sl in ctx.rooms[rid]["slots"] and rid not in busy.get(sl, ()) for sl in span)]
		options.append({
			"day_index": d, "slot_index": s, "current": d == me["day_index"] and s == me["slot_index"],
			"solver_allowed": (not me["allowed_starts"]) or start in me["allowed_starts"],
			"issues": [i["message"] for i in people], "rules": sorted({i["rule"] for i in people}),
			"free_rooms": free_rooms, "current_room_free": me["room_id"] in free_rooms,
		})  # fmt: skip
	return {"entry": me, "options": options, "needs_room": needs_room}


@frappe.whitelist()
def move_entry(entry: str, day_index: int, slot_index: int, room_id: str | None = None, force: int = 0) -> dict:
	_row, v = _load_entry(entry)
	require_manager()
	if v.approval_status not in EDITABLE:
		frappe.throw(_("Only draft versions can be changed. Create an editable copy first."))
	d, s = cint(day_index), cint(slot_index)
	entries = entry_dicts(v.name)
	ctx = build_context(v.plan)
	me = next(e for e in entries if e["name"] == entry)
	week = ctx.week
	if not (0 <= d < len(week.days) and 0 <= s and s + int(me["duration"] or 1) <= week.slots_per_day):
		frappe.throw(_("The session does not fit in that slot."))
	new_room = me["room_id"] if room_id is None else (room_id or "")
	if new_room and new_room not in ctx.rooms:
		frappe.throw(_("Unknown room {0}.").format(new_room))
	cand = {**me, "day_index": d, "slot_index": s, "room_id": new_room}
	issues = _conflicts_for(cand, entries, ctx)
	if issues and not cint(force):
		return {"saved": False, "issues": issues}
	frappe.db.set_value("TT Entry", entry, {
		"day_index": d, "slot_index": s, "room_id": new_room,
		"room_name": ctx.rooms.get(new_room, {}).get("name", "") if new_room else "", "is_manual": 1,
	})  # fmt: skip
	all_issues = check_entries(entry_dicts(v.name), ctx)
	frappe.db.set_value("TT Version", v.name, {"checks": json.dumps(all_issues), "hard_issues": len(all_issues)})
	frappe.get_doc("TT Version", v.name).add_comment(
		"Info", _("Moved {0} to {1} slot {2}{3}").format(me["session_key"], week.days[d], s, f", room {new_room}" if new_room else "")
	)
	return {"saved": True, "issues": issues, "hard_issues": len(all_issues)}


@frappe.whitelist()
def get_free_slots(version: str, kind: str, key: str, term_id: str | None = None) -> list[int]:
	v = check_version(version)
	if kind not in ("cohort", "faculty", "room"):
		frappe.throw(_("Unknown kind {0}.").format(kind))
	key = key.upper() if kind == "cohort" else (key.lower() if kind == "faculty" else key)
	return free_slots(entry_dicts(version), build_context(v.plan), kind, key, term_id or None)


# --------------------------------------------------------------------------- versions & approval


def _set_status(version: str, status: str, comment: str | None, **extra):
	frappe.db.set_value("TT Version", version, {"approval_status": status, **extra})
	frappe.get_doc("TT Version", version).add_comment("Info", f"{status}{': ' + comment if comment else ''}")


@frappe.whitelist()
def submit_version(version: str, comment: str | None = None):
	v = check_version(version, "write")
	require_manager()
	if v.run_status != "Completed" or v.approval_status not in EDITABLE:
		frappe.throw(_("Only completed draft versions can be submitted."))
	_set_status(version, "Submitted", comment, submitted_by=frappe.session.user, submitted_on=now_datetime(), notes=comment or None)
	return "ok"


def _require_approver():
	if not set(frappe.get_roles()) & {"Timetable Approver", "System Manager"}:
		frappe.throw(_("Only a Timetable Approver can do this."), frappe.PermissionError)


@frappe.whitelist()
def approve_version(version: str, comment: str | None = None):
	v = check_version(version)
	_require_approver()
	if v.approval_status != "Submitted":
		frappe.throw(_("Only submitted versions can be approved."))
	hard = frappe.db.get_value("TT Version", version, "hard_issues") or 0
	if hard and not comment:
		frappe.throw(_("This version has {0} hard issues. Add a comment explaining why it is approved anyway.").format(hard))
	for other in frappe.get_all("TT Version", filters={"plan": v.plan, "approval_status": "Approved", "name": ("!=", version)}, pluck="name"):
		_set_status(other, "Superseded", _("Replaced by {0}").format(version))
	_set_status(version, "Approved", comment, reviewed_by=frappe.session.user, reviewed_on=now_datetime(), review_comment=comment)
	frappe.db.set_value("TT Plan", v.plan, {"active_version": version, "status": "Finalised"})
	return "ok"


@frappe.whitelist()
def request_changes(version: str, comment: str):
	v = check_version(version)
	_require_approver()
	if v.approval_status != "Submitted":
		frappe.throw(_("Only submitted versions can be sent back."))
	if not (comment or "").strip():
		frappe.throw(_("Say what needs to change."))
	_set_status(version, "Changes Requested", comment, reviewed_by=frappe.session.user, reviewed_on=now_datetime(), review_comment=comment)
	return "ok"


@frappe.whitelist()
def reopen_plan(plan: str):
	check_plan(plan, "write")
	require_manager()
	frappe.db.set_value("TT Plan", plan, "status", "Generated")
	return "ok"


@frappe.whitelist()
def copy_version(version: str, label: str | None = None) -> str:
	"""Editable copy of any completed version (e.g. to adjust an approved timetable)."""
	v = check_version(version)
	require_manager()
	src = frappe.get_doc("TT Version", version)
	if src.run_status != "Completed":
		frappe.throw(_("Only completed versions can be copied."))
	if frappe.db.get_value("TT Plan", v.plan, "status") == "Finalised":
		frappe.throw(_("The plan is finalised. Reopen it before creating a new version."))
	new = frappe.get_doc({
		"doctype": "TT Version", "plan": src.plan, "version_label": label or f"{src.version_label} (copy)", "source": src.source,
		"run_status": "Completed", "approval_status": "Draft", "solver_status": src.solver_status, "objective": src.objective,
		"best_bound": src.best_bound, "wall_time": src.wall_time, "solutions_found": src.solutions_found, "entries_count": src.entries_count,
		"weights": src.weights, "violations": src.violations, "soft_issues": src.soft_issues, "checks": src.checks,
		"hard_issues": src.hard_issues, "stats": src.stats, "hint": src.hint, "hint_from": src.name, "time_limit": src.time_limit,
		"started_at": src.started_at, "finished_at": src.finished_at,
	}).insert()  # fmt: skip
	fields = [f.fieldname for f in frappe.get_meta("TT Entry").fields if f.fieldtype not in ("Section Break", "Column Break")]
	rows = frappe.get_all("TT Entry", filters={"version": version}, fields=fields, limit_page_length=0)
	now, user = now_datetime(), frappe.session.user
	values = [(frappe.generate_hash(length=12), *[new.name if f == "version" else r[f] for f in fields], user, user, now, now, 0) for r in rows]
	frappe.db.bulk_insert("TT Entry", ["name", *fields, "owner", "modified_by", "creation", "modified", "docstatus"], values, chunk_size=500)
	return new.name


@frappe.whitelist()
def update_version(version: str, label: str | None = None, notes: str | None = None):
	check_version(version, "write")
	require_manager()
	values = {}
	if label is not None:
		values["version_label"] = label.strip() or frappe.db.get_value("TT Version", version, "version_label")
	if notes is not None:
		values["notes"] = notes
	if values:
		frappe.db.set_value("TT Version", version, values)
	return "ok"


@frappe.whitelist()
def list_versions(plan: str) -> list[dict]:
	check_plan(plan)
	return frappe.get_all(
		"TT Version",
		filters={"plan": plan},
		fields=["name", "version_label", "source", "run_status", "approval_status", "solver_status", "objective", "wall_time",
				"entries_count", "hard_issues", "soft_issues", "creation", "owner", "finished_at", "submitted_by", "reviewed_by",
				"review_comment", "hint_from", "notes"],  # fmt: skip
		order_by="creation desc",
		limit_page_length=0,
	)
