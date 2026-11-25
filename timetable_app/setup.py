"""Install / migrate hooks."""

import frappe

ROLES = {
	"Timetable Manager": "Programme office: maintains data, generates and adjusts timetables.",
	"Timetable Approver": "Reviews and approves submitted timetable versions.",
	"Timetable Viewer": "Read-only access to plans and timetables.",
}


def ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def after_install():
	ensure_roles()
	# the installing administrator can use the app straight away
	if frappe.db.exists("User", "Administrator"):
		frappe.get_doc("User", "Administrator").add_roles("Timetable Manager", "Timetable Approver")


def after_migrate():
	ensure_roles()
