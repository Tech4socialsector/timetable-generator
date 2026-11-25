# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from timetable_app.timetable_generator.utils import (
	assert_plan_editable,
	clean,
	ensure_unique,
	normalise_list,
	validate_availability,
)


class TTFaculty(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "faculty_id", "faculty_name")
		self.faculty_id = (self.faculty_id or "").lower()
		self.faculty_name = self.faculty_name or self.faculty_id
		normalise_list(self, "program_ids", upper=True)
		validate_availability(self)
		ensure_unique(self, "faculty_id", "Faculty")
