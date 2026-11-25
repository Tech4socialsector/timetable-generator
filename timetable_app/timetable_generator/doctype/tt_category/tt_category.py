# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from timetable_app.timetable_generator.utils import assert_plan_editable, clean, day_hi, ensure_unique, validate_int_list


class TTCategory(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "category_id", "category_name")
		self.category_name = self.category_name or self.category_id
		self.choice_count = max(0, self.choice_count or 0)
		validate_int_list(self, "allowed_slots", "Allowed start slots")
		validate_int_list(self, "allowed_days", "Allowed days", 0, day_hi(self))
		validate_int_list(self, "preferred_slots", "Preferred slots")
		ensure_unique(self, "category_id", "Category")
