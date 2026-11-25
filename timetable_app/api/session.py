"""Session / boot info and plan overview for the SPA."""

from __future__ import annotations

import frappe

from timetable_app.api.common import check_plan, is_manager, loads, week_payload
from timetable_app.api.review import _hhmm

APP_ROLES = {"Timetable Manager", "Timetable Approver", "Timetable Viewer", "System Manager"}


def has_app_permission() -> bool:
	return frappe.session.user != "Guest" and bool(set(frappe.get_roles()) & APP_ROLES)


@frappe.whitelist()
def get_session() -> dict:
	roles = set(frappe.get_roles())
	user = frappe.session.user
	return {
		"user": user,
		"full_name": frappe.utils.get_fullname(user),
		"user_image": frappe.db.get_value("User", user, "user_image"),
		"roles": sorted(roles & APP_ROLES),
		"is_manager": is_manager(),
		"is_approver": bool(roles & {"Timetable Approver", "System Manager"}),
		"has_access": has_app_permission(),
	}


@frappe.whitelist()
def list_plans() -> list[dict]:
	plans = frappe.get_list(
		"TT Plan",
		fields=["name", "plan_name", "campus", "academic_year", "start_date", "end_date", "status", "active_version", "modified"],
		order_by="modified desc",
		limit_page_length=0,
	)
	for p in plans:
		p["sections"] = frappe.db.count("TT Section", {"plan": p.name})
		p["faculty"] = frappe.db.count("TT Faculty", {"plan": p.name})
		p["rooms"] = frappe.db.count("TT Room", {"plan": p.name})
		p["versions"] = frappe.db.count("TT Version", {"plan": p.name})
		p["completed"] = frappe.db.count("TT Version", {"plan": p.name, "run_status": "Completed"})
		p["running"] = bool(frappe.db.exists("TT Version", {"plan": p.name, "run_status": ("in", ["Queued", "Running"])}))
		ready = loads(frappe.db.get_value("TT Plan", p.name, "readiness"), None)
		# progress through the 8-step workflow, for the plan card
		p["progress"] = sum([
			bool(p.start_date and p.end_date),
			p["sections"] > 0 and p["rooms"] > 0 and p["faculty"] > 0,
			bool(ready and ready.get("ok")),
			bool(ready and ready.get("ok")),
			p["completed"] > 0,
			bool(frappe.db.exists("TT Version", {"plan": p.name, "approval_status": ("in", ["Submitted", "Approved"])})),
			bool(p.active_version),
			bool(p.active_version),
		])  # fmt: skip
	return plans


@frappe.whitelist()
def get_overview(plan: str) -> dict:
	check_plan(plan)
	doc = frappe.get_doc("TT Plan", plan)
	counts = {
		dt: frappe.db.count(dt, {"plan": plan})
		for dt in ("TT Programme", "TT Term", "TT Category", "TT Room", "TT Faculty", "TT Meeting", "TT Section")
	}
	versions = frappe.get_all(
		"TT Version",
		filters={"plan": plan},
		fields=["name", "version_label", "run_status", "approval_status", "objective", "hard_issues", "soft_issues", "entries_count", "creation", "source"],
		order_by="creation desc",
		limit=5,
	)
	readiness = loads(doc.readiness, None)
	running = next((v.name for v in versions if v.run_status in ("Queued", "Running")), None)
	has_data = counts["TT Section"] > 0 and counts["TT Room"] > 0 and counts["TT Faculty"] > 0
	steps = [
		{"key": "setup", "label": "Setup", "route": "PlanSetup", "done": bool(doc.start_date and doc.end_date and counts["TT Term"])},
		{"key": "data", "label": "Data", "route": "Sections", "done": has_data},
		{"key": "validate", "label": "Validation", "route": "Generate", "done": bool(readiness and readiness.get("ok"))},
		{"key": "rules", "label": "Rules", "route": "Rules", "done": bool(readiness and readiness.get("ok"))},
		{"key": "generate", "label": "Generate", "route": "Generate", "done": any(v.run_status == "Completed" for v in versions)},
		{"key": "review", "label": "Review", "route": "Versions", "done": any(v.approval_status in ("Submitted", "Approved") for v in versions)},
		{"key": "finalise", "label": "Finalise", "route": "Versions", "done": bool(doc.active_version)},
		{"key": "outputs", "label": "Outputs", "route": "Reports", "done": bool(doc.active_version)},
	]
	current = next((s for s in steps if not s["done"]), None)
	if current:
		current["current"] = True
	return {
		"plan": {k: doc.get(k) for k in ("name", "plan_name", "campus", "academic_year", "start_date", "end_date", "status", "active_version", "time_limit")},
		"slots": [{"slot_index": s.slot_index, "label": s.label, "start_time": _hhmm(s.start_time), "end_time": _hhmm(s.end_time), "regular": s.regular} for s in doc.slots],
		"week": week_payload(plan),
		"counts": counts,
		"versions": versions,
		"readiness": {**{k: readiness.get(k) for k in ("ok", "errors", "warnings", "checked_on", "stats")}, "top": _top_issues(readiness)} if readiness else None,
		"running": running,
		"steps": steps,
		"is_manager": is_manager(),
	}


def _top_issues(readiness: dict, n: int = 6) -> list[dict]:
	groups: dict[tuple, dict] = {}
	for i in readiness.get("issues") or []:
		key = (i.get("level"), i.get("code"))
		g = groups.setdefault(key, {"level": i.get("level"), "code": i.get("code"), "count": 0, "sample": i.get("message")})
		g["count"] += 1
	return sorted(groups.values(), key=lambda g: (g["level"] != "error", -g["count"]))[:n]
