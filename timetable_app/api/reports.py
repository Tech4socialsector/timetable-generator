"""Excel outputs for a timetable version (the outputs listed in the working note)."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _

from timetable_app.api.common import build_context, check_version, entry_dicts, loads, plan_rows
from timetable_app.engine.checks import free_slots, occupied
from timetable_app.api.data_io import plan_sheet_columns
from timetable_app.engine.workbook import write_workbook

REPORTS = {
	"full": "Complete workbook (all reports)",
	"timetable": "Overall timetable (course-wise)",
	"cohort": "Cohort-wise timetable",
	"faculty": "Faculty timetable",
	"room": "Room-wise timetable",
	"skeleton": "Skeleton (categories per slot)",
	"complete": "Complete-category availability",
	"utilisation": "Room utilisation by slot",
	"free_cohort": "Free slots per cohort",
	"free_faculty": "Free slots per faculty",
	"with_inputs": "Input workbook with timetable (old format)",
}


def _slot_labels(plan: str) -> list[str]:
	slots = frappe.get_all("TT Plan Slot", filters={"parent": plan, "parenttype": "TT Plan"}, fields=["slot_index", "label", "start_time", "end_time"], order_by="slot_index asc")
	out = []
	for s in slots:
		t = f" ({str(s.start_time)[:5]}-{str(s.end_time)[:5]})" if s.start_time and s.end_time else ""
		out.append(f"{s.label}{t}")
	return out


def _rows_list(entries, labels, faculty_names, days):
	header = ["Day", "Slot", "Time", "Course code", "Course name", "Section", "Type", "Category", "Faculty", "Room", "Cohorts",
			  "Programmes", "Term", "Slots", "Moved by hand"]  # fmt: skip
	rows = []
	for e in sorted(entries, key=lambda x: (x["day_index"], x["slot_index"], x["course_code"])):
		rows.append([
			days[e["day_index"]] if e["day_index"] < len(days) else e["day_index"], e["slot_index"], labels[e["slot_index"]] if e["slot_index"] < len(labels) else "",
			e["course_code"], e["course_name"], e["section_key"].rsplit("_", 1)[-1], e["session_type"].title(), e["category"],
			", ".join(faculty_names.get(f, f) for f in e["faculty_ids"]), e["room_name"] or ("Virtual" if not e["room_id"] else e["room_id"]),
			", ".join(e["cohorts"]), ", ".join(e["program_ids"]), e["term_id"], e["duration"], "Yes" if e["is_manual"] else "",
		])  # fmt: skip
	return header, rows


def _grid(entries, labels, cell, week):
	grid = defaultdict(list)
	spd = week.slots_per_day
	for e in entries:
		for sl in occupied(e, spd):
			grid[sl].append(cell(e))
	header = ["Day", *labels]
	rows = [[name, *["\n".join(sorted(set(grid[d * spd + s]))) for s in range(spd)]] for d, name in enumerate(week.days)]
	return header, rows


def _by(entries, key_fn, labels, faculty_names, key_label, days):
	groups = defaultdict(list)
	for e in entries:
		for k in key_fn(e):
			groups[k].append(e)
	header, _ = _rows_list([], labels, faculty_names, days)
	rows = []
	for k in sorted(groups):
		_, r = _rows_list(groups[k], labels, faculty_names, days)
		rows += [[k, *x] for x in r]
	return [key_label, *header], rows


def build_report(version: str, report: str) -> tuple[str, bytes]:
	v = check_version(version)
	if report not in REPORTS:
		frappe.throw(_("Unknown report {0}.").format(report))
	doc = frappe.get_doc("TT Version", version)
	entries = entry_dicts(version)
	labels = _slot_labels(v.plan)
	faculty_names = {f.faculty_id: f.faculty_name for f in frappe.get_all("TT Faculty", filters={"plan": v.plan}, fields=["faculty_id", "faculty_name"], limit_page_length=0)}
	ctx = build_context(v.plan)
	week, days, spd = ctx.week, list(ctx.week.days), ctx.week.slots_per_day
	labels = (labels + [f"Slot {i}" for i in range(len(labels), spd)])[:spd]
	sheets: dict[str, tuple[list, list]] = {}

	def want(*names):
		return report in names or report == "full"

	if want("timetable", "with_inputs"):
		sheets["Timetable"] = _rows_list(entries, labels, faculty_names, days)
	if want("skeleton"):
		sheets["Skeleton"] = _grid(entries, labels, lambda e: e["category"], week)
	if want("cohort"):
		sheets["By cohort"] = _by(entries, lambda e: e["cohorts"], labels, faculty_names, "Cohort", days)
	if want("faculty"):
		sheets["By faculty"] = _by(entries, lambda e: [faculty_names.get(f, f) for f in e["faculty_ids"]], labels, faculty_names, "Faculty", days)
	if want("room"):
		sheets["By room"] = _by(entries, lambda e: [e["room_name"]] if e["room_name"] else [], labels, faculty_names, "Room", days)
	if want("utilisation"):
		used = defaultdict(set)
		for e in entries:
			if e["room_id"]:
				for sl in occupied(e, spd):
					used[sl].add(e["room_id"])
		total = len(ctx.rooms) or 1
		header = ["Day", *labels]
		rows = [[name, *[f"{len(used[d * spd + s])} / {total} ({round(100 * len(used[d * spd + s]) / total)}%)" for s in range(spd)]] for d, name in enumerate(days)]
		sheets["Room utilisation"] = (header, rows)
	if want("complete"):
		rows = []
		for e in entries:
			if ctx.choice(e["category"]) != "COMPLETE":
				continue
			others = [o for o in entries if o["name"] != e["name"]]
			free = [c for c in e["cohorts"] if set(occupied(e, spd)) <= set(free_slots(others, ctx, "cohort", c, e["term_id"]))]
			rows.append([e["course_code"], e["course_name"], e["category"], days[e["day_index"]], labels[e["slot_index"]],
						 ", ".join(e["cohorts"]), ", ".join(free), ", ".join(sorted(set(e["cohorts"]) - set(free)))])  # fmt: skip
		sheets["Complete category"] = (["Course code", "Course name", "Category", "Day", "Slot", "Eligible cohorts", "Free to attend", "Busy"], rows)
	if want("free_cohort"):
		cohorts = sorted({c for e in entries for c in e["cohorts"] if c != "ALL"})
		sheets["Free slots - cohorts"] = _free_sheet(entries, ctx, "cohort", cohorts, labels, {})
	if want("free_faculty"):
		fac = sorted({f for e in entries for f in e["faculty_ids"]})
		sheets["Free slots - faculty"] = _free_sheet(entries, ctx, "faculty", fac, labels, faculty_names)
	if report == "full":
		viol = loads(doc.violations, []) or []
		checks = loads(doc.checks, []) or []
		sheets["Checks"] = (["Kind", "Rule", "Message"], [["Hard", c["rule"], c["message"]] for c in checks] + [["Soft", x["rule"], x["message"]] for x in viol])
	if report == "with_inputs":
		rows = plan_rows(v.plan)
		inputs = {name: (cols, [[r.get(c) for c in cols] for r in rows.get(name, [])]) for name, cols in plan_sheet_columns(v.plan).items()}
		sheets = {**inputs, **sheets, "Skeleton_FULL": _grid(entries, labels, lambda e: e["category"], week)}

	name = f"{frappe.scrub(v.plan)}_{frappe.scrub(doc.version_label or version)}_{report}.xlsx"
	return name, write_workbook(sheets)


def _free_sheet(entries, ctx, kind, keys, labels, names):
	w = ctx.week
	header = [kind.title(), *[f"{d} {labels[s].split(' (')[0]}" for d in w.days for s in range(w.slots_per_day)], "Free slots"]
	rows = []
	for k in keys:
		free = set(free_slots(entries, ctx, kind, k))
		rows.append([names.get(k, k), *["free" if i in free else "" for i in range(w.total)], len(free)])
	return header, rows


@frappe.whitelist()
def download(version: str, report: str = "full"):
	name, content = build_report(version, report)
	frappe.local.response.filename = name
	frappe.local.response.filecontent = content
	frappe.local.response.type = "binary"


@frappe.whitelist()
def list_reports() -> dict:
	return REPORTS
