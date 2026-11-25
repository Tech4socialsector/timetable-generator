# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from timetable_app.timetable_generator.utils import assert_plan_editable, clean, ensure_unique


class TTProgramme(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "program_id", "program_name", "school")
		self.program_id = (self.program_id or "").upper()
		self.program_name = self.program_name or self.program_id
		ensure_unique(self, "program_id", "Programme")
