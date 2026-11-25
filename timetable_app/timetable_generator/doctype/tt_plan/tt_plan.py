# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from timetable_app.engine.scenario_builder import split_list
from timetable_app.engine.week import ALL_DAYS, MAX_SLOTS_PER_DAY
from timetable_app.timetable_generator.utils import DAY_FIELDS, clear_week_cache

DEFAULT_SLOTS = [
	("Early morning", "06:30:00", "08:00:00", 0),
	("Slot 1", "08:30:00", "10:30:00", 1),
	("Slot 2", "10:45:00", "12:45:00", 1),
	("Slot 3", "13:45:00", "15:45:00", 1),
	("Slot 4", "16:00:00", "18:00:00", 1),
	("Evening", "18:45:00", "20:45:00", 0),
]

WEIGHT_FIELDS = ["w_meeting", "w_faculty_rest", "w_faculty_free_day", "w_session_gap", "w_balance", "w_building", "w_layout"]

# Fields holding absolute slot numbers (day x slots_per_day + slot) or day indices, remapped when the week changes.
ABS_SLOT_FIELDS = {"TT Section": ["allowed_slots", "preferred_slot"], "TT Category": ["allowed_slots", "preferred_slots"], "TT Meeting": ["meeting_slots"]}
DAY_INDEX_FIELDS = {"TT Section": ["allowed_days"], "TT Category": ["allowed_days"]}

# Every DocType that belongs to a plan, children first (deletion order).
PLAN_DOCTYPES = ["TT Entry", "TT Version", "TT Section", "TT Meeting", "TT Faculty", "TT Room", "TT Category", "TT Term", "TT Programme"]


class TTPlan(Document):
	def validate(self):
		self.plan_name = (self.plan_name or "").strip()
		if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The plan ends before it starts."))
		self.set_default_slots()
		self.validate_week()
		self._week_change = self.detect_week_change()
		self.validate_lunch()
		for f in WEIGHT_FIELDS:
			v = self.get(f)
			if v is None:
				self.set(f, 100)
			elif not 0 <= v <= 1000:
				frappe.throw(_("{0} must be between 0 and 1000.").format(self.meta.get_label(f)))
		if not 1 <= (self.time_limit or 0) <= 600:
			frappe.throw(_("Time limit must be 1 to 600 minutes."))
		if not 1 <= (self.num_workers or 0) <= 64:
			frappe.throw(_("Solver threads must be 1 to 64."))

	def set_default_slots(self):
		if self.slots:
			return
		for i, (label, start, end, regular) in enumerate(DEFAULT_SLOTS):
			self.append("slots", {"slot_index": i, "label": label, "start_time": start, "end_time": end, "regular": regular})

	def validate_week(self):
		days = [d[:3].title() for d in split_list(self.teaching_days or "Mon,Tue,Wed,Thu,Fri,Sat")]
		bad = [d for d in days if d not in ALL_DAYS]
		if bad:
			frappe.throw(_("Unknown teaching day(s): {0}. Use Mon, Tue, Wed, Thu, Fri, Sat, Sun.").format(", ".join(bad)))
		if not days or len(set(days)) != len(days):
			frappe.throw(_("Choose each teaching day once (at least one)."))
		days = sorted(days, key=ALL_DAYS.index)
		self.teaching_days = ",".join(days)
		regular = [d[:3].title() for d in split_list(self.regular_days or "")]
		if [d for d in regular if d not in days]:
			frappe.throw(_("Regular days must be teaching days."))
		if not regular:
			frappe.throw(_("Choose at least one regular day (used when a section or category does not list allowed slots)."))
		self.regular_days = ",".join(sorted(set(regular), key=ALL_DAYS.index))

		if not 1 <= len(self.slots) <= MAX_SLOTS_PER_DAY:
			frappe.throw(_("A day needs 1 to {0} time slots.").format(MAX_SLOTS_PER_DAY))
		# slot numbers follow the row order; renumber 0..n-1
		self.slots.sort(key=lambda r: (r.idx or 0))
		for i, r in enumerate(self.slots):
			r.slot_index = i
			r.idx = i + 1
			r.label = (r.label or f"Slot {i}").strip()
			r.start_time = _clean_time(r.start_time, r.label)
			r.end_time = _clean_time(r.end_time, r.label)
			if r.start_time and r.end_time and r.end_time <= r.start_time:
				frappe.throw(_("Time slot '{0}' ends before it starts.").format(r.label))
		if not any(r.regular for r in self.slots):
			frappe.throw(_("Mark at least one slot as a regular teaching slot."))

	def validate_lunch(self):
		vals = [int(float(v)) for v in split_list(self.lunch_slots or "")]
		if self._week_change:
			vals = [self._week_change["slot_map"][v] for v in vals if v in self._week_change["slot_map"]]
		if any(v < 0 or v >= len(self.slots) for v in vals):
			frappe.throw(_("Blocked slots must be between 0 and {0}.").format(len(self.slots) - 1))
		vals = sorted(set(vals))
		if vals and vals != list(range(vals[0], vals[0] + len(vals))):
			frappe.throw(_("Blocked slots must be consecutive, e.g. 3 or 3,4."))
		self.lunch_slots = ",".join(map(str, vals))

	def detect_week_change(self):
		"""Old -> new mapping of days and slots when the week structure changed."""
		if self.is_new():
			return None
		old = self.get_doc_before_save()
		if not old:
			return None
		old_days = [d for d in split_list(old.teaching_days or "Mon,Tue,Wed,Thu,Fri,Sat")]
		new_days = self.teaching_days.split(",")
		old_rows = sorted(old.slots, key=lambda r: int(r.slot_index))
		if any(r.name for r in self.slots):
			# rows keep their identity (moved, inserted or deleted slots are followed)
			new_pos = {r.name: r.slot_index for r in self.slots if r.name}
			slot_map = {int(r.slot_index): new_pos[r.name] for r in old_rows if r.name in new_pos}
		else:
			# rows were sent without their ids: match by position
			slot_map = {i: i for i in range(min(len(old_rows), len(self.slots)))}
		unchanged = old_days == new_days and len(old_rows) == len(self.slots) and all(k == v for k, v in slot_map.items()) and len(slot_map) == len(old_rows)
		if unchanged:
			return None
		# Appending slots at the end of the day or days at the end of the week keeps every existing
		# (day, slot) position, so existing timetable versions stay valid.
		append_only = new_days[: len(old_days)] == old_days and len(slot_map) == len(old_rows) and all(k == v for k, v in slot_map.items())
		if not append_only and frappe.db.exists("TT Version", {"plan": self.name}):
			frappe.throw(_("This plan already has timetable versions. You can add time slots at the end of the day or days at the end of "
						   "the week, but inserting, removing or reordering slots or days would invalidate them. Delete the versions or "
						   "copy the plan first."))  # fmt: skip
		return {"old_days": old_days, "old_spd": len(old_rows), "new_days": new_days, "new_spd": len(self.slots), "slot_map": slot_map}

	def on_update(self):
		clear_week_cache(self.name)
		if self._week_change:
			dropped = remap_plan_data(self.name, self._week_change)
			if dropped:
				frappe.msgprint(_("The week changed: {0} slot values that no longer exist (removed days or slots) were dropped from sections, categories, meetings and availability.").format(dropped),
								indicator="orange", alert=True)  # fmt: skip

	def on_trash(self):
		if frappe.db.exists("TT Version", {"plan": self.name, "run_status": ("in", ["Queued", "Running"])}):
			frappe.throw(_("A timetable is being generated for this plan. Cancel it first."))
		frappe.db.set_value("TT Plan", self.name, "active_version", None, update_modified=False)
		for dt in PLAN_DOCTYPES:
			frappe.db.delete(dt, {"plan": self.name})


def _clean_time(value, label: str):
	"""'6:30', '6:30:', '06:30:00' or a timedelta -> '06:30:00'; empty -> None."""
	if value in (None, ""):
		return None
	parts = [p for p in str(value).strip().split(":") if p != ""]
	try:
		h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
	except (ValueError, IndexError):
		frappe.throw(_("Time slot '{0}' has an invalid time '{1}'.").format(label, value))
	if not (0 <= h <= 23 and 0 <= m <= 59):
		frappe.throw(_("Time slot '{0}' has an invalid time '{1}'.").format(label, value))
	return f"{h:02d}:{m:02d}:00"


def remap_plan_data(plan: str, change: dict) -> int:
	"""Rewrite stored slot numbers so they keep pointing at the same day and slot."""
	old_days, old_spd, new_days, new_spd, smap = (change[k] for k in ("old_days", "old_spd", "new_days", "new_spd", "slot_map"))
	dropped = 0

	def abs_slots(value):
		nonlocal dropped
		out = set()
		for v in split_list(value or ""):
			d, s = divmod(int(float(v)), old_spd)
			if d < len(old_days) and old_days[d] in new_days and s in smap:
				out.add(new_days.index(old_days[d]) * new_spd + smap[s])
			else:
				dropped += 1
		return ",".join(map(str, sorted(out)))

	def day_indices(value):
		nonlocal dropped
		out = set()
		for v in split_list(value or ""):
			d = int(float(v))
			if d < len(old_days) and old_days[d] in new_days:
				out.add(new_days.index(old_days[d]))
			else:
				dropped += 1
		return ",".join(map(str, sorted(out)))

	def availability(value):
		nonlocal dropped
		raw = (value or "").strip().upper()
		if raw in ("", "NONE", "ALL"):
			return raw or "NONE"
		out = set()
		for v in split_list(raw):
			s = int(float(v))
			if s in smap:
				out.add(smap[s])
			else:
				dropped += 1
		return "ALL" if len(out) == new_spd else (",".join(map(str, sorted(out))) or "NONE")

	for dt in ("TT Section", "TT Category", "TT Meeting"):
		fields = ABS_SLOT_FIELDS.get(dt, []) + DAY_INDEX_FIELDS.get(dt, [])
		for row in frappe.get_all(dt, filters={"plan": plan}, fields=["name", *fields], limit=0):
			values = {f: abs_slots(row[f]) for f in ABS_SLOT_FIELDS.get(dt, []) if row[f]}
			values.update({f: day_indices(row[f]) for f in DAY_INDEX_FIELDS.get(dt, []) if row[f]})
			if values:
				frappe.db.set_value(dt, row.name, values, update_modified=False)
	# timetable versions: solver hints and the allowed starts kept on sessions
	import json

	for v in frappe.get_all("TT Version", filters={"plan": plan}, fields=["name", "hint"], limit=0):
		if v.hint:
			hint = {k: abs_slots(str(x)) for k, x in json.loads(v.hint).items()}
			frappe.db.set_value("TT Version", v.name, "hint", json.dumps({k: int(x) for k, x in hint.items() if x != ""}), update_modified=False)
	for e in frappe.get_all("TT Entry", filters={"plan": plan, "allowed_starts": ("not in", ["", "[]"])}, fields=["name", "allowed_starts"], limit=0):
		starts = abs_slots(",".join(str(x) for x in json.loads(e.allowed_starts or "[]")))
		frappe.db.set_value("TT Entry", e.name, "allowed_starts", json.dumps([int(x) for x in starts.split(",") if x != ""]), update_modified=False)

	for dt in ("TT Room", "TT Faculty"):
		for row in frappe.get_all(dt, filters={"plan": plan}, fields=["name", *DAY_FIELDS], limit=0):
			values = {f: availability(row[f]) for f in DAY_FIELDS}
			if any(values[f] != (row[f] or "NONE") for f in DAY_FIELDS):
				frappe.db.set_value(dt, row.name, values, update_modified=False)
	return dropped
