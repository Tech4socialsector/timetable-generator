"""Migration tests: the original engine (main.py, src/) and the Frappe app live in one repository.

Run without Frappe:
    cd <bench>/apps/timetable-generator && ../../env/bin/python -m unittest timetable_app.tests.test_migration

These guard that
* the original command-line code is untouched and still importable,
* the app runs on the repository's own ``src/`` engine (no stale copies),
* every solver method / argument the app relies on still exists in ``src/solver.py``
  (so a rename upstream fails here, not in production),
* packaging and the frontend build are independent of the repository folder name.
"""

import importlib
import inspect
import shutil
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import timetable_app
from timetable_app.engine import _upstream, domain, runner, solver
from timetable_app.engine.scenario_builder import ScenarioBuilder

REPO = Path(timetable_app.__file__).resolve().parents[1]
ORIGINAL_FILES = ["main.py", "requirements.txt", "README.md", "src/__init__.py", "src/domain.py", "src/solver.py", "src/data_loader.py"]


class TestOriginalCodeUntouched(unittest.TestCase):
	def test_original_files_exist(self):
		for f in ORIGINAL_FILES:
			self.assertTrue((REPO / f).is_file(), f"{f} is missing from the repository root")

	@unittest.skipUnless(shutil.which("git") and (REPO / ".git").exists(), "not a git checkout")
	def test_original_files_unchanged_from_git(self):
		tracked = subprocess.run(["git", "ls-files", "--", *ORIGINAL_FILES], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
		if not tracked:
			self.skipTest("original files are not committed in this checkout")
		diff = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", *tracked], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
		self.assertEqual(diff, "", f"original command-line files were modified: {diff}")

	def test_original_engine_imports(self):
		for mod in ("src.domain", "src.solver", "src.data_loader"):
			importlib.import_module(mod)

	def test_main_py_imports_without_running(self):
		spec = importlib.util.spec_from_file_location("timetable_main_check", REPO / "main.py")
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)  # __name__ != "__main__", so main() is not executed
		self.assertTrue(callable(module.main))


class TestAppUsesRepositoryEngine(unittest.TestCase):
	def test_solver_is_src_solver(self):
		import src.solver

		self.assertIs(solver.TimetableSolver, src.solver.TimetableSolver)
		self.assertEqual(Path(src.solver.__file__).resolve(), (REPO / "src" / "solver.py").resolve())

	def test_domain_models_are_src_models(self):
		import src.domain

		for name in ("Course", "Section", "TeachingLocation", "TimetableScenario", "CourseCategory", "Term"):
			self.assertIs(getattr(domain, name), getattr(src.domain, name), name)
		self.assertTrue(issubclass(domain.Faculty, src.domain.Faculty))

	def test_no_engine_copies_in_app(self):
		engine = REPO / "timetable_app" / "engine"
		for f in ("solver.py", "domain.py"):
			self.assertNotIn("class TimetableSolver", (engine / f).read_text())
			self.assertNotIn("class TimetableScenario", (engine / f).read_text())

	def test_loader_rejects_missing_engine(self):
		with mock.patch.object(_upstream, "SRC_DIR", REPO / "does-not-exist"):
			with self.assertRaises(ImportError):
				_upstream.load("solver")

	def test_loader_rejects_shadowing_src_package(self):
		fake = type(sys)("src")
		fake.__file__ = "/somewhere/else/src/__init__.py"
		with mock.patch.dict(sys.modules, {"src": fake}):
			with self.assertRaises(ImportError):
				_upstream.load("solver")

	def test_faculty_programmes_reach_the_solver(self):
		from timetable_app.tests.test_engine import rows

		r = rows()
		r["Faculty"][0]["program_id"] = "MA"
		r["Meeting Slots"] = [{"program_id": "MA", "term_id": "MA_T1", "meeting_slots": "14", "attendee_type": "FACULTY_ONLY"}]
		sc = ScenarioBuilder(r).build().scenario
		fac = next(f for f in sc.faculty if f.id == "a@x.edu")
		self.assertEqual(getattr(fac, "program_ids", None), ["MA"])  # what src/solver.py reads


class TestSolverContract(unittest.TestCase):
	"""Every method and keyword argument the app calls on src/solver.py must exist."""

	CALLS = {
		"create_variables": [],
		"add_faculty_constraints": [],
		"add_daily_distribution_constraints": ["consecutive_day_penalty"],
		"add_unified_cohort_constraints": [],
		"add_room_availability_constraints": [],
		"add_meeting_slot_penalties": ["default_violation_penalty", "global_violation_penalty"],
		"add_faculty_rest_soft_constraint": ["penalty_weight"],
		"add_faculty_free_day_soft_constraint": ["penalty_weight"],
		"add_preferred_building_constraints": ["penalty"],
		"add_cohort_spreading_soft_constraints": ["empty_day_penalty", "overcrowding_penalty"],
		"add_preferred_room_layout_constraints": ["penalty"],
		"get_allowed_start_indices": ["section", "duration"],
		"_get_feasible_locations": ["course", "s_type"],
		"report_meeting_violations": ["solver"],
		"report_hardwall_violations": ["solver"],
		"report_faculty_free_day_violations": ["solver"],
	}

	def test_methods_and_arguments(self):
		for name, args in self.CALLS.items():
			fn = getattr(solver.TimetableSolver, name, None)
			self.assertIsNotNone(fn, f"src/solver.py no longer has TimetableSolver.{name}")
			params = inspect.signature(fn).parameters
			for a in args:
				self.assertIn(a, params, f"TimetableSolver.{name} no longer accepts '{a}'")

	def test_attributes_used_after_create_variables(self):
		from timetable_app.tests.test_engine import rows

		s = solver.TimetableSolver(ScenarioBuilder(rows()).build().scenario)
		s.create_variables()
		for attr in ("session_vars", "room_intervals", "faculty_intervals", "penalties", "conflicts", "model", "slots_per_day"):
			self.assertTrue(hasattr(s, attr), attr)
		data = next(iter(s.session_vars.values()))
		for key in ("section", "start", "presences", "presence_map", "duration", "type", "allowed_starts_list", "term_id"):
			self.assertIn(key, data)

	def test_weighted_model_builds(self):
		from timetable_app.tests.test_engine import rows

		r = ScenarioBuilder(rows()).build()
		model, _ = runner.quiet(runner.build_model, r.scenario, {k: 50 for k in runner.RULES}, True, r.section_reqs)
		self.assertTrue(model.penalties is not None)


class TestPackaging(unittest.TestCase):
	def test_only_app_package_is_installed(self):
		cfg = tomllib.loads((REPO / "pyproject.toml").read_text())
		self.assertEqual(cfg["project"]["name"], "timetable_app")
		self.assertEqual(cfg["tool"]["flit"]["module"]["name"], "timetable_app")

	def test_hooks_app_name(self):
		self.assertIn('app_name = "timetable_app"', (REPO / "timetable_app" / "hooks.py").read_text())

	def test_frontend_build_paths_are_explicit(self):
		cfg = (REPO / "frontend" / "vite.config.js").read_text()
		self.assertIn("../timetable_app/public/frontend", cfg)
		self.assertIn("../timetable_app/www/timetable.html", cfg)
		self.assertIn("/assets/timetable_app/frontend/", cfg)

	def test_gitignore_keeps_build_output_out(self):
		ignore = (REPO / ".gitignore").read_text()
		for pattern in ("node_modules/", "timetable_app/public/frontend/", "timetable_app/www/timetable.html", ".venv*/"):
			self.assertIn(pattern, ignore)


if __name__ == "__main__":
	unittest.main()
