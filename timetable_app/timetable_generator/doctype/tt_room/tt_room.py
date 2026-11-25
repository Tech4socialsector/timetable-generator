# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from timetable_app.timetable_generator.utils import (
	assert_plan_editable,
	clean,
	ensure_unique,
	normalise_list,
	validate_availability,
)


class TTRoom(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "room_id", "room_name", "building", "lab_type")
		self.room_name = self.room_name or self.room_id
		self.building = (self.building or "").upper()
		self.lab_type = (self.lab_type or "").upper()
		normalise_list(self, "layouts", upper=True)
		if self.room_type in ("CLASSROOM", "EITHER") and not (self.capacity or 0) > 0:
			frappe.throw(_("Classrooms need a capacity."))
		if self.room_type in ("LAB", "EITHER") and not self.lab_type:
			frappe.throw(_("Labs need a lab type."))
		validate_availability(self)
		ensure_unique(self, "room_id", "Room")
