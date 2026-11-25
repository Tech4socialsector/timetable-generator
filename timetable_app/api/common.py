"""Shared helpers: permissions and converting a plan's DocTypes to engine inputs."""

from __future__ import annotations

import json

import frappe
from frappe import _

from timetable_app.engine.checks import Context
from timetable_app.engine.scenario_builder import (
	normalise_choice_type,
	parse_availability,
	parse_date,
	split_list,
)

from timetable_app.timetable_generator.utils import DAY_FIELDS, plan_week  # noqa: E402


# --------------------------------------------------------------------------- permissions


def check_plan(plan: str, ptype: str = "read"):
	if not plan or not frappe.db.exists("TT Plan", plan):
		frappe.throw(_("Plan {0} not found.").format(plan), frappe.DoesNotExistError)
	if not frappe.has_permission("TT Plan", ptype, plan):
		frappe.throw(_("You do not have permission to {0} plan {1}.").format(ptype, plan), frappe.PermissionError)


def check_version(version: str, ptype: str = "read") -> dict:
	row = frappe.db.get_value("TT Version", version, ["name", "plan", "approval_status", "run_status"], as_dict=True)
	if not row:
		frappe.throw(_("Version {0} not found.").format(version), frappe.DoesNotExistError)
	if not frappe.has_permission("TT Version", ptype, version):
		frappe.throw(_("You do not have permission to {0} this version.").format(ptype), frappe.PermissionError)
	return row


def is_manager() -> bool:
	roles = set(frappe.get_roles())
	return bool(roles & {"Timetable Manager", "System Manager"})


def require_manager():
	if not is_manager():
		frappe.throw(_("Only the programme office (Timetable Manager) can do this."), frappe.PermissionError)


def loads(value, default=None):
	if not value:
		return default
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


# --------------------------------------------------------------------------- plan -> rows


def _all(doctype: str, plan: str, fields: list[str], order_by: str = "creation asc") -> list[dict]:
	return frappe.get_all(doctype, filters={"plan": plan}, fields=fields, order_by=order_by, limit_page_length=0)


def plan_rows(plan: str) -> dict[str, list[dict]]:
	"""The plan's data in the workbook row format understood by ScenarioBuilder."""
	rows: dict[str, list[dict]] = {}
	rows["Programs"] = [
		{"program_id": p.program_id, "program_name": p.program_name}
		for p in _all("TT Programme", plan, ["program_id", "program_name"])
	]
	rows["Terms"] = [
		{"term_id": t.term_id, "start_date": t.start_date, "end_date": t.end_date}
		for t in _all("TT Term", plan, ["term_id", "start_date", "end_date"])
	]
	rows["Categories"] = [
		{"Name": c.category_name, "ID": c.category_id, "choice_type": c.choice_type, "choice_count": c.choice_count,
		 "allowed_slots": c.allowed_slots, "allowed_days": c.allowed_days, "preferred_slot": c.preferred_slots}
		for c in _all("TT Category", plan, ["category_id", "category_name", "choice_type", "choice_count", "allowed_slots", "allowed_days", "preferred_slots"])
	]  # fmt: skip
	rows["Rooms"] = [
		{"id": r.room_id, "name": r.room_name, "type": r.room_type, "classroom_capacity": r.capacity, "room_layout": r.layouts,
		 "lab_type": r.lab_type, "building": r.building, **{f.title(): r[f] for f in DAY_FIELDS}}
		for r in _all("TT Room", plan, ["room_id", "room_name", "room_type", "capacity", "layouts", "lab_type", "building", *DAY_FIELDS])
	]  # fmt: skip
	rows["Faculty"] = [
		{"id": f.faculty_id, "name": f.faculty_name, "program_id": f.program_ids, "Evening?": "Yes" if f.evening else "No",
		 "Remarks": f.remarks, **{d.title(): f[d] for d in DAY_FIELDS}}
		for f in _all("TT Faculty", plan, ["faculty_id", "faculty_name", "program_ids", "evening", "remarks", *DAY_FIELDS])
	]  # fmt: skip
	rows["Meeting Slots"] = [
		{"program_id": m.program_id, "term_id": m.term_id, "meeting_slots": m.meeting_slots, "attendee_type": m.attendee_type}
		for m in _all("TT Meeting", plan, ["program_id", "term_id", "meeting_slots", "attendee_type"])
	]
	sec_fields = [
		"serial_no", "course_code", "section_number", "course_name", "category", "faculty_ids", "theory_durations", "lab_durations",
		"required_room_capacity", "preferred_theory_layouts", "preferred_theory_buildings", "required_lab_type",
		"required_cohorts", "optional_cohorts", "allowed_slots", "allowed_days", "preferred_slot", "program_ids", "term_id",
		"start_date", "end_date", "preferred_lab_buildings", "preferred_lab_layouts", "school", "remarks", "credits", "group_name",
	]  # fmt: skip
	rows["Sections"] = [
		{**{k: s[k] for k in sec_fields if k not in ("serial_no", "faculty_ids", "start_date", "end_date", "remarks", "credits", "group_name")},
		 "SI no": s.serial_no, "faculty_id": s.faculty_ids, "Start date": s.start_date, "End date": s.end_date, "Remarks": s.remarks,
		 "Credits": s.credits, "Group": s.group_name,
		 "required_room_capacity": s.required_room_capacity or None}
		for s in _all("TT Section", plan, sec_fields, order_by="course_code asc, section_number asc")
	]  # fmt: skip
	return rows


def lunch_slots(plan: str) -> list[int]:
	raw = frappe.db.get_value("TT Plan", plan, "lunch_slots") or ""
	return [int(v) for v in split_list(raw)]


def build_context(plan: str) -> Context:
	week = plan_week(plan)
	spd = week.slots_per_day
	ctx = Context(week=week)
	for t in _all("TT Term", plan, ["term_id", "start_date", "end_date"]):
		ctx.terms[t.term_id.upper()] = (parse_date(t.start_date), parse_date(t.end_date))
	for c in _all("TT Category", plan, ["category_id", "choice_type"]):
		ctx.choice_types.setdefault(c.category_id.lower(), normalise_choice_type(c.choice_type))
	day_fields = [d.lower() for d in week.days]
	for r in _all("TT Room", plan, ["room_id", "room_name", "room_type", "capacity", "lab_type", "building", *DAY_FIELDS]):
		slots = set()
		for d, f in enumerate(day_fields):
			slots.update(d * spd + s for s in parse_availability(r[f] or "ALL", spd) if s < spd)
		ctx.rooms[r.room_id] = {"name": r.room_name, "type": r.room_type, "capacity": r.capacity or 0,
								"lab_type": (r.lab_type or "").upper(), "building": r.building, "slots": slots}  # fmt: skip
	for f in _all("TT Faculty", plan, ["faculty_id", *DAY_FIELDS]):
		slots = set()
		for d, fld in enumerate(day_fields):
			slots.update(d * spd + s for s in parse_availability(f[fld] or "", spd) if s < spd)
		ctx.faculty_slots[f.faculty_id.lower()] = slots
	for s in _all("TT Section", plan, ["section_key", "required_room_capacity", "required_lab_type"]):
		ctx.sections[s.section_key] = {"capacity": s.required_room_capacity or 0, "lab_type": (s.required_lab_type or "").upper()}
	return ctx


def week_payload(plan: str) -> dict:
	"""The plan's week for the UI."""
	w = plan_week(plan)
	return {"days": list(w.days), "slots_per_day": w.slots_per_day, "regular_days": sorted(w.regular_days, key=list(w.days).index),
			"regular_slots": sorted(w.regular_slots), "total": w.total}  # fmt: skip


def entry_dicts(version: str) -> list[dict]:
	fields = ["name", "session_key", "section_key", "course_code", "course_name", "category", "session_type", "session_index",
			  "day_index", "slot_index", "duration", "room_id", "room_name", "term_id", "is_manual", "faculty_ids", "cohorts",
			  "program_ids", "allowed_starts"]  # fmt: skip
	out = frappe.get_all("TT Entry", filters={"version": version}, fields=fields, order_by="day_index asc, slot_index asc, course_code asc", limit_page_length=0)
	for e in out:
		e["faculty_ids"] = split_list(e.get("faculty_ids") or "")
		e["cohorts"] = split_list(e.get("cohorts") or "", upper=True)
		e["program_ids"] = split_list(e.get("program_ids") or "", upper=True)
		e["allowed_starts"] = loads(e.get("allowed_starts"), [])
	return out
