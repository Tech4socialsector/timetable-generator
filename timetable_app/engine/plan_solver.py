"""TimetableSolver with per-section room requirements.

Upstream builds one Course per course code from the first Sections row, so all
sections of a course share the first row's room capacity / lab type. Sections
of the same course often need different rooms (e.g. section 1: 50 seats,
sections 2-4: 70 seats), which led to sections being placed in rooms that are
too small. ``create_variables`` calls ``get_allowed_start_indices(section, ...)``
immediately before ``_get_feasible_locations(course, ...)`` for the same
section, so we remember the section there and apply its own requirements.
"""

from __future__ import annotations

from .solver import TimetableSolver
from .week import DEFAULT_WEEK, Week


class PlanSolver(TimetableSolver):
	def __init__(self, scenario, section_reqs: dict[str, dict] | None = None, week: Week | None = None, **kw):
		super().__init__(scenario, **kw)
		self.section_reqs = section_reqs or {}
		self.week = week or DEFAULT_WEEK
		cfg = scenario.config
		if (cfg.days_per_week, cfg.slots_per_day) != (len(self.week.days), self.week.slots_per_day):
			raise ValueError("The scenario's week does not match the plan's week structure.")
		self._current_section = None

	def get_allowed_start_indices(self, section, duration):
		self._current_section = section
		if self.week == DEFAULT_WEEK:
			return super().get_allowed_start_indices(section, duration)  # the original engine, unchanged
		return self._allowed_starts_for_week(section, duration)

	def _allowed_starts_for_week(self, section, duration):
		"""Same rules as src/solver.py, for any week structure.

		Upstream hard-codes six slots per day and the regular starts Mon-Fri slots 1-4;
		here they come from the plan's week (slots per day, regular days and slots).
		"""
		spd = self.week.slots_per_day
		cat = self.scenario.get_course_category_by_id(section.category.lower().strip())
		if section.allowed_slots:
			allowed = section.allowed_slots
		elif cat and cat.allowed_slots:
			allowed = cat.allowed_slots
		else:
			allowed = self.week.regular_starts
		allowed_set = set(allowed)

		if cat and cat.choice_type.upper() == "VIRTUAL_OPEN":
			faculty_ok = set(range(self.total_slots))
		else:
			faculty_ok = None
			for fid in section.faculty_ids:
				fac = self.faculty_map[fid]
				slots = {s.day_index * spd + s.slot_index for s in fac.available_slots}
				faculty_ok = slots if faculty_ok is None else faculty_ok & slots
			faculty_ok = faculty_ok or set()

		lunch = set(self.scenario.config.lunch_slots)
		starts = []
		for start in allowed:
			end = start + duration - 1
			if start // spd != end // spd or end not in allowed_set:
				continue
			if all((start + d) in faculty_ok and (start + d) % spd not in lunch for d in range(duration)):
				starts.append(start)
		return starts

	def feasible_locations_for(self, section, course, s_type):
		req = self.section_reqs.get(section.id) if section is not None else None
		if not req:
			return TimetableSolver._get_feasible_locations(self, course, s_type)
		cap = req.get("capacity")
		lab = req.get("lab_type")
		out = []
		for loc in self.scenario.locations:
			if s_type == "LAB":
				if loc.type in ["LAB", "EITHER"] and loc.lab_type == (lab or course.required_lab_type):
					out.append(loc)
			elif loc.type in ["CLASSROOM", "EITHER"]:
				if (loc.classroom_capacity or 0) >= (cap if cap is not None else (course.required_classroom_size or 0)):
					out.append(loc)
		return out

	def _get_feasible_locations(self, course, s_type):
		sec = self._current_section
		if sec is not None and sec.course_id != course.id:
			sec = None
		return self.feasible_locations_for(sec, course, s_type)
