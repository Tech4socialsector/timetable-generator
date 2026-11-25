"""Run the CP-SAT timetable solver with configurable rule weights.

The solver is ``src/solver.py`` from this repository (the engine ``main.py``
uses), loaded unchanged through ``engine/solver.py``. This module drives it:

* builds the model with rule weights (100 = upstream default penalty),
* adds the cross-term room / faculty no-overlap fix (upstream only prevents
  double booking within the *same* term id, not across overlapping terms),
* runs the search with a progress callback, a stop flag and an in-memory hint,
* returns plain-dict results and diagnostics (no printing, no files).
"""

from __future__ import annotations

import contextlib
import io
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .domain import TimetableScenario
from .plan_solver import PlanSolver
from .week import DEFAULT_WEEK
from .solver import TimetableSolver

# rule key -> (label, help text). Weight 100 reproduces the upstream penalty.
RULES: dict[str, tuple[str, str]] = {
	"meeting": ("Keep meeting slots free", "Avoid scheduling classes in programme meeting slots."),
	"faculty_rest": ("Faculty rest", "Avoid back-to-back classes for a faculty member."),
	"faculty_free_day": ("Faculty free day", "Give each faculty member at least one day without classes or meetings."),
	"session_gap": ("Gap between sessions", "Avoid sessions of the same section on consecutive days."),
	"balance": ("Balanced week", "Avoid days with no classes for a cohort."),
	"building": ("Preferred building", "Use the section's preferred building."),
	"layout": ("Preferred room layout", "Use a room with the preferred layout."),
}
DEFAULT_WEIGHTS = {k: 100 for k in RULES}

# upstream default penalty values
_BASE = {
	"meeting": 100000,
	"meeting_global": 200000,
	"faculty_rest": 5000,
	"faculty_free_day": 10000,
	"session_gap": 5000,
	"balance_empty_day": 4000,
	"balance_overcrowding": 40,
	"building": 1000,
	"layout": 2000,
}


def _scaled(base: int, weight: float) -> int:
	return max(0, round(base * float(weight) / 100.0))


@dataclass
class SolveResult:
	status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | MODEL_INVALID | UNKNOWN | CANCELLED
	objective: float | None = None
	best_bound: float | None = None
	wall_time: float = 0.0
	seed: int | None = None
	solutions_found: int = 0
	entries: list[dict] = field(default_factory=list)
	violations: list[dict] = field(default_factory=list)
	hint: dict[str, int] = field(default_factory=dict)
	stats: dict = field(default_factory=dict)
	log: str = ""

	@property
	def has_solution(self) -> bool:
		return self.status in ("OPTIMAL", "FEASIBLE") or (self.status == "CANCELLED" and bool(self.entries))


def build_model(
	scenario: TimetableScenario,
	weights: dict | None = None,
	fix_cross_term_overlap: bool = True,
	section_reqs: dict | None = None,
	week=None,
) -> TimetableSolver:
	"""Create variables and constraints (same order as TimetableSolver.add_constraints)."""
	w = {**DEFAULT_WEIGHTS, **(weights or {})}
	s = PlanSolver(scenario, section_reqs, week)
	s.create_variables()

	for data in s.session_vars.values():
		s.model.Add(sum(data["presences"]) == 1)
	for intervals in s.room_intervals.values():
		s.model.AddNoOverlap(intervals)
	s.add_faculty_constraints()
	if fix_cross_term_overlap:
		_add_cross_term_no_overlap(s)

	s.add_daily_distribution_constraints(consecutive_day_penalty=_scaled(_BASE["session_gap"], w["session_gap"]))
	s.add_unified_cohort_constraints()
	s.add_room_availability_constraints()
	s.add_meeting_slot_penalties(
		default_violation_penalty=_scaled(_BASE["meeting"], w["meeting"]),
		global_violation_penalty=_scaled(_BASE["meeting_global"], w["meeting"]),
	)
	s.add_faculty_rest_soft_constraint(penalty_weight=_scaled(_BASE["faculty_rest"], w["faculty_rest"]))
	s.add_faculty_free_day_soft_constraint(penalty_weight=_scaled(_BASE["faculty_free_day"], w["faculty_free_day"]))
	s.add_preferred_building_constraints(penalty=_scaled(_BASE["building"], w["building"]))
	s.add_cohort_spreading_soft_constraints(
		empty_day_penalty=_scaled(_BASE["balance_empty_day"], w["balance"]),
		overcrowding_penalty=_scaled(_BASE["balance_overcrowding"], w["balance"]),
	)
	s.add_preferred_room_layout_constraints(penalty=_scaled(_BASE["layout"], w["layout"]))
	return s


def _add_cross_term_no_overlap(s: TimetableSolver) -> None:
	"""Rooms and faculty must not be double booked across *different* overlapping terms."""
	for table in (s.room_intervals, s.faculty_intervals):
		by_resource: dict[str, dict[str, list]] = {}
		for (res_id, term_id), intervals in table.items():
			by_resource.setdefault(res_id, {})[term_id] = intervals
		for terms in by_resource.values():
			for t1, t2 in itertools.combinations(sorted(terms), 2):
				if s.scenario.terms_overlap(t1, t2):
					merged = terms[t1] + terms[t2]
					if len(merged) > 1:
						s.model.AddNoOverlap(merged)


def apply_hint(s: TimetableSolver, hint: dict[str, int] | None) -> tuple[int, int]:
	if not hint:
		return 0, 0
	loaded = skipped = 0
	for suffix, start in hint.items():
		data = s.session_vars.get(suffix)
		if data is not None and start in data["allowed_starts_list"]:
			s.model.AddHint(data["start"], int(start))
			loaded += 1
		else:
			skipped += 1
	return loaded, skipped


class _Tracker(cp_model.CpSolverSolutionCallback):
	"""Runs inside CP-SAT threads: only records plain Python values (no Frappe calls here)."""

	def __init__(self):
		super().__init__()
		self.t0 = time.time()
		self.count = 0
		self.objective: float | None = None
		self.bound: float | None = None
		self.history: list[tuple[float, float]] = []

	def on_solution_callback(self):
		self.count += 1
		self.objective = self.ObjectiveValue()
		self.bound = self.BestObjectiveBound()
		self.history.append((round(time.time() - self.t0, 1), self.objective))

	def snapshot(self) -> dict:
		return {"solutions": self.count, "objective": self.objective, "bound": self.bound, "elapsed": time.time() - self.t0}


def solve(
	s: TimetableSolver,
	time_limit: int = 300,
	seed: int | None = None,
	num_workers: int = 8,
	on_tick: Callable[[dict], bool | None] | None = None,
	tick_seconds: float = 2.0,
) -> SolveResult:
	"""Solve in a helper thread. ``on_tick(snapshot)`` is called from the *calling* thread every
	``tick_seconds`` (safe for Frappe DB / cache / realtime calls); returning True stops the search
	and keeps the best timetable found so far."""
	cp = cp_model.CpSolver()
	cp.parameters.max_time_in_seconds = float(time_limit)
	cp.parameters.num_workers = int(num_workers)
	cp.parameters.exploit_best_solution = True
	seed = int(seed) if seed is not None else int(time.time()) % 2**31
	cp.parameters.random_seed = seed
	if s.penalties:
		s.model.Minimize(sum(s.penalties))

	tracker = _Tracker()
	box: dict = {}

	def run():
		try:
			box["status"] = cp.Solve(s.model, tracker)
		except BaseException as e:  # surfaced below
			box["error"] = e

	t0 = time.time()
	worker = threading.Thread(target=run, name="cp-sat", daemon=True)
	worker.start()
	cancelled = False
	while worker.is_alive():
		worker.join(tick_seconds)
		if worker.is_alive() and on_tick is not None:
			try:
				stop = on_tick(tracker.snapshot())
			except Exception:
				stop = False  # progress reporting must never kill the search
			if stop and not cancelled:
				cancelled = True
				cp.StopSearch()
	if "error" in box:
		raise box["error"]
	status = box["status"]

	name = cp.StatusName(status)
	result = SolveResult(
		status="CANCELLED" if cancelled else name,
		wall_time=round(time.time() - t0, 1),
		seed=seed,
		solutions_found=tracker.count,
		stats={
			"variables": len(s.model.Proto().variables),
			"constraints": len(s.model.Proto().constraints),
			"sessions": len(s.session_vars),
			"history": tracker.history[-200:],
		},
	)
	if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
		result.objective = cp.ObjectiveValue()
		result.best_bound = cp.BestObjectiveBound()
		result.entries = extract_entries(s, cp)
		result.violations = extract_violations(s, cp)
		result.hint = {k: cp.Value(d["start"]) for k, d in s.session_vars.items()}
		buf = io.StringIO()
		with contextlib.redirect_stdout(buf):
			# upstream text reports, kept for the run log (they assume the standard 6-slot week)
			for fn in () if getattr(s, "week", DEFAULT_WEEK) != DEFAULT_WEEK else (s.report_meeting_violations, s.report_hardwall_violations, s.report_faculty_free_day_violations):
				try:
					fn(cp)
				except Exception as e:
					print(f"[report {fn.__name__} failed: {e}]")
		result.log = buf.getvalue()
	return result


def split_suffix(suffix: str) -> tuple[str, str, int]:
	"""'668426__Section_1_THEORY_0' -> ('668426__Section_1', 'THEORY', 0)"""
	head, s_type, idx = suffix.rsplit("_", 2)
	return head, s_type, int(idx)


def extract_entries(s: TimetableSolver, cp: cp_model.CpSolver) -> list[dict]:
	out = []
	spd = s.slots_per_day
	for suffix, data in s.session_vars.items():
		start = cp.Value(data["start"])
		room = ""
		for room_id, pres in data["presence_map"].items():
			if cp.BooleanValue(pres):
				room = "" if room_id == "NO_ROOM" else room_id
				break
		sec = data["section"]
		_, s_type, idx = split_suffix(suffix)
		out.append(
			{
				"session_key": suffix,
				"section_key": sec.id,
				"session_type": s_type,
				"session_index": idx,
				"day_index": start // spd,
				"slot_index": start % spd,
				"duration": data["duration"],
				"room_id": room,
				"term_id": sec.term_id,
				"allowed_starts": list(data["allowed_starts_list"]),
			}
		)
	return out


def extract_violations(s: TimetableSolver, cp: cp_model.CpSolver) -> list[dict]:
	"""Soft-constraint violations in the chosen solution."""
	v: list[dict] = []
	spd = s.slots_per_day
	for m in getattr(s, "meeting_violations", []):
		if cp.BooleanValue(m["var"]):
			v.append({"rule": "meeting", "session_key": m["suffix"], "day_index": m["slot"] // spd, "slot_index": m["slot"] % spd,
					  "message": f"{m['suffix']} is in a programme meeting slot."})  # fmt: skip
	for h in getattr(s, "hard_wall_violations", []):
		if cp.Value(h["var"]):
			v.append({"rule": "cohort_clash", "cohort": h["cohort"], "slot": h["slot"],
					  "message": f"Cohort {h['cohort']}: '{h['unit_1']}' and '{h['unit_2']}' clash at slot {h['slot']}."})  # fmt: skip
	for f in getattr(s, "faculty_free_day_violations", []):
		if cp.BooleanValue(f["var"]):
			v.append({"rule": "faculty_free_day", "faculty_id": f["faculty_id"],
					  "message": f"{f['faculty_id']} has no free day."})  # fmt: skip
	seen_b2b = set()
	for c in s.conflicts:
		t = c.get("type")
		var = c.get("var")
		if var is None:
			continue
		if t == "SECTION_ALIGNMENT" and cp.BooleanValue(var):
			v.append({"rule": "section_alignment", "message": f"Sections of {c['sections'][0].rsplit('_pair_', 1)[0]} are not in the same slot."})
		elif t == "FACULTY_B2B" and cp.BooleanValue(var):
			key = (c["faculty_id"], c["first_suffix"], c["second_suffix"])
			if key in seen_b2b:
				continue
			seen_b2b.add(key)
			v.append({"rule": "faculty_rest", "faculty_id": c["faculty_id"], "session_key": c["first_suffix"],
					  "message": f"{c['faculty_id']} teaches {c['first_suffix']} and {c['second_suffix']} back to back."})  # fmt: skip
		elif t in ("PREFERRED_THEORY_BUILDING", "PREFERRED_LAB_BUILDING") and cp.BooleanValue(var):
			v.append({"rule": "building", "session_key": c["section_id"],
					  "message": f"{c['section_id']} wanted {', '.join(c['requested_buildings'])} but is in {c['alloted_building']}."})  # fmt: skip
		elif t in ("PREFERRED_THEORY_LAYOUTS", "PREFERRED_LAB_LAYOUTS") and cp.BooleanValue(var):
			v.append({"rule": "layout", "session_key": c["section_id"],
					  "message": f"{c['section_id']} wanted layout {', '.join(c['requested_layouts'])} but got {', '.join(c['alloted_layouts'] or [])}."})  # fmt: skip
	return v


def quiet(fn, *args, **kwargs):
	"""Run an upstream function, capturing what it prints. Returns (result, output)."""
	buf = io.StringIO()
	with contextlib.redirect_stdout(buf):
		res = fn(*args, **kwargs)
	return res, buf.getvalue()
