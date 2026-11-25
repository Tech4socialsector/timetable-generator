# Copyright (c) 2026, Azim Premji Foundation - TFSS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TTEntry(Document):
	"""A scheduled session. Created by the solver/importer; moved via timetable_app.api.review."""
