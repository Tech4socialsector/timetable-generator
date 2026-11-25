# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from timetable_app.timetable_generator.utils import assert_plan_editable, clean, validate_int_list


class TTMeeting(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "program_id", "term_id")
		self.program_id = (self.program_id or "").upper()
		self.term_id = (self.term_id or "FULL").upper()
		validate_int_list(self, "meeting_slots", "Meeting slots")
		if not self.meeting_slots:
			frappe.throw(_("Pick at least one meeting slot."))
