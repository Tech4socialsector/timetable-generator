"""Engine tests (no Frappe needed): python -m unittest timetable_app.tests.test_engine"""

import unittest
from datetime import date

from timetable_app.engine import runner
from timetable_app.engine.checks import Context, check_entries, free_slots
from timetable_app.engine.preflight import run_preflight
from timetable_app.engine.scenario_builder import ScenarioBuilder, parse_availability, section_key


def rows(**over):
	base = {
		"Programs": [{"program_id": "MA", "program_name": "MA"}, {"program_id": "UG", "program_name": "UG"}],
		"Terms": [
			{"term_id": "MA_T1", "start_date": date(2027, 1, 18), "end_date": date(2027, 5, 7)},
			{"term_id": "UG_T1", "start_date": date(2027, 1, 18), "end_date": date(2027, 5, 8)},
		],
		"Categories": [{"Name": "Core", "ID": "CORE", "choice_type": "None", "choice_count": None}],
		"Rooms": [{"id": "R1", "name": "Room 1", "type": "CLASSROOM", "classroom_capacity": 40, "building": "A",
				   **{d: "ALL" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")}}],  # fmt: skip
		"Faculty": [
			{"id": "a@x.edu", "name": "A", **{d: "ALL" for d in ("Mon", "Tue", "Wed", "Thu", "Fri")}, "Sat": "NONE"},
			{"id": "b@x.edu", "name": "B", **{d: "ALL" for d in ("Mon", "Tue", "Wed", "Thu", "Fri")}, "Sat": "NONE"},
		],
		"Meeting Slots": [],
		"Sections": [
			{"SI no": "1_PG", "course_code": "MA101", "section_number": 1, "course_name": "MA course", "category": "CORE", "faculty_id": "a@x.edu",
			 "theory_durations": "1,1", "required_room_capacity": 30, "required_cohorts": "MA26", "program_ids": "MA", "term_id": "MA_T1"},
			{"course_code": "UG101", "section_number": 1, "course_name": "UG course", "category": "CORE", "faculty_id": "b@x.edu",
			 "theory_durations": "1,1", "required_room_capacity": 30, "required_cohorts": "UG26", "program_ids": "UG", "term_id": "UG_T1"},
		],
	}  # fmt: skip
	base.update(over)
	return base


class TestBuilder(unittest.TestCase):
	def test_builds(self):
		r = ScenarioBuilder(rows()).build()
		self.assertTrue(r.ok, [i.message for i in r.issues])
		self.assertEqual(len(r.scenario.sections), 2)
		self.assertEqual(r.scenario.get_term_by_id("MA_T1").term_id, "MA_T1")

	def test_availability(self):
		self.assertEqual(parse_availability("ALL"), [0, 1, 2, 3, 4, 5])
		self.assertEqual(parse_availability("NONE"), [])
		self.assertEqual(parse_availability("1, 2,4"), [1, 2, 4])
		self.assertEqual(parse_availability(""), [])

	def test_section_key(self):
		self.assertEqual(section_key("ABC", "2.0"), "ABC__Section_2")

	def test_unknown_faculty_is_an_error(self):
		r = rows()
		r["Sections"][0]["faculty_id"] = "nobody@x.edu"
		res = ScenarioBuilder(r).build()
		self.assertFalse(res.ok)
		self.assertIn("unknown_faculty", [i.code for i in res.errors])

	def test_meeting_slot_term_case_insensitive(self):
		r = rows(**{"Meeting Slots": [{"program_id": "ma", "term_id": "ma_t1", "meeting_slots": "14,15", "attendee_type": "student_only"}]})
		res = ScenarioBuilder(r).build()
		self.assertTrue(res.ok, [i.message for i in res.issues])
		self.assertEqual(res.scenario.program_term_meeting_slots[0].term_id, "MA_T1")

	def test_duplicate_identical_category_is_warning(self):
		cats = rows()["Categories"] * 2
		res = ScenarioBuilder(rows(Categories=cats)).build()
		self.assertTrue(res.ok)
		self.assertIn("duplicate_category", [i.code for i in res.issues if i.level == "warning"])


class TestPreflight(unittest.TestCase):
	def test_no_room_big_enough(self):
		r = rows()
		r["Sections"][0]["required_room_capacity"] = 500
		issues = run_preflight(ScenarioBuilder(r).build().scenario)
		self.assertIn("no_room", [i.code for i in issues if i.level == "error"])

	def test_zero_starts(self):
		r = rows()
		for d in ("Mon", "Tue", "Wed", "Thu", "Fri"):
			r["Faculty"][0][d] = "0,5"  # only non-regular slots
		issues = run_preflight(ScenarioBuilder(r).build().scenario)
		self.assertIn("zero_starts", [i.code for i in issues])


class TestSolve(unittest.TestCase):
	def _solve(self, fix):
		r = rows()
		# one room, both sections pinned to the same single slot pair: only solvable by sharing the room
		for s in r["Sections"]:
			s["theory_durations"] = "1"
			s["allowed_slots"] = "1"
		sc = ScenarioBuilder(r).build().scenario
		model, _ = runner.quiet(runner.build_model, sc, None, fix)
		return runner.solve(model, time_limit=20, num_workers=2)

	def test_upstream_allows_cross_term_double_booking(self):
		res = self._solve(fix=False)
		self.assertIn(res.status, ("OPTIMAL", "FEASIBLE"))
		rooms = {(e["day_index"], e["slot_index"], e["room_id"]) for e in res.entries}
		self.assertEqual(len(rooms), 1)  # both sessions in Room 1 at the same time

	def test_fix_prevents_cross_term_double_booking(self):
		res = self._solve(fix=True)
		self.assertEqual(res.status, "INFEASIBLE")

	def test_full_solve_and_checks(self):
		sc = ScenarioBuilder(rows()).build().scenario
		model, _ = runner.quiet(runner.build_model, sc)
		res = runner.solve(model, time_limit=30, num_workers=2)
		self.assertIn(res.status, ("OPTIMAL", "FEASIBLE"))
		self.assertEqual(len(res.entries), 4)
		ctx = Context(
			terms={"MA_T1": (date(2027, 1, 18), date(2027, 5, 7)), "UG_T1": (date(2027, 1, 18), date(2027, 5, 8))},
			choice_types={"core": "NONE"},
			rooms={"R1": {"name": "Room 1", "type": "CLASSROOM", "capacity": 40, "lab_type": "", "slots": set(range(36))}},
			faculty_slots={"a@x.edu": set(range(30)), "b@x.edu": set(range(30))},
			sections={"MA101__Section_1": {"capacity": 30}, "UG101__Section_1": {"capacity": 30}},
		)
		ents = []
		for i, e in enumerate(res.entries):
			sec = next(s for s in sc.sections if s.id == e["section_key"])
			ents.append({**e, "name": str(i), "course_code": sec.course_id, "category": sec.category_id,
						 "faculty_ids": sec.faculty_ids, "cohorts": sec.eligible_cohorts})  # fmt: skip
		self.assertEqual(check_entries(ents, ctx), [])
		# force a clash and make sure it is detected
		ents[1] = {**ents[1], "day_index": ents[2]["day_index"], "slot_index": ents[2]["slot_index"]}
		rules = {i["rule"] for i in check_entries(ents, ctx)}
		self.assertTrue(rules & {"room_double_booked", "same_day", "faculty_double_booked"})
		self.assertTrue(len(free_slots(ents, ctx, "cohort", "MA26")) > 0)


class TestSectionCapacity(unittest.TestCase):
	def test_each_section_gets_a_room_big_enough(self):
		r = rows()
		r["Rooms"] = [
			{"id": "S", "name": "Small", "type": "CLASSROOM", "classroom_capacity": 50, **{d: "ALL" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")}},
			{"id": "B", "name": "Big", "type": "CLASSROOM", "classroom_capacity": 70, **{d: "ALL" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")}},
		]
		sec2 = {**r["Sections"][0], "section_number": 2, "required_room_capacity": 70, "faculty_id": "b@x.edu"}
		r["Sections"] = [{**r["Sections"][0], "required_room_capacity": 50}, sec2]
		res = ScenarioBuilder(r).build()
		self.assertEqual(res.section_reqs["MA101__Section_2"]["capacity"], 70)
		model, _ = runner.quiet(runner.build_model, res.scenario, None, True, res.section_reqs)
		out = runner.solve(model, time_limit=20, num_workers=2)
		self.assertIn(out.status, ("OPTIMAL", "FEASIBLE"))
		for e in out.entries:
			if e["section_key"] == "MA101__Section_2":
				self.assertEqual(e["room_id"], "B")

	def test_preflight_uses_section_capacity(self):
		r = rows()
		r["Sections"].append({**r["Sections"][0], "section_number": 2, "required_room_capacity": 90, "faculty_id": "b@x.edu"})
		res = ScenarioBuilder(r).build()
		codes = [i.code for i in run_preflight(res.scenario, res.section_reqs) if i.level == "error"]
		self.assertIn("no_room", codes)


class TestCohortRules(unittest.TestCase):
	def test_stackable_categories_do_not_clash(self):
		ctx = Context(choice_types={"elec": "GROUPED", "core": "NONE"})
		a = {"name": "a", "session_key": "A", "section_key": "A__Section_1", "course_code": "A", "category": "ELEC", "day_index": 0,
			 "slot_index": 1, "duration": 1, "room_id": "", "faculty_ids": ["x"], "cohorts": ["C1"], "term_id": "FULL"}  # fmt: skip
		b = {**a, "name": "b", "session_key": "B", "section_key": "B__Section_1", "course_code": "B", "faculty_ids": ["y"]}
		self.assertNotIn("cohort_clash", {i["rule"] for i in check_entries([a, b], ctx)})
		b["category"] = "CORE"
		self.assertIn("cohort_clash", {i["rule"] for i in check_entries([a, b], ctx)})


if __name__ == "__main__":
	unittest.main()
