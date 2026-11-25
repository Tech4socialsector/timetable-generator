"""Readiness checks run before solving.

Ports the upstream ``run_preflight_audit`` (which printed and called sys.exit)
to structured issues, and adds the checks that otherwise surface only as an
opaque INFEASIBLE / ValueError from the solver.
"""

from __future__ import annotations

from collections import defaultdict

from .domain import TimetableScenario
from .scenario_builder import VIRTUAL_TYPES, Issue
from .week import DEFAULT_WEEK, Week
from .plan_solver import PlanSolver


def run_preflight(scenario: TimetableScenario, section_reqs: dict | None = None, week: Week | None = None) -> list[Issue]:
	issues: list[Issue] = []
	week = week or DEFAULT_WEEK
	slot_label = week.label
	spd = week.slots_per_day
	s = PlanSolver(scenario, section_reqs, week)  # only used for its helper methods; no variables are created
	cat_map = {c.id.lower(): c for c in scenario.course_categories}
	course_map = {c.id: c for c in scenario.courses}

	fac_need: dict[str, int] = defaultdict(int)
	fac_union: dict[str, set[int]] = defaultdict(set)
	cohort_need: dict[str, int] = defaultdict(int)

	for sec in scenario.sections:
		course = course_map[sec.course_id]
		cat = cat_map.get(sec.category_id.lower())
		virtual = cat is not None and cat.choice_type in VIRTUAL_TYPES
		n_sessions = len(course.theory_durations) + len(course.lab_durations)
		days_available: set[int] = set()

		for s_type, durations in (("THEORY", course.theory_durations), ("LAB", course.lab_durations)):
			if not virtual and durations and not s.feasible_locations_for(sec, course, s_type):
				req = (section_reqs or {}).get(sec.id) or {}
				if s_type == "LAB":
					msg = f"{sec.id}: no lab of type '{req.get('lab_type') or course.required_lab_type}' exists."
				else:
					msg = f"{sec.id}: no classroom holds {req.get('capacity') or course.required_classroom_size} students."
				issues.append(Issue("error", "no_room", msg, "Sections", sec.id))
			for i, dur in enumerate(durations):
				suffix = f"{sec.id}_{s_type}_{i}"
				starts = s.get_allowed_start_indices(sec, dur)
				if not starts:
					issues.append(Issue("error", "zero_starts",
						f"{suffix} has no valid start slot. Check faculty availability and allowed slots.", "Sections", sec.id))  # fmt: skip
					continue
				if len(starts) <= 2:
					issues.append(Issue("warning", "low_options",
						f"{suffix} can start in only {len(starts)} slot(s): {', '.join(slot_label(x) for x in starts)}.", "Sections", sec.id))  # fmt: skip
				days_available |= {x // spd for x in starts}
				if cat is None or cat.choice_type != "VIRTUAL_OPEN":
					for fid in sec.faculty_ids:
						fac_need[(fid, sec.term_id)] += dur
						for st in starts:
							fac_union[(fid, sec.term_id)].update(range(st, st + dur))
				for c in sec.eligible_cohorts:
					if c != "ALL" and (cat is None or cat.choice_type in ("NONE",)):
						cohort_need[(c, sec.term_id)] += dur

		if n_sessions and days_available and len(days_available) < n_sessions:
			issues.append(Issue("error", "day_conflict",
				f"{sec.id} needs {n_sessions} different days but can be placed on only {len(days_available)}.", "Sections", sec.id))  # fmt: skip

		if not virtual and course.theory_durations and not ((section_reqs or {}).get(sec.id, {}).get("capacity") or course.required_classroom_size):
			issues.append(Issue("warning", "no_capacity", f"{sec.id} has no required room capacity; any classroom may be used.", "Sections", sec.id))

	for (fid, term), need in fac_need.items():
		have = len(fac_union[(fid, term)])
		if need > have:
			issues.append(Issue("error", "faculty_conflict",
				f"{fid} needs {need} slots in term {term} but has only {have} usable openings.", "Faculty", fid))  # fmt: skip

	regular = len(week.regular_starts)  # slots usable when nothing else is allowed
	for (cohort, term), need in cohort_need.items():
		if need > regular:
			issues.append(Issue("warning", "cohort_load",
				f"Cohort {cohort} has {need} core-session slots in term {term}, more than the {regular} regular slots.", "Sections", cohort))  # fmt: skip
	return issues
