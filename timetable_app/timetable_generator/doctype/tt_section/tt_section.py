# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from timetable_app.engine.scenario_builder import section_key
from timetable_app.timetable_generator.utils import (
	assert_plan_editable,
	clean,
	day_hi,
	normalise_list,
	validate_duration_list,
	validate_int_list,
)


class TTSection(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "course_code", "course_name", "category", "term_id", "required_lab_type")
		self.section_number = self.section_number or 1
		if self.section_number < 1:
			frappe.throw(_("Section number must be 1 or more."))
		self.section_key = section_key(self.course_code, self.section_number)
		self.term_id = (self.term_id or "FULL").upper()
		self.required_lab_type = (self.required_lab_type or "").upper()
		normalise_list(self, "faculty_ids", lower=True)
		normalise_list(self, "required_cohorts", upper=True)
		normalise_list(self, "optional_cohorts", upper=True)
		normalise_list(self, "program_ids", upper=True)
		for f in ("preferred_theory_buildings", "preferred_lab_buildings", "preferred_theory_layouts", "preferred_lab_layouts"):
			normalise_list(self, f, upper=True)
		validate_duration_list(self, "theory_durations", "Theory sessions")
		validate_duration_list(self, "lab_durations", "Lab sessions")
		if not self.theory_durations and not self.lab_durations:
			frappe.throw(_("Add theory or lab sessions."))
		if self.lab_durations and not self.required_lab_type:
			frappe.throw(_("Lab sessions need a lab type."))
		validate_int_list(self, "allowed_slots", "Allowed start slots")
		validate_int_list(self, "allowed_days", "Allowed days", 0, day_hi(self))
		validate_int_list(self, "preferred_slot", "Preferred slots")
		if not self.flags.skip_unique and frappe.db.exists(
			"TT Section", {"plan": self.plan, "section_key": self.section_key, "name": ("!=", self.name)}
		):
			frappe.throw(_("Section {0} of {1} already exists.").format(self.section_number, self.course_code), frappe.DuplicateEntryError)

	def on_update(self):
		create_missing_faculty(self)


def name_from_email(faculty_id: str) -> str:
	"""juhi.tyagi@apu.edu.in -> Juhi Tyagi"""
	local = faculty_id.split("@", 1)[0]
	words = [w for w in local.replace("_", ".").replace("-", ".").split(".") if w]
	return " ".join(w[:1].upper() + w[1:] for w in words) or faculty_id


def create_missing_faculty(section) -> list[str]:
	"""Faculty named on a section but missing from the plan are added with every slot free."""
	from timetable_app.engine.scenario_builder import split_list
	from timetable_app.timetable_generator.utils import DAY_FIELDS, plan_week

	ids = [f.lower() for f in split_list(section.faculty_ids or "")]
	if not ids:
		return []
	existing = set(frappe.get_all("TT Faculty", filters={"plan": section.plan, "faculty_id": ("in", ids)}, pluck="faculty_id"))
	teaching = {d.lower() for d in plan_week(section.plan).days}
	created = []
	for fid in ids:
		if fid in existing:
			continue
		doc = frappe.get_doc({
			"doctype": "TT Faculty",
			"plan": section.plan,
			"faculty_id": fid,
			"faculty_name": name_from_email(fid),
			"program_ids": section.program_ids,
			"remarks": _("Added automatically from course {0}; all slots free until edited.").format(section.course_code),
			**{d: ("ALL" if d in teaching else "NONE") for d in DAY_FIELDS},
		})  # fmt: skip
		doc.flags.ignore_plan_lock = section.flags.ignore_plan_lock
		doc.insert(ignore_permissions=True)
		created.append(fid)
	if created:
		frappe.local.tt_auto_faculty = [*(getattr(frappe.local, "tt_auto_faculty", None) or []), *created]
	return created
