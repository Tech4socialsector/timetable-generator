import frappe

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + frappe.utils.quote(frappe.request.path)
		raise frappe.Redirect
	from timetable_app.api.session import get_session

	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	# frappe-ui's jinjaBootData copies every key of `boot` onto `window`
	context.boot = {
		"csrf_token": csrf_token,
		"site_name": frappe.local.site,
		"socketio_port": frappe.conf.socketio_port,
		"tt_session": get_session(),
	}
	return context
