"""Configurable week structure (no Frappe needed):
    ../../env/bin/python -m unittest timetable_app.tests.test_week
"""

import unittest
from datetime import date

from timetable_app.engine import runner
from timetable_app.engine.checks import Context, check_entries
from timetable_app.engine.plan_solver import PlanSolver
from timetable_app.engine.preflight import run_preflight
from timetable_app.engine.scenario_builder import ScenarioBuilder
from timetable_app.engine.week import DEFAULT_WEEK, Week, week_from
from timetable_app.tests.test_engine import rows

UPSTREAM_REGULAR_STARTS = [1, 2, 3, 4, 7, 8, 9, 10, 13, 14, 15, 16, 19, 20, 21, 22, 25, 26, 27, 28]  # src/solver.py

EIGHT = Week(("Mon", "Tue", "Wed", "Thu", "Fri"), 8, frozenset({"Mon", "Tue", "Wed", "Thu", "Fri"}), frozenset(range(1, 7)))


def week_rows(week: Week):
	r = rows()
	for sheet in ("Rooms", "Faculty"):
		for row in r[sheet]:
			for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
				row[d] = "ALL" if d in week.days else "NONE"
	return r


class TestWeekModel(unittest.TestCase):
	def test_default_matches_original_engine(self):
		self.assertEqual(DEFAULT_WEEK.regular_starts, UPSTREAM_REGULAR_STARTS)
		self.assertEqual(DEFAULT_WEEK.total, 36)

	def test_week_from_strings(self):
		w = week_from("Mon,Tue,Wed,Thu,Fri", 8, "Mon,Tue", "1,2,3")
		self.assertEqual(w.days, ("Mon", "Tue", "Wed", "Thu", "Fri"))
		self.assertEqual(w.regular_starts, [1, 2, 3, 9, 10, 11])
		self.assertEqual(w.label(9), "Tue slot 1")

	def test_invalid_weeks(self):
		with self.assertRaises(ValueError):
			Week((), 6)
		with self.assertRaises(ValueError):
			Week(("Mon", "Mon"), 6)
		with self.assertRaises(ValueError):
			Week(("Mon",), 13)


class TestDefaultWeekUsesUpstream(unittest.TestCase):
	def test_identical_allowed_starts(self):
		from src.solver import TimetableSolver

		sc = ScenarioBuilder(rows()).build().scenario
		ours, theirs = PlanSolver(sc), TimetableSolver(sc)
		for sec in sc.sections:
			self.assertEqual(ours.get_allowed_start_indices(sec, 1), theirs.get_allowed_start_indices(sec, 1))
			self.assertEqual(ours.get_allowed_start_indices(sec, 2), theirs.get_allowed_start_indices(sec, 2))

	def test_mismatched_week_is_rejected(self):
		sc = ScenarioBuilder(rows()).build().scenario
		with self.assertRaises(ValueError):
			PlanSolver(sc, week=EIGHT)


class TestCustomWeek(unittest.TestCase):
	def build(self, r=None):
		return ScenarioBuilder(r or week_rows(EIGHT), week=EIGHT).build()

	def test_builder_uses_week(self):
		res = self.build()
		self.assertTrue(res.ok, [i.message for i in res.issues])
		self.assertEqual((res.scenario.config.days_per_week, res.scenario.config.slots_per_day), (5, 8))
		fac = res.scenario.faculty[0]
		self.assertEqual(len(fac.available_slots), 40)  # ALL = 8 slots x 5 days

	def test_allowed_starts_follow_week(self):
		res = self.build()
		s = PlanSolver(res.scenario, week=EIGHT)
		starts = s.get_allowed_start_indices(res.scenario.sections[0], 1)
		self.assertEqual(starts, EIGHT.regular_starts)
		two = s.get_allowed_start_indices(res.scenario.sections[0], 2)
		self.assertTrue(all(x % 8 + 1 <= 6 for x in two))  # a double session stays inside regular slots of one day

	def test_solve_and_check(self):
		res = self.build()
		self.assertEqual([i for i in run_preflight(res.scenario, res.section_reqs, EIGHT) if i.level == "error"], [])
		model, _ = runner.quiet(runner.build_model, res.scenario, None, True, res.section_reqs, EIGHT)
		out = runner.solve(model, time_limit=20, num_workers=2)
		self.assertIn(out.status, ("OPTIMAL", "FEASIBLE"))
		self.assertTrue(all(e["slot_index"] < 8 and e["day_index"] < 5 for e in out.entries))
		ctx = Context(week=EIGHT, terms={"MA_T1": (date(2027, 1, 18), date(2027, 5, 7)), "UG_T1": (date(2027, 1, 18), date(2027, 5, 8))},
					  choice_types={"core": "NONE"},
					  rooms={"R1": {"name": "Room 1", "type": "CLASSROOM", "capacity": 40, "lab_type": "", "slots": set(range(40))}},
					  faculty_slots={"a@x.edu": set(range(40)), "b@x.edu": set(range(40))},
					  sections={"MA101__Section_1": {"capacity": 30}, "UG101__Section_1": {"capacity": 30}})  # fmt: skip
		ents = []
		for i, e in enumerate(out.entries):
			sec = next(x for x in res.scenario.sections if x.id == e["section_key"])
			ents.append({**e, "name": str(i), "course_code": sec.course_id, "category": sec.category_id, "faculty_ids": sec.faculty_ids, "cohorts": sec.eligible_cohorts})
		self.assertEqual(check_entries(ents, ctx), [])

	def test_out_of_range_values_are_errors(self):
		r = week_rows(EIGHT)
		r["Faculty"][0]["Mon"] = "1,9"  # slot 9 does not exist in an 8-slot day
		self.assertIn("bad_faculty", [i.code for i in self.build(r).errors])
		r = week_rows(EIGHT)
		r["Sections"][0]["allowed_slots"] = "41"
		self.assertIn("bad_slots", [i.code for i in self.build(r).errors])
		r = week_rows(EIGHT)
		r["Meeting Slots"] = [{"program_id": "MA", "term_id": "MA_T1", "meeting_slots": "40", "attendee_type": "BOTH"}]
		self.assertIn("bad_meeting_slots", [i.code for i in self.build(r).errors])


if __name__ == "__main__":
	unittest.main()
