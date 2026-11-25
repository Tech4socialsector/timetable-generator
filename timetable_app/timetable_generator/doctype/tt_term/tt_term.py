# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from timetable_app.timetable_generator.utils import assert_plan_editable, clean, ensure_unique


class TTTerm(Document):
	def validate(self):
		assert_plan_editable(self)
		clean(self, "term_id")
		self.term_id = (self.term_id or "").upper()
		if self.term_id == "FULL":
			frappe.throw(_("FULL is reserved for the whole semester; choose another term ID."))
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("The term ends before it starts."))
		ensure_unique(self, "term_id", "Term")
