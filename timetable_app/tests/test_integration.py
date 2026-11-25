"""End-to-end tests of the Frappe app on a real site, using synthetic data.

Each test creates its own throw-away plan ("_TT Test ...") and deletes it afterwards,
so it is safe to run on a development site:

    cd <bench>/sites
    TT_TEST_SITE=timetable.local ../env/bin/python -m unittest timetable_app.tests.test_integration

(It also runs under ``bench --site <test-site> run-tests --app timetable_app``.)
"""

import os
import unittest
from unittest import mock

import frappe

from timetable_app.engine.workbook import INPUT_SHEETS, read_workbook, write_workbook


def _connect():
	if getattr(frappe.local, "db", None):
		return False
	site = os.environ.get("TT_TEST_SITE")
	if not site:
		raise unittest.SkipTest("set TT_TEST_SITE=<site> (or run through bench run-tests)")
	frappe.init(site=site, sites_path=os.environ.get("TT_SITES_PATH", "."))
	frappe.connect()
	return True


def _workbook_bytes() -> bytes:
	from timetable_app.tests.test_engine import rows

	data = rows()
	return write_workbook({n: (cols, [[r.get(c) for c in cols] for r in data.get(n, [])]) for n, cols in INPUT_SHEETS.items()})


def _run_now(method, **kwargs):
	"""Stand-in for frappe.enqueue: run the generation job synchronously."""
	frappe.get_attr(method)(version=kwargs["version"])


class TimetableIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls._own_connection = _connect()
		frappe.set_user("Administrator")
		from timetable_app.setup import ensure_roles

		ensure_roles()

	@classmethod
	def tearDownClass(cls):
		if cls._own_connection:
			frappe.destroy()

	def setUp(self):
		from timetable_app.api import data_io

		self.plan = data_io.create_plan(f"_TT Test {frappe.generate_hash(length=6)}", campus="Test", start_date="2027-01-18", end_date="2027-05-08")
		self.file = frappe.get_doc({"doctype": "File", "file_name": "tt_test.xlsx", "content": _workbook_bytes(), "is_private": 1}).insert()
		frappe.db.commit()

	def tearDown(self):
		frappe.db.rollback()
		frappe.cache.delete_keys("tt_cancel::")
		for v in frappe.get_all("TT Version", filters={"plan": self.plan}, pluck="name"):
			frappe.db.set_value("TT Version", v, {"approval_status": "Draft", "run_status": "Completed"})
		frappe.db.set_value("TT Plan", self.plan, {"active_version": None, "status": "Setup"})
		frappe.delete_doc("TT Plan", self.plan, force=1, ignore_permissions=True)
		frappe.delete_doc("File", self.file.name, force=1, ignore_permissions=True)
		frappe.db.commit()

	# ------------------------------------------------------------------ helpers
	def _import(self):
		from timetable_app.api import data_io

		return data_io.import_workbook(self.plan, self.file.file_url)

	def _generate(self):
		from timetable_app.api import scheduler

		self._import()
		self.assertTrue(scheduler.check_readiness(self.plan)["ok"])
		with mock.patch.object(frappe, "enqueue", side_effect=_run_now):
			v = scheduler.generate(self.plan, label="Test run", time_limit=1)
		return v

	# ------------------------------------------------------------------ tests
	def test_plan_defaults(self):
		p = frappe.get_doc("TT Plan", self.plan)
		self.assertEqual([s.slot_index for s in p.slots], [0, 1, 2, 3, 4, 5])
		self.assertEqual(p.w_meeting, 100)

	def test_preview_and_import(self):
		from timetable_app.api import data_io

		pv = data_io.preview_workbook(self.file.file_url)
		self.assertEqual(pv["errors"], 0)
		self.assertEqual(pv["sheets"]["Sections"], 2)
		res = self._import()
		self.assertEqual(res["skipped"], [])
		self.assertEqual(res["counts"]["TT Section"], 2)
		self.assertEqual(frappe.db.get_value("TT Section", {"plan": self.plan, "course_code": "MA101"}, "section_key"), "MA101__Section_1")
		self.assertEqual(frappe.db.get_value("TT Section", {"plan": self.plan, "course_code": "MA101"}, "serial_no"), "1_PG")

	def test_readiness_sets_ready(self):
		from timetable_app.api import scheduler

		self._import()
		r = scheduler.check_readiness(self.plan)
		self.assertTrue(r["ok"], r["issues"])
		self.assertEqual(frappe.db.get_value("TT Plan", self.plan, "status"), "Ready")

	def test_validation_rejects_bad_data(self):
		self._import()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "TT Room", "plan": self.plan, "room_id": "X1", "room_type": "CLASSROOM", "capacity": 0}).insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "TT Room", "plan": self.plan, "room_id": "R1", "room_type": "CLASSROOM", "capacity": 10}).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "TT Section", "plan": self.plan, "course_code": "Z1", "category": "CORE"}).insert()

	def test_generate_review_and_checks(self):
		from timetable_app.api import review

		v = self._generate()
		doc = frappe.get_doc("TT Version", v)
		self.assertEqual(doc.run_status, "Completed", doc.error)
		self.assertEqual(doc.entries_count, 4)
		self.assertEqual(doc.hard_issues, 0)
		self.assertTrue(review.get_version(v)["editable"])
		entries = review.get_entries(v)["entries"]
		self.assertEqual(len(entries), 4)

	def test_move_detects_clashes(self):
		from timetable_app.api import review

		v = self._generate()
		entries = review.get_entries(v)["entries"]
		a, b = entries[0], next(e for e in entries[1:] if e["section_key"] != entries[0]["section_key"])
		# moving A onto B's slot and room double-books the only room: refused without force
		r = review.move_entry(a["name"], b["day_index"], b["slot_index"], b["room_id"])
		self.assertFalse(r["saved"])
		self.assertIn("room_double_booked", {i["rule"] for i in r["issues"]})
		# a clean option is accepted
		opt = next(o for o in review.move_options(a["name"])["options"] if not o["issues"] and o["free_rooms"] and not o["current"])
		r = review.move_entry(a["name"], opt["day_index"], opt["slot_index"], opt["free_rooms"][0])
		self.assertTrue(r["saved"])
		self.assertEqual(frappe.db.get_value("TT Entry", a["name"], "is_manual"), 1)

	def test_reports_build(self):
		from timetable_app.api import reports

		v = self._generate()
		for key in reports.REPORTS:
			name, content = reports.build_report(v, key)
			self.assertTrue(name.endswith(".xlsx"))
			self.assertGreater(len(content), 1000, key)

	def test_approval_locks_and_reopens(self):
		from timetable_app.api import review

		v = self._generate()
		review.submit_version(v, "please review")
		review.approve_version(v, "ok")
		self.assertEqual(frappe.db.get_value("TT Plan", self.plan, ["status", "active_version"]), ("Finalised", v))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "TT Room", "plan": self.plan, "room_id": "R9", "room_type": "CLASSROOM", "capacity": 10}).insert()
		review.reopen_plan(self.plan)
		self.assertEqual(frappe.db.get_value("TT Plan", self.plan, "status"), "Generated")

	def test_cancel_queued_and_copy(self):
		from timetable_app.api import review, scheduler

		v = self._generate()
		copy = review.copy_version(v, "copy")
		self.assertEqual(frappe.db.count("TT Entry", {"version": copy}), 4)
		with self.assertRaises(frappe.ValidationError):
			scheduler.cancel(copy)  # not running

	def test_export_round_trip(self):
		from timetable_app.api.common import plan_rows
		from timetable_app.engine.scenario_builder import ScenarioBuilder

		self._import()
		rows = plan_rows(self.plan)
		self.assertTrue(ScenarioBuilder(rows).build().ok)
		self.assertIn("1_PG", [r.get("SI no") for r in rows["Sections"]])  # every workbook column survives the round trip

	def test_session_and_overview(self):
		from timetable_app.api import session

		self._import()
		ov = session.get_overview(self.plan)
		self.assertEqual(ov["counts"]["TT Section"], 2)
		self.assertEqual(len(ov["steps"]), 8)
		self.assertIn(self.plan, [p.name for p in session.list_plans()])
		self.assertTrue(session.get_session()["is_manager"])

	# ------------------------------------------------------------------ week structure
	def _set_week(self, days, slots, regular_days=None):
		p = frappe.get_doc("TT Plan", self.plan)
		p.teaching_days = ",".join(days)
		p.regular_days = ",".join(regular_days or [d for d in days if d not in ("Sat", "Sun")])
		p.set("slots", slots)
		p.save()
		return p

	def test_week_change_remaps_saved_slots(self):
		self._import()
		sec = frappe.get_doc("TT Section", {"plan": self.plan, "course_code": "MA101"})
		sec.allowed_slots = "7,13"  # Tue slot 1, Wed slot 1
		sec.save()
		frappe.db.set_value("TT Faculty", {"plan": self.plan, "faculty_id": "a@x.edu"}, "mon", "1,2")
		old = frappe.get_doc("TT Plan", self.plan)
		rows = [{"name": r.name, "label": r.label, "regular": r.regular} for r in old.slots]
		# insert a new first slot and drop the last one; remove Saturday
		new_rows = [{"label": "Very early", "regular": 0}, *rows[:-1]]
		self._set_week(["Mon", "Tue", "Wed", "Thu", "Fri"], new_rows)
		from timetable_app.timetable_generator.utils import plan_week

		w = plan_week(self.plan)
		self.assertEqual((w.days, w.slots_per_day), (("Mon", "Tue", "Wed", "Thu", "Fri"), 6))
		# Tue slot 1 -> Tue slot 2 (=1*6+2), Wed slot 1 -> Wed slot 2 (=2*6+2)
		self.assertEqual(frappe.db.get_value("TT Section", sec.name, "allowed_slots"), "8,14")
		self.assertEqual(frappe.db.get_value("TT Faculty", {"plan": self.plan, "faculty_id": "a@x.edu"}, "mon"), "2,3")

	def test_slot_times_are_normalised(self):
		p = frappe.get_doc("TT Plan", self.plan)
		p.slots[0].start_time, p.slots[0].end_time = "6:30:", "8:00"
		p.save()
		p.reload()
		self.assertEqual((str(p.slots[0].start_time), str(p.slots[0].end_time)), ("6:30:00", "8:00:00"))
		p.slots[0].end_time = "6:00"
		with self.assertRaises(frappe.ValidationError):
			p.save()

	def test_week_change_blocked_with_versions(self):
		self._generate()
		old = frappe.get_doc("TT Plan", self.plan)
		rows = [{"name": r.name, "label": r.label, "regular": r.regular} for r in old.slots]
		with self.assertRaises(frappe.ValidationError):  # inserting a slot at the start moves every session
			self._set_week(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], [{"label": "Dawn", "regular": 0}, *rows])
		with self.assertRaises(frappe.ValidationError):  # removing a day
			self._set_week(["Mon", "Tue", "Wed", "Thu", "Fri"], rows)

	def test_append_slot_keeps_versions_valid(self):
		import json

		from timetable_app.api import data_io, review, scheduler

		v = self._generate()
		before = review.get_entries(v)["entries"]
		hint_before = json.loads(frappe.db.get_value("TT Version", v, "hint"))
		week = data_io.add_time_slot(self.plan, "Late evening", "21:00", "22:00", 0)
		self.assertEqual(week["slots_per_day"], 7)
		self.assertEqual(frappe.get_doc("TT Plan", self.plan).slots[-1].label, "Late evening")
		# sessions keep their day and slot; absolute numbers are re-based on 7 slots a day
		after = {e["name"]: e for e in review.get_entries(v)["entries"]}
		for e in before:
			self.assertEqual((after[e["name"]]["day_index"], after[e["name"]]["slot_index"]), (e["day_index"], e["slot_index"]))
			self.assertTrue(all(x // 7 == old // 6 and x % 7 == old % 6 for x, old in zip(after[e["name"]]["allowed_starts"], e["allowed_starts"])))
		hint_after = json.loads(frappe.db.get_value("TT Version", v, "hint"))
		self.assertEqual({k: (x // 7, x % 7) for k, x in hint_after.items()}, {k: (x // 6, x % 6) for k, x in hint_before.items()})
		self.assertEqual(scheduler.rerun_checks(v), [])
		with self.assertRaises(frappe.ValidationError):
			data_io.add_time_slot(self.plan, "late EVENING")  # names must be unique

	def test_generate_with_custom_week(self):
		from timetable_app.api import review

		self._import()
		old = frappe.get_doc("TT Plan", self.plan)
		rows = [{"name": r.name, "label": r.label, "regular": r.regular} for r in old.slots]
		self._set_week(["Mon", "Tue", "Wed", "Thu", "Fri"], [*rows, {"label": "Slot 6", "regular": 1}, {"label": "Slot 7", "regular": 0}])
		for f in frappe.get_all("TT Faculty", filters={"plan": self.plan}, pluck="name"):
			frappe.db.set_value("TT Faculty", f, {d: "ALL" for d in ("mon", "tue", "wed", "thu", "fri")})
		v = self._generate()
		doc = frappe.get_doc("TT Version", v)
		self.assertEqual(doc.run_status, "Completed", doc.error)
		self.assertEqual(doc.hard_issues, 0)
		data = review.get_version(v)
		self.assertEqual(data["week"]["slots_per_day"], 8)
		self.assertTrue(all(e["slot_index"] < 8 and e["day_index"] < 5 for e in review.get_entries(v)["entries"]))

	# ------------------------------------------------------------------ faculty from the course list
	def test_section_creates_missing_faculty(self):
		self._import()
		frappe.get_doc({"doctype": "TT Section", "plan": self.plan, "course_code": "NEW1", "category": "CORE", "theory_durations": "1",
						"required_room_capacity": 20, "faculty_ids": "juhi.tyagi@x.edu, a@x.edu", "program_ids": "MA"}).insert()  # fmt: skip
		fac = frappe.get_doc("TT Faculty", {"plan": self.plan, "faculty_id": "juhi.tyagi@x.edu"})
		self.assertEqual(fac.faculty_name, "Juhi Tyagi")
		self.assertEqual([fac.get(d) for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")], ["ALL"] * 6 + ["NONE"])
		self.assertEqual(fac.program_ids, "MA")
		self.assertEqual(frappe.db.count("TT Faculty", {"plan": self.plan, "faculty_id": "a@x.edu"}), 1)  # existing one untouched

	def test_import_creates_faculty_named_only_in_sections(self):
		from timetable_app.api import data_io, scheduler
		from timetable_app.tests.test_engine import rows

		data = rows()
		data["Faculty"] = data["Faculty"][:1]  # b@x.edu only appears in Sections
		content = write_workbook({n: (cols, [[r.get(c) for c in cols] for r in data.get(n, [])]) for n, cols in INPUT_SHEETS.items()})
		f = frappe.get_doc({"doctype": "File", "file_name": "tt_test2.xlsx", "content": content, "is_private": 1}).insert()
		try:
			res = data_io.import_workbook(self.plan, f.file_url)
			self.assertEqual(res["counts"].get("TT Faculty (added from sections)"), 1)
			self.assertTrue(frappe.db.exists("TT Faculty", {"plan": self.plan, "faculty_id": "b@x.edu"}))
			self.assertTrue(scheduler.check_readiness(self.plan)["ok"])
		finally:
			frappe.delete_doc("File", f.name, force=1, ignore_permissions=True)



if __name__ == "__main__":
	unittest.main()
