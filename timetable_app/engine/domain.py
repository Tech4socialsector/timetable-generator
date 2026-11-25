"""Domain models from ``src/domain.py`` (the original engine), re-exported for the app.

Only one addition, kept here so ``src/`` stays unchanged: ``Faculty.program_ids``.
``src/solver.py`` reads ``getattr(faculty, "program_ids", [])`` to apply
FACULTY_ONLY / BOTH meeting slots to the faculty free-day rule, but the upstream
model does not declare the field, so pydantic would silently drop it.
"""

from __future__ import annotations

from typing import List

from ._upstream import load

_domain = load("domain")

Cohort = _domain.Cohort
Course = _domain.Course
CourseCategory = _domain.CourseCategory
LabType = _domain.LabType
Major = _domain.Major
Program = _domain.Program
ProgramTermMeetingSlots = _domain.ProgramTermMeetingSlots
Programme = _domain.Programme
RoomType = _domain.RoomType
Section = _domain.Section
TeachingLocation = _domain.TeachingLocation
Term = _domain.Term
TimeSlot = _domain.TimeSlot
TimetableScenario = _domain.TimetableScenario
WorkWeekConfig = _domain.WorkWeekConfig


class Faculty(_domain.Faculty):
	program_ids: List[str] = []  # noqa: UP006 - matches the upstream typing style
