# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TTVersion(Document):
	def validate(self):
		if not self.version_label:
			n = frappe.db.count("TT Version", {"plan": self.plan}) + (0 if not self.is_new() else 1)
			self.version_label = f"Version {n}"

	def on_trash(self):
		if self.run_status in ("Queued", "Running"):
			frappe.throw(_("Cancel the run before deleting this version."))
		if self.approval_status == "Approved":
			frappe.throw(_("An approved version cannot be deleted."))
		frappe.db.delete("TT Entry", {"version": self.name})
		frappe.db.set_value("TT Version", {"hint_from": self.name}, "hint_from", None, update_modified=False)
