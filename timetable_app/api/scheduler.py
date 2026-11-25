"""Readiness checks and timetable generation (background job)."""

from __future__ import annotations

import json
import time
import traceback

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from timetable_app.api.common import (
	build_context,
	check_plan,
	check_version,
	entry_dicts,
	loads,
	lunch_slots,
	plan_rows,
	require_manager,
)
from timetable_app.engine import runner
from timetable_app.engine.checks import check_entries
from timetable_app.engine.preflight import run_preflight
from timetable_app.engine.scenario_builder import ScenarioBuilder
from timetable_app.timetable_generator.utils import plan_week

PROGRESS_EVENT = "tt_progress"
WEIGHT_MAP = {
	"meeting": "w_meeting",
	"faculty_rest": "w_faculty_rest",
	"faculty_free_day": "w_faculty_free_day",
	"session_gap": "w_session_gap",
	"balance": "w_balance",
	"building": "w_building",
	"layout": "w_layout",
}


def _cancel_key(version: str) -> str:
	return f"tt_cancel::{version}"


# --------------------------------------------------------------------------- readiness


def _build(plan: str):
	return ScenarioBuilder(plan_rows(plan), lunch_slots=lunch_slots(plan), week=plan_week(plan)).build()


@frappe.whitelist()
def check_readiness(plan: str) -> dict:
	check_plan(plan, "read")
	t0 = time.time()
	result = _build(plan)
	issues = [i.as_dict() for i in result.issues]
	stats = {}
	if result.scenario is not None:
		try:
			issues += [i.as_dict() for i in run_preflight(result.scenario, result.section_reqs, plan_week(plan))]
		except Exception as e:
			issues.append({"level": "error", "code": "preflight_failed", "message": f"Readiness check failed: {e}", "sheet": "", "ref": ""})
		sc = result.scenario
		cm = {c.id: c for c in sc.courses}
		stats = {
			"sections": len(sc.sections),
			"sessions": sum(len(cm[s.course_id].theory_durations) + len(cm[s.course_id].lab_durations) for s in sc.sections),
			"cohorts": len(sc.cohorts),
			"faculty": len(sc.faculty),
			"rooms": len(sc.locations),
		}
	errors = sum(1 for i in issues if i["level"] == "error")
	warnings = sum(1 for i in issues if i["level"] == "warning")
	payload = {
		"ok": errors == 0,
		"errors": errors,
		"warnings": warnings,
		"issues": issues,
		"stats": stats,
		"checked_on": str(now_datetime()),
		"seconds": round(time.time() - t0, 1),
	}
	if frappe.has_permission("TT Plan", "write", plan):
		values = {"readiness": json.dumps(payload, default=str), "readiness_checked_on": now_datetime()}
		status = frappe.db.get_value("TT Plan", plan, "status")
		if status in ("Setup", "Ready"):
			values["status"] = "Ready" if payload["ok"] else "Setup"
		frappe.db.set_value("TT Plan", plan, values, update_modified=False)
	return payload


# --------------------------------------------------------------------------- generate


@frappe.whitelist()
def generate(plan: str, label: str | None = None, time_limit: int | None = None, hint_from: str | None = None, seed: int | None = None, notes: str | None = None) -> str:
	check_plan(plan, "write")
	require_manager()
	if frappe.db.exists("TT Version", {"plan": plan, "run_status": ("in", ["Queued", "Running"])}):
		frappe.throw(_("A timetable is already being generated for this plan."))
	p = frappe.get_doc("TT Plan", plan)
	if p.status == "Finalised":
		frappe.throw(_("This plan is finalised. Reopen it to generate new versions."))

	result = _build(plan)
	if not result.ok:
		first = "; ".join(i.message for i in result.errors[:3])
		frappe.throw(_("Fix the data problems first ({0} errors): {1}").format(len(result.errors), first))

	minutes = cint(time_limit) or cint(p.time_limit) or 30
	if not 1 <= minutes <= 600:
		frappe.throw(_("Time limit must be 1 to 600 minutes."))
	if hint_from:
		hv = check_version(hint_from)
		if hv.plan != plan:
			frappe.throw(_("The starting version belongs to another plan."))

	weights = {k: cint(p.get(f)) for k, f in WEIGHT_MAP.items()}
	v = frappe.get_doc(
		{
			"doctype": "TT Version",
			"plan": plan,
			"version_label": (label or "").strip() or None,
			"source": "Generated",
			"run_status": "Queued",
			"approval_status": "Draft",
			"time_limit": minutes * 60,
			"seed": cint(seed) or None,
			"hint_from": hint_from or None,
			"weights": json.dumps({**weights, "cross_term_overlap": cint(p.cross_term_overlap), "num_workers": cint(p.num_workers) or 8}),
			"notes": notes,
			"progress": json.dumps({"stage": "queued"}),
		}
	).insert()
	frappe.db.commit()
	job = frappe.enqueue(
		"timetable_app.api.scheduler.run_version",
		queue="long",
		timeout=minutes * 60 + 1800,
		version=v.name,
		job_id=f"tt_generate::{v.name}",
		deduplicate=True,
		enqueue_after_commit=False,
	)
	v.db_set("job_id", getattr(job, "id", "") or "", update_modified=False)
	return v.name


def _progress(version: str, data: dict, commit: bool = True):
	data = {**data, "version": version, "at": time.time()}
	frappe.db.set_value("TT Version", version, "progress", json.dumps(data, default=str), update_modified=False)
	if commit:
		frappe.db.commit()
	frappe.publish_realtime(PROGRESS_EVENT, data, after_commit=False)


def run_version(version: str):
	"""Background job: build the model, solve, store entries."""
	v = frappe.get_doc("TT Version", version)
	if v.run_status != "Queued":
		return
	if frappe.cache.get_value(_cancel_key(version)):
		_finish(v, "Cancelled", error="Cancelled before start.")
		return
	v.db_set({"run_status": "Running", "started_at": now_datetime()}, update_modified=False)
	_progress(version, {"stage": "building", "message": "Reading plan data"})
	try:
		cfg = loads(v.weights, {}) or {}
		result = _build(v.plan)
		if not result.ok:
			raise frappe.ValidationError("; ".join(i.message for i in result.errors[:5]))
		_progress(version, {"stage": "building", "message": "Building the scheduling model"})
		weights = {k: cfg.get(k, 100) for k in WEIGHT_MAP}
		model, build_log = runner.quiet(runner.build_model, result.scenario, weights, bool(cfg.get("cross_term_overlap", 1)), result.section_reqs, plan_week(v.plan))

		hint = loads(frappe.db.get_value("TT Version", v.hint_from, "hint"), None) if v.hint_from else None
		loaded, skipped = runner.apply_hint(model, hint)
		solve_start = time.time()
		_progress(version, {"stage": "solving", "message": "Searching for a timetable", "sessions": len(model.session_vars), "started": solve_start,
							"hint_loaded": loaded, "hint_skipped": skipped, "time_limit": v.time_limit, "elapsed": 0})  # fmt: skip

		cancel_key = _cancel_key(version)

		def on_tick(snap):
			# runs in this (job) thread every few seconds while CP-SAT searches in its own threads
			_progress(version, {"stage": "solving", "message": "Improving the timetable" if snap["solutions"] else "Searching for a timetable",
								"time_limit": v.time_limit, "started": solve_start, "sessions": len(model.session_vars), **snap})  # fmt: skip
			return bool(frappe.cache.get_value(cancel_key))

		res = runner.solve(
			model,
			time_limit=v.time_limit or 1800,
			seed=v.seed,
			num_workers=cint(cfg.get("num_workers")) or 8,
			on_tick=on_tick,
		)
		_ensure_db()  # a long search can outlive an idle database connection
		_progress(version, {"stage": "saving", "message": "Saving the timetable", "solutions": res.solutions_found, "objective": res.objective})
		log = "\n".join(x for x in (build_log[-20000:], res.log[-40000:]) if x)
		if res.entries:
			_save_entries(v, result.scenario, res.entries)
			_store_checks(v.name, v.plan)
		status = "Completed" if res.entries else ("Cancelled" if res.status == "CANCELLED" else "Failed")
		error = None
		if not res.entries:
			error = {
				"INFEASIBLE": "No timetable can satisfy all hard constraints. Review the readiness report.",
				"MODEL_INVALID": "The scheduling model is invalid.",
				"CANCELLED": "Cancelled.",
			}.get(res.status, "No timetable was found within the time limit. Try a longer time limit or start from an earlier version.")
		frappe.db.set_value(
			"TT Version",
			version,
			{
				"solver_status": res.status,
				"objective": res.objective,
				"best_bound": res.best_bound,
				"solutions_found": res.solutions_found,
				"wall_time": res.wall_time,
				"seed": res.seed,
				"violations": json.dumps(res.violations),
				"soft_issues": len(res.violations),
				"stats": json.dumps(res.stats),
				"hint": json.dumps(res.hint) if res.hint else None,
				"log": log,
			},
			update_modified=False,
		)
		_finish(frappe.get_doc("TT Version", version), status, error=error)
	except Exception as e:
		_ensure_db()
		frappe.db.rollback()
		_finish(frappe.get_doc("TT Version", version), "Failed", error=f"{e}\n\n{traceback.format_exc()}"[-20000:])
	finally:
		frappe.cache.delete_value(_cancel_key(version))


def _ensure_db():
	"""Reconnect if the database dropped the connection (e.g. wait_timeout during a long solve)."""
	try:
		frappe.db.sql("select 1")
	except Exception:
		try:
			frappe.db.close()
		except Exception:
			pass
		frappe.db.connect()


def _finish(v, status: str, error: str | None = None):
	v.db_set({"run_status": status, "finished_at": now_datetime(), "error": error}, update_modified=True)
	if status == "Completed" and frappe.db.get_value("TT Plan", v.plan, "status") in ("Setup", "Ready"):
		frappe.db.set_value("TT Plan", v.plan, "status", "Generated", update_modified=False)
	frappe.db.commit()
	_progress(v.name, {"stage": "done", "run_status": status, "message": error or status})


def _save_entries(v, scenario, entries: list[dict]):
	sections = {s.id: s for s in scenario.sections}
	courses = {c.id: c for c in scenario.courses}
	rooms = {r.id: r for r in scenario.locations}
	frappe.db.delete("TT Entry", {"version": v.name})
	fields = ["name", "version", "plan", "session_key", "section_key", "course_code", "course_name", "category", "session_type",
			  "session_index", "day_index", "slot_index", "duration", "room_id", "room_name", "term_id", "is_manual", "faculty_ids",
			  "cohorts", "program_ids", "allowed_starts", "owner", "modified_by", "creation", "modified", "docstatus"]  # fmt: skip
	now, user = now_datetime(), frappe.session.user
	values = []
	for e in entries:
		sec = sections[e["section_key"]]
		course = courses[sec.course_id]
		room = rooms.get(e["room_id"])
		values.append((
			frappe.generate_hash(length=12), v.name, v.plan, e["session_key"], e["section_key"], course.id, course.name,
			sec.category_id, e["session_type"], e["session_index"], e["day_index"], e["slot_index"], e["duration"],
			e["room_id"] or "", room.name if room else "", e["term_id"], 0, ", ".join(sec.faculty_ids),
			", ".join(sec.eligible_cohorts), ", ".join(course.program_ids or []), json.dumps(e.get("allowed_starts") or []),
			user, user, now, now, 0,
		))  # fmt: skip
	frappe.db.bulk_insert("TT Entry", fields, values, chunk_size=500)
	frappe.db.set_value("TT Version", v.name, "entries_count", len(values), update_modified=False)


def _store_checks(version: str, plan: str) -> list[dict]:
	issues = check_entries(entry_dicts(version), build_context(plan))
	frappe.db.set_value("TT Version", version, {"checks": json.dumps(issues), "hard_issues": len(issues)}, update_modified=False)
	return issues


@frappe.whitelist()
def cancel(version: str):
	v = check_version(version, "write")
	require_manager()
	if v.run_status not in ("Queued", "Running"):
		frappe.throw(_("This version is not running."))
	frappe.cache.set_value(_cancel_key(version), 1, expires_in_sec=6 * 3600)
	if v.run_status == "Queued":
		# a queued job that never started (e.g. worker down) can be cancelled immediately
		job_id = frappe.db.get_value("TT Version", version, "job_id")
		try:
			from frappe.utils.background_jobs import get_job

			job = get_job(f"tt_generate::{version}") if not job_id else get_job(job_id)
			if job and job.get_status() in ("queued", "scheduled", "deferred"):
				job.cancel()
				_finish(frappe.get_doc("TT Version", version), "Cancelled", error="Cancelled before start.")
		except Exception:
			pass
	return "ok"


@frappe.whitelist()
def get_progress(version: str) -> dict:
	check_version(version)
	row = frappe.db.get_value("TT Version", version, ["run_status", "progress", "error", "solutions_found", "objective"], as_dict=True)
	return {**row, "progress": loads(row.progress, {})}


@frappe.whitelist()
def rerun_checks(version: str) -> list[dict]:
	v = check_version(version)
	return _store_checks(version, v.plan)


def mark_stale_runs():
	"""Scheduler: a version stuck in Running after its time limit + 1h is marked Failed (worker died)."""
	rows = frappe.get_all("TT Version", filters={"run_status": ("in", ["Queued", "Running"])}, fields=["name", "started_at", "time_limit", "creation"])
	now = now_datetime()
	for r in rows:
		started = r.started_at or r.creation
		if (now - started).total_seconds() > (r.time_limit or 1800) + 3600:
			_finish(frappe.get_doc("TT Version", r.name), "Failed", error="The generation job stopped unexpectedly (worker restarted?).")

