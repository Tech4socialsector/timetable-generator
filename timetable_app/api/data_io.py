"""Workbook import / export and plan setup helpers."""

from __future__ import annotations

import io
import json
from collections import Counter

import frappe
import openpyxl
from frappe import _
from frappe.utils import cint, now_datetime

from timetable_app.api.common import (
	DAY_FIELDS,
	build_context,
	check_plan,
	plan_rows,
	require_manager,
)
from timetable_app.engine.checks import check_entries
from timetable_app.timetable_generator.utils import plan_week
from timetable_app.engine.scenario_builder import (
	ScenarioBuilder,
	col,
	normalise_choice_type,
	parse_date,
	section_key,
	split_list,
	text,
)
from timetable_app.engine.workbook import INPUT_SHEETS, read_workbook, write_workbook

PLAN_DATA = ["TT Section", "TT Meeting", "TT Faculty", "TT Room", "TT Category", "TT Term", "TT Programme"]


def _file_bytes(file_url: str) -> bytes:
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(_("Uploaded file not found."))
	f = frappe.get_doc("File", name)
	if not (f.file_name or "").lower().endswith((".xlsx", ".xlsm")):
		frappe.throw(_("Upload an Excel .xlsx file."))
	return f.get_content()


def _timetable_sheet(content: bytes) -> list[dict]:
	wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	try:
		ws = next((w for w in wb.worksheets if w.title.strip().lower() == "timetable"), None)
		if ws is None:
			return []
		rows = ws.iter_rows(values_only=True)
		header = [text(h) for h in next(rows, [])]
		return [dict(zip(header, r)) for r in rows if any(text(v) for v in r)]
	finally:
		wb.close()


# --------------------------------------------------------------------------- preview / import


@frappe.whitelist()
def preview_workbook(file_url: str, plan: str | None = None) -> dict:
	require_manager()
	if plan:
		check_plan(plan)
	content = _file_bytes(file_url)
	rows = read_workbook(content)
	result = ScenarioBuilder(rows, week=plan_week(plan)).build()
	tt = _timetable_sheet(content)
	return {
		"sheets": {s: len(rows.get(s, [])) for s in INPUT_SHEETS},
		"missing_sheets": [s for s in INPUT_SHEETS if s not in rows],
		"issues": [i.as_dict() for i in result.issues],
		"errors": len(result.errors),
		"timetable_rows": sum(1 for r in tt if _is_start(r)),
	}


def _is_start(r: dict) -> bool:
	v = r.get("Is Start Slot")
	return v in (True, 1) or str(v).strip().lower() in ("true", "1", "yes")


@frappe.whitelist()
def import_workbook(plan: str, file_url: str, import_timetable: int = 0) -> dict:
	"""Replace the plan's data with the workbook contents."""
	check_plan(plan, "write")
	require_manager()
	if frappe.db.get_value("TT Plan", plan, "status") == "Finalised":
		frappe.throw(_("This plan is finalised. Reopen it before importing data."))
	if frappe.db.exists("TT Version", {"plan": plan, "run_status": ("in", ["Queued", "Running"])}):
		frappe.throw(_("A timetable is being generated for this plan. Wait for it to finish or cancel it."))
	content = _file_bytes(file_url)
	rows = read_workbook(content)
	missing = [s for s in ("Sections", "Faculty", "Rooms", "Categories") if s not in rows]
	if missing:
		frappe.throw(_("The workbook is missing these sheets: {0}").format(", ".join(missing)))

	for dt in PLAN_DATA:
		frappe.db.delete(dt, {"plan": plan})
	frappe.local.tt_auto_faculty = []

	counts: Counter = Counter()
	skipped: list[str] = []

	def insert(doctype, values, ref):
		doc = frappe.get_doc({"doctype": doctype, "plan": plan, **values})
		doc.flags.skip_unique = True
		try:
			doc.insert()
			counts[doctype] += 1
		except frappe.ValidationError as e:
			frappe.clear_last_message()
			skipped.append(f"{doctype} {ref}: {frappe.utils.strip_html(str(e))}")

	seen = set()
	for r in rows.get("Programs", []):
		pid = col(r, "program_id").upper()
		if pid and pid not in seen:
			seen.add(pid)
			insert("TT Programme", {"program_id": pid, "program_name": col(r, "program_name") or pid}, pid)
	seen = set()
	for r in rows.get("Terms", []):
		tid = col(r, "term_id").upper()
		if tid and tid not in seen:
			seen.add(tid)
			insert("TT Term", {"term_id": tid, "start_date": parse_date(r.get("start_date")), "end_date": parse_date(r.get("end_date"))}, tid)
	seen = set()
	for r in rows.get("Categories", []):
		cid = col(r, "ID", "id") or col(r, "Name")
		if not cid or cid.lower() in seen:
			continue
		seen.add(cid.lower())
		insert("TT Category", {
			"category_id": cid, "category_name": col(r, "Name") or cid, "choice_type": normalise_choice_type(col(r, "choice_type")),
			"choice_count": cint(col(r, "choice_count") or 0), "allowed_slots": col(r, "allowed_slots"),
			"allowed_days": col(r, "allowed_days"), "preferred_slots": col(r, "preferred_slot", "preferred_slots"),
		}, cid)  # fmt: skip
	seen = set()
	for r in rows.get("Rooms", []):
		rid = col(r, "id", "room_id")
		if not rid or rid in seen:
			continue
		seen.add(rid)
		cap = col(r, "classroom_capacity", "capacity")
		insert("TT Room", {
			"room_id": rid, "room_name": col(r, "name") or rid, "room_type": col(r, "type").upper() or "CLASSROOM",
			"capacity": cint(float(cap)) if cap else 0, "lab_type": col(r, "lab_type"), "layouts": col(r, "layouts", "room_layout"),
			"building": col(r, "building"), **{f: col(r, f.title()) or "ALL" for f in DAY_FIELDS},
		}, rid)  # fmt: skip
	seen = set()
	for r in rows.get("Faculty", []):
		fid = col(r, "id", "faculty_id").lower()
		if not fid or fid in seen:
			continue
		seen.add(fid)
		insert("TT Faculty", {
			"faculty_id": fid, "faculty_name": col(r, "name") or fid, "program_ids": col(r, "program_ids", "program_id"),
			"evening": 1 if col(r, "Evening?", "evening").lower() in ("yes", "y", "1", "true") else 0, "remarks": col(r, "Remarks"),
			**{f: col(r, f.title()) or "NONE" for f in DAY_FIELDS},
		}, fid)  # fmt: skip
	for r in rows.get("Meeting Slots", []):
		pid = col(r, "program_id")
		if pid:
			insert("TT Meeting", {"program_id": pid, "term_id": col(r, "term_id") or "FULL", "meeting_slots": col(r, "meeting_slots"),
								  "attendee_type": col(r, "attendee_type").upper().replace(" ", "_") or "BOTH"}, pid)  # fmt: skip
	seen = set()
	for r in rows.get("Sections", []):
		code = col(r, "course_code")
		if not code:
			continue
		num = col(r, "section_number") or "1"
		try:
			key = section_key(code, num)
		except ValueError:
			skipped.append(f"TT Section {code}: invalid section number '{num}'")
			continue
		if key in seen:
			skipped.append(f"TT Section {key}: duplicate row")
			continue
		seen.add(key)
		cap = col(r, "required_room_capacity")
		credits = col(r, "Credits", "credits")
		insert("TT Section", {
			"serial_no": col(r, "SI no", "Sl no", "S.No", "serial_no"), "course_code": code, "section_number": cint(float(num)), "course_name": col(r, "course_name"), "category": col(r, "category"),
			"faculty_ids": col(r, "faculty_id", "faculty_ids"), "theory_durations": col(r, "theory_durations"),
			"lab_durations": col(r, "lab_durations"), "required_room_capacity": cint(float(cap)) if cap else 0,
			"required_lab_type": col(r, "required_lab_type"), "required_cohorts": col(r, "required_cohorts", "cohorts"),
			"optional_cohorts": col(r, "optional_cohorts"), "allowed_slots": col(r, "allowed_slots"), "allowed_days": col(r, "allowed_days"),
			"preferred_slot": col(r, "preferred_slot", "preferred_slots"), "program_ids": col(r, "program_ids", "program_id"),
			"term_id": col(r, "term_id") or "FULL", "start_date": parse_date(r.get("Start date")), "end_date": parse_date(r.get("End date")),
			"preferred_theory_buildings": col(r, "preferred_theory_buildings"), "preferred_theory_layouts": col(r, "preferred_theory_layouts"),
			"preferred_lab_buildings": col(r, "preferred_lab_buildings"), "preferred_lab_layouts": col(r, "preferred_lab_layouts"),
			"school": col(r, "school"), "credits": float(credits) if _is_number(credits) else 0, "group_name": col(r, "Group", "group"),
			"remarks": col(r, "Remarks", "remarks"),
		}, key)  # fmt: skip

	auto = getattr(frappe.local, "tt_auto_faculty", None) or []
	frappe.local.tt_auto_faculty = []
	if auto:
		counts["TT Faculty (added from sections)"] = len(set(auto))
	frappe.db.set_value("TT Plan", plan, {"readiness": None, "readiness_checked_on": None, "status": "Setup"}, update_modified=True)
	version = None
	if cint(import_timetable):
		version = _import_timetable(plan, _timetable_sheet(content))
	return {"counts": dict(counts), "skipped": skipped, "version": version}


def _is_number(v) -> bool:
	try:
		float(v)
		return True
	except (TypeError, ValueError):
		return False


def _import_timetable(plan: str, tt_rows: list[dict]) -> str | None:
	"""Create a version from a workbook 'Timetable' sheet (output of the command-line generator)."""
	starts = [r for r in tt_rows if _is_start(r)]
	if not starts:
		return None
	week = plan_week(plan)
	day_index = {d.lower(): i for i, d in enumerate(week.days)}
	sections = {s.section_key: s for s in frappe.get_all("TT Section", filters={"plan": plan},
				fields=["section_key", "course_code", "course_name", "category", "faculty_ids", "required_cohorts", "program_ids", "term_id"], limit_page_length=0)}  # fmt: skip
	rooms_by_name = {r.room_name: r.room_id for r in frappe.get_all("TT Room", filters={"plan": plan}, fields=["room_id", "room_name"], limit_page_length=0)}
	v = frappe.get_doc({"doctype": "TT Version", "plan": plan, "version_label": "Imported from workbook", "source": "Imported",
						"run_status": "Completed", "approval_status": "Draft", "solver_status": "IMPORTED",
						"started_at": now_datetime(), "finished_at": now_datetime()}).insert()  # fmt: skip
	values, hint, now, user = [], {}, now_datetime(), frappe.session.user
	for r in starts:
		session = text(r.get("Session"))
		try:
			head, s_type, idx = session.rsplit("_", 2)
			d = day_index[text(r.get("Assigned Day")).lower()[:3]]
			slot = int(float(text(r.get("Assigned Slot"))))
		except (ValueError, KeyError):
			continue
		sec = sections.get(head)
		if not sec:
			continue
		room_name = text(r.get("Assigned Room"))
		room_id = rooms_by_name.get(room_name, "")
		dur = int(float(text(r.get("Number of Slot")) or 1))
		if slot >= week.slots_per_day:
			continue
		hint[session] = week.abs(d, slot)
		values.append((
			frappe.generate_hash(length=12), v.name, plan, session, head, sec.course_code, sec.course_name, sec.category, s_type,
			int(idx), d, slot, dur, room_id, room_name if room_id else "", sec.term_id, 0, sec.faculty_ids, sec.required_cohorts,
			sec.program_ids, "[]", user, user, now, now, 0,
		))  # fmt: skip
	fields = ["name", "version", "plan", "session_key", "section_key", "course_code", "course_name", "category", "session_type",
			  "session_index", "day_index", "slot_index", "duration", "room_id", "room_name", "term_id", "is_manual", "faculty_ids",
			  "cohorts", "program_ids", "allowed_starts", "owner", "modified_by", "creation", "modified", "docstatus"]  # fmt: skip
	frappe.db.bulk_insert("TT Entry", fields, values, chunk_size=500)
	from timetable_app.api.common import entry_dicts

	issues = check_entries(entry_dicts(v.name), build_context(plan))
	v.db_set({"entries_count": len(values), "hint": json.dumps(hint), "checks": json.dumps(issues), "hard_issues": len(issues), "soft_issues": 0})
	return v.name


# --------------------------------------------------------------------------- export


def _send(filename: str, content: bytes):
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "binary"


@frappe.whitelist()
def download_template():
	examples = {
		"Programs": [["MADEV", "MA Development"]],
		"Terms": [["MADEV_TERM1", "2027-01-18", "2027-05-07"]],
		"Categories": [["Core", "CORE", "NONE", "", "", "", ""], ["Electives set 1", "ELEC1", "GROUPED", "1", "", "", ""]],
		"Rooms": [["R101", "Block A 101", "CLASSROOM", 50, "", "", "BLOCK A", "ALL", "ALL", "ALL", "ALL", "ALL", "NONE"]],
		"Faculty": [["jane.doe@example.edu", "Jane Doe", "1,2,3,4", "1,2,3,4", "ALL", "ALL", "1,2", "NONE", "MADEV", "No", ""]],
		"Meeting Slots": [["MADEV", "MADEV_TERM1", "14,15,16", "STUDENT_ONLY"]],
		"Sections": [["DEV101", 1, "Development Theory", "CORE", "jane.doe@example.edu", "1,1", "", 40, "", "", "", "MADEV26", "",
					  "", "", "", "MADEV", "MADEV_TERM1", "2027-01-18", "2027-05-07", "", "", "SoDev", "", 4, ""]],
	}  # fmt: skip
	sheets = {name: (cols, examples.get(name, [])) for name, cols in INPUT_SHEETS.items()}
	_send("timetable_input_template.xlsx", write_workbook(sheets))


def plan_sheet_columns(plan: str) -> dict[str, list[str]]:
	"""Workbook columns for this plan: the Rooms / Faculty day columns follow the plan's teaching days."""
	days = list(plan_week(plan).days)
	out = {}
	for name, cols in INPUT_SHEETS.items():
		if name in ("Rooms", "Faculty"):
			first = cols.index("Mon")
			cols = [*cols[:first], *days, *[c for c in cols[first:] if c not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]]
		out[name] = cols
	return out


@frappe.whitelist()
def export_inputs(plan: str):
	check_plan(plan)
	rows = plan_rows(plan)
	sheets = {}
	for name, cols in plan_sheet_columns(plan).items():
		data = rows.get(name, [])
		sheets[name] = (cols, [[r.get(c) for c in cols] for r in data])
	_send(f"{frappe.scrub(plan)}_inputs.xlsx", write_workbook(sheets))


# --------------------------------------------------------------------------- plan setup


@frappe.whitelist()
def create_plan(plan_name: str, campus: str | None = None, academic_year: str | None = None, start_date=None, end_date=None, copy_from: str | None = None) -> str:
	require_manager()
	if not frappe.has_permission("TT Plan", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	p = frappe.get_doc({"doctype": "TT Plan", "plan_name": plan_name, "campus": campus, "academic_year": academic_year,
						"start_date": start_date or None, "end_date": end_date or None})  # fmt: skip
	if copy_from:
		check_plan(copy_from)
		src = frappe.get_doc("TT Plan", copy_from)
		for f in ("lunch_slots", "time_limit", "num_workers", "cross_term_overlap", "w_meeting", "w_faculty_rest", "w_faculty_free_day",
				  "w_session_gap", "w_balance", "w_building", "w_layout"):  # fmt: skip
			p.set(f, src.get(f))
		for s in src.slots:
			p.append("slots", {k: s.get(k) for k in ("slot_index", "label", "start_time", "end_time", "regular")})
	p.insert()
	if copy_from:
		skip = {"name", "plan", "owner", "creation", "modified", "modified_by", "idx", "docstatus", "doctype", "_user_tags", "_comments", "_assign", "_liked_by", "_seen"}
		for dt in reversed(PLAN_DATA):
			for row in frappe.get_all(dt, filters={"plan": copy_from}, fields=["*"], limit_page_length=0):
				doc = frappe.get_doc({"doctype": dt, "plan": p.name, **{k: v for k, v in row.items() if k not in skip}})
				doc.flags.skip_unique = True
				doc.insert()
	return p.name


@frappe.whitelist()
def get_options(plan: str) -> dict:
	"""Values for pickers in the UI."""
	check_plan(plan)

	def vals(dt, field):
		return sorted({r[0] for r in frappe.get_all(dt, filters={"plan": plan}, fields=[field], as_list=True, limit_page_length=0) if r[0]})

	cohorts, buildings_layouts = set(), {"buildings": set(), "layouts": set(), "lab_types": set()}
	for r in frappe.get_all("TT Section", filters={"plan": plan}, fields=["required_cohorts", "optional_cohorts"], limit_page_length=0):
		cohorts.update(split_list(r.required_cohorts or "", upper=True))
		cohorts.update(split_list(r.optional_cohorts or "", upper=True))
	for r in frappe.get_all("TT Room", filters={"plan": plan}, fields=["building", "layouts", "lab_type"], limit_page_length=0):
		if r.building:
			buildings_layouts["buildings"].add(r.building)
		if r.lab_type:
			buildings_layouts["lab_types"].add(r.lab_type)
		buildings_layouts["layouts"].update(split_list(r.layouts or "", upper=True))
	return {
		"programmes": frappe.get_all("TT Programme", filters={"plan": plan}, fields=["program_id", "program_name"], order_by="program_id asc", limit_page_length=0),
		"terms": frappe.get_all("TT Term", filters={"plan": plan}, fields=["term_id", "start_date", "end_date"], order_by="start_date asc", limit_page_length=0),
		"categories": frappe.get_all("TT Category", filters={"plan": plan}, fields=["category_id", "category_name", "choice_type"], order_by="category_id asc", limit_page_length=0),
		"faculty": frappe.get_all("TT Faculty", filters={"plan": plan}, fields=["faculty_id", "faculty_name"], order_by="faculty_name asc", limit_page_length=0),
		"rooms": frappe.get_all("TT Room", filters={"plan": plan}, fields=["room_id", "room_name", "room_type", "capacity", "building", "lab_type"], order_by="room_name asc", limit_page_length=0),
		"cohorts": sorted(cohorts),
		"schools": vals("TT Section", "school"),
		**{k: sorted(v) for k, v in buildings_layouts.items()},
	}


@frappe.whitelist()
def add_time_slot(plan: str, label: str, start_time: str | None = None, end_time: str | None = None, regular: int = 0) -> dict:
	"""Append a time slot to the end of the plan's day (keeps every existing slot in place)."""
	from timetable_app.api.common import week_payload

	check_plan(plan, "write")
	require_manager()
	label = (label or "").strip()
	if not label:
		frappe.throw(_("Give the new slot a name, e.g. Evening 2."))
	doc = frappe.get_doc("TT Plan", plan)
	if label.lower() in {(s.label or "").strip().lower() for s in doc.slots}:
		frappe.throw(_("There is already a slot called '{0}'.").format(label))
	doc.append("slots", {"slot_index": len(doc.slots), "label": label, "start_time": start_time or None,
						 "end_time": end_time or None, "regular": cint(regular)})  # fmt: skip
	doc.save()
	return week_payload(plan)
