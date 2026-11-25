"""Build a solver ``TimetableScenario`` from plain row dictionaries.

Rows use the same column names as the planning workbook sheets, so the exact
same parsing is applied whether the data comes from an uploaded .xlsx file or
from the Frappe DocTypes. Problems are collected as structured issues instead of
being printed / ``sys.exit``-ed, so the UI can show every problem at once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from .week import DEFAULT_WEEK, Week
from .domain import (
	Cohort,
	Course,
	CourseCategory,
	Faculty,
	Program,
	ProgramTermMeetingSlots,
	RoomType,
	Section,
	TeachingLocation,
	Term,
	TimeSlot,
	TimetableScenario,
	WorkWeekConfig,
)

# Defaults (the original 6-day x 6-slot week). Plans can define their own Week.
DAYS = list(DEFAULT_WEEK.days)
DAYS_PER_WEEK = len(DEFAULT_WEEK.days)
SLOTS_PER_DAY = DEFAULT_WEEK.slots_per_day
CHOICE_TYPES = ["NONE", "CONSTRAINED", "COMPLETE", "GROUPED", "VIRTUAL_STAFFED", "VIRTUAL_OPEN"]
VIRTUAL_TYPES = ("VIRTUAL_STAFFED", "VIRTUAL_OPEN")
ATTENDEE_TYPES = ["STUDENT_ONLY", "FACULTY_ONLY", "BOTH"]

# Category spellings seen in workbooks -> canonical solver value
_CHOICE_ALIASES = {
	"": "NONE",
	"CONSTRAINT": "CONSTRAINED",
	"VIRTUAL STAFFED": "VIRTUAL_STAFFED",
	"VIRTUAL OPEN": "VIRTUAL_OPEN",
}


# --------------------------------------------------------------------------- helpers


def text(value: Any) -> str:
	"""Normalise a cell to a stripped string ('' for empty / NaN, '3' for 3.0)."""
	if value is None:
		return ""
	if isinstance(value, float):
		if math.isnan(value):
			return ""
		if value.is_integer():
			return str(int(value))
	if isinstance(value, datetime):
		return value.date().isoformat()
	return str(value).strip()


def col(row: dict, *names: str) -> str:
	"""Return the first non-empty column among ``names`` (case-insensitive)."""
	lowered = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
	for name in names:
		value = text(lowered.get(name.lower()))
		if value:
			return value
	return ""


def split_list(value: str, upper: bool = False) -> list[str]:
	items = [v.strip() for v in str(value or "").split(",")]
	items = [v for v in items if v and v.lower() not in ("none", "nan")]
	return [v.upper() for v in items] if upper else items


def parse_ints(value: str) -> list[int]:
	return [int(float(v)) for v in split_list(value)]


def parse_optional_ints(value: str) -> list[int] | None:
	vals = parse_ints(value)
	return vals or None


def parse_availability(value: str, slots_per_day: int = SLOTS_PER_DAY) -> list[int]:
	"""'ALL' -> every slot, 'NONE'/'' -> no slot, '1,2,4' -> those slot indices."""
	tokens = [t.strip().upper() for t in str(value or "").split(",") if t.strip()]
	slots: set[int] = set()
	for t in tokens:
		if t == "ALL":
			slots.update(range(slots_per_day))
		elif t in ("NONE", "NAN"):
			continue
		else:
			slots.add(int(float(t)))
	return sorted(slots)


def parse_date(value: Any) -> date | None:
	if value in (None, ""):
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	s = text(value)
	for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
		try:
			return datetime.strptime(s, fmt).date()
		except ValueError:
			continue
	return None


def normalise_choice_type(value: str) -> str:
	v = text(value).upper().replace("-", "_")
	v = _CHOICE_ALIASES.get(v, v)
	return v.replace(" ", "_")


def section_key(course_code: str, section_number: str) -> str:
	"""Same id format the solver/exporters use: ``<course>__Section_<n>``."""
	return f"{course_code}__Section_{int(float(section_number))}"


# --------------------------------------------------------------------------- issues


@dataclass
class Issue:
	level: str  # "error" | "warning"
	code: str
	message: str
	sheet: str = ""
	ref: str = ""

	def as_dict(self) -> dict:
		return {"level": self.level, "code": self.code, "message": self.message, "sheet": self.sheet, "ref": self.ref}


@dataclass
class BuildResult:
	scenario: TimetableScenario | None
	issues: list[Issue] = field(default_factory=list)
	# section id -> {"capacity": int | None, "lab_type": str | None}, from that section's own row
	section_reqs: dict[str, dict] = field(default_factory=dict)

	@property
	def errors(self) -> list[Issue]:
		return [i for i in self.issues if i.level == "error"]

	@property
	def ok(self) -> bool:
		return self.scenario is not None and not self.errors


# --------------------------------------------------------------------------- builder


class ScenarioBuilder:
	"""``rows`` maps sheet name -> list of row dicts (column header -> value)."""

	def __init__(self, rows: dict[str, list[dict]], lunch_slots: list[int] | None = None, week: Week | None = None):
		self.week = week or DEFAULT_WEEK
		self.rows = rows
		self.issues: list[Issue] = []
		self.section_reqs: dict[str, dict] = {}
		self.config = WorkWeekConfig(
			days_per_week=len(self.week.days),
			slots_per_day=self.week.slots_per_day,
			lunch_slots=lunch_slots or [],
			meeting_slots=[],
		)

	# -- issue helpers
	def error(self, code, message, sheet="", ref=""):
		self.issues.append(Issue("error", code, message, sheet, ref))

	def warn(self, code, message, sheet="", ref=""):
		self.issues.append(Issue("warning", code, message, sheet, ref))

	def _day_slots(self, raw: str, sheet: str, ref: str, day: str) -> list[int]:
		"""Availability of one day; slot numbers beyond the plan's slots are reported."""
		slots = parse_availability(raw, self.week.slots_per_day)
		bad = [x for x in slots if not 0 <= x < self.week.slots_per_day]
		if bad:
			raise ValueError(f"{day} lists slot(s) {bad}, but the week has slots 0-{self.week.slots_per_day - 1}")
		return slots

	def _check_slots(self, values: list[int] | None, what: str, sid: str) -> bool:
		bad = [x for x in (values or []) if not 0 <= x < self.week.total]
		if bad:
			self.error("bad_slots", f"Section {sid}: {what} {bad} are outside the week (0-{self.week.total - 1}).", "Sections", sid)
			return False
		return True

	def sheet(self, name: str) -> list[dict]:
		rows = self.rows.get(name) or []
		# drop fully empty rows
		return [r for r in rows if any(text(v) for v in r.values())]

	# -- loaders
	def categories(self) -> list[CourseCategory]:
		out, seen = [], {}
		for r in self.sheet("Categories"):
			cid = col(r, "ID", "id", "category_id") or col(r, "Name")
			if not cid:
				continue
			key = cid.lower()
			choice = normalise_choice_type(col(r, "choice_type"))
			if key in seen:
				if seen[key] == choice:
					self.warn("duplicate_category", f"Category '{cid}' is listed twice; the duplicate row is ignored.", "Categories", cid)
				else:
					self.error("duplicate_category", f"Category '{cid}' is defined twice with different choice types.", "Categories", cid)
				continue
			seen[key] = choice
			if choice not in CHOICE_TYPES:
				self.error(
					"bad_choice_type",
					f"Category '{cid}' has unknown choice type '{col(r, 'choice_type')}'. "
					f"Use one of: {', '.join(CHOICE_TYPES)}.",
					"Categories",
					cid,
				)
				continue
			try:
				out.append(
					CourseCategory(
						id=cid,
						name=col(r, "Name", "name", "category_name") or cid,
						choice_type=choice,
						choice_count=int(float(col(r, "choice_count") or 0)),
						allowed_slots=parse_optional_ints(col(r, "allowed_slots")),
						allowed_days=parse_optional_ints(col(r, "allowed_days")),
						preferred_slots=parse_ints(col(r, "preferred_slot", "preferred_slots")),
					)
				)
			except (ValueError, ValidationError) as e:
				self.error("bad_category", f"Category '{cid}': {e}", "Categories", cid)
				continue
			bad = [x for x in (out[-1].allowed_slots or []) + (out[-1].preferred_slots or []) if not 0 <= x < self.week.total]
			if bad:
				self.error("bad_slots", f"Category '{cid}' uses slots {bad} outside the week (0-{self.week.total - 1}).", "Categories", cid)
				out.pop()
		return out

	def locations(self) -> list[TeachingLocation]:
		out, seen = [], set()
		for r in self.sheet("Rooms"):
			rid = col(r, "id", "room_id")
			if not rid:
				continue
			if rid in seen:
				self.error("duplicate_room", f"Room id '{rid}' is used more than once.", "Rooms", rid)
				continue
			seen.add(rid)
			rtype = col(r, "type", "room_type").upper() or "CLASSROOM"
			cap = col(r, "classroom_capacity", "capacity")
			layouts = split_list(col(r, "layouts", "room_layout"), upper=True) or None
			slots = []
			try:
				for d, day in enumerate(self.week.days):
					for s in self._day_slots(col(r, day) or "ALL", "Rooms", rid, day):
						slots.append(TimeSlot(day_index=d, slot_index=s))
				out.append(
					TeachingLocation(
						id=rid,
						name=col(r, "name", "room_name") or rid,
						building=col(r, "building").upper(),
						type=RoomType(rtype),
						classroom_capacity=int(float(cap)) if cap else None,
						lab_type=col(r, "lab_type").upper() or None,
						layouts=layouts,
						available_slots=slots,
					)
				)
			except (ValueError, ValidationError) as e:
				self.error("bad_room", f"Room '{rid}': {_short(e)}", "Rooms", rid)
		return out

	def faculty(self) -> list[Faculty]:
		out, seen = [], set()
		for r in self.sheet("Faculty"):
			fid = col(r, "id", "faculty_id").lower()
			if not fid:
				continue
			if fid in seen:
				self.error("duplicate_faculty", f"Faculty '{fid}' is listed more than once.", "Faculty", fid)
				continue
			seen.add(fid)
			try:
				slots = [
					TimeSlot(day_index=d, slot_index=s)
					for d, day in enumerate(self.week.days)
					for s in self._day_slots(col(r, day), "Faculty", fid, day)
				]
				out.append(
					Faculty(
						id=fid,
						name=col(r, "name", "faculty_name") or fid,
						available_slots=slots,
						program_ids=split_list(col(r, "program_ids", "program_id"), upper=True),
					)
				)
			except (ValueError, ValidationError) as e:
				self.error("bad_faculty", f"Faculty '{fid}': {_short(e)}", "Faculty", fid)
		return out

	def programs(self) -> list[Program]:
		out, seen = [], set()
		for r in self.sheet("Programs"):
			pid = col(r, "program_id").upper()
			if not pid or pid in seen:
				continue
			seen.add(pid)
			out.append(Program(program_id=pid, program_name=col(r, "program_name") or pid))
		return out

	def terms(self) -> list[Term]:
		out, seen = [], set()
		for r in self.sheet("Terms"):
			tid = col(r, "term_id").upper()
			if not tid:
				continue
			if tid in seen:
				self.error("duplicate_term", f"Term '{tid}' is defined more than once.", "Terms", tid)
				continue
			seen.add(tid)
			start, end = parse_date(r.get("start_date")), parse_date(r.get("end_date"))
			if not start or not end:
				self.error("bad_term", f"Term '{tid}' needs a start and end date.", "Terms", tid)
				continue
			if end < start:
				self.error("bad_term", f"Term '{tid}' ends before it starts.", "Terms", tid)
				continue
			out.append(Term(term_id=tid, start_date=start, end_date=end))
		return out

	def meeting_slots(self, programs: list[Program], terms: list[Term]) -> list[ProgramTermMeetingSlots]:
		prog_ids = {p.program_id for p in programs} | {"GLOBAL"}
		term_ids = {t.term_id for t in terms} | {"FULL"}
		out = []
		for r in self.sheet("Meeting Slots"):
			pid = col(r, "program_id").upper()
			tid = col(r, "term_id").upper() or "FULL"
			ref = f"{pid} / {tid}"
			if not pid:
				continue
			if pid not in prog_ids:
				self.error("unknown_program", f"Meeting slot refers to unknown programme '{pid}'.", "Meeting Slots", ref)
				continue
			if tid not in term_ids:
				self.error("unknown_term", f"Meeting slot refers to unknown term '{tid}'.", "Meeting Slots", ref)
				continue
			attendee = col(r, "attendee_type").upper().replace(" ", "_") or "BOTH"
			if attendee not in ATTENDEE_TYPES:
				self.error(
					"bad_attendee_type",
					f"Meeting slot {ref} has attendee type '{attendee}'. Use one of: {', '.join(ATTENDEE_TYPES)}.",
					"Meeting Slots",
					ref,
				)
				continue
			try:
				slots = parse_ints(col(r, "meeting_slots"))
			except ValueError:
				self.error("bad_meeting_slots", f"Meeting slot {ref} has invalid slot numbers.", "Meeting Slots", ref)
				continue
			bad = [s for s in slots if not 0 <= s < self.week.total]
			if bad:
				self.error("bad_meeting_slots", f"Meeting slot {ref} has out-of-range slots {bad} (0-{self.week.total - 1}).", "Meeting Slots", ref)
				continue
			out.append(ProgramTermMeetingSlots(program_id=pid, term_id=tid, attendee_type=attendee, meeting_slots=slots))
		return out

	def sections(self, faculty, categories, programs, terms):
		cat_map = {c.id.lower(): c for c in categories}
		fac_ids = {f.id for f in faculty}
		prog_ids = {p.program_id for p in programs}
		term_ids = {t.term_id for t in terms} | {"FULL"}
		courses: dict[str, Course] = {}
		sections: list[Section] = []
		cohorts: set[str] = set()
		seen_sections: set[str] = set()

		for r in self.sheet("Sections"):
			code = col(r, "course_code")
			if not code:
				continue
			num = col(r, "section_number") or "1"
			try:
				sid = section_key(code, num)
			except ValueError:
				self.error("bad_section_number", f"Course {code} has invalid section number '{num}'.", "Sections", code)
				continue
			if sid in seen_sections:
				self.error("duplicate_section", f"Section {sid} appears more than once.", "Sections", sid)
				continue
			seen_sections.add(sid)

			cat_id = col(r, "category")
			cat = cat_map.get(cat_id.lower())
			if not cat:
				self.error("unknown_category", f"Section {sid} uses unknown category '{cat_id}'.", "Sections", sid)
				continue

			fids = [f.lower() for f in split_list(col(r, "faculty_id", "faculty_ids"))]
			if cat.choice_type != "VIRTUAL_OPEN":
				if not fids:
					self.error("no_faculty", f"Section {sid} has no faculty assigned.", "Sections", sid)
					continue
				unknown = [f for f in fids if f not in fac_ids]
				if unknown:
					self.error(
						"unknown_faculty",
						f"Section {sid} uses faculty not in the Faculty list: {', '.join(unknown)}.",
						"Sections",
						sid,
					)
					continue

			cohort_raw = col(r, "required_cohorts", "cohorts")
			sec_cohorts = ["ALL"] if cohort_raw.upper() == "ALL" else split_list(cohort_raw, upper=True)
			if not sec_cohorts:
				self.warn("no_cohorts", f"Section {sid} has no cohorts, so student clashes cannot be checked.", "Sections", sid)
			cohorts.update(c for c in sec_cohorts if c != "ALL")

			pids = sorted(set(split_list(col(r, "program_ids", "program_id"), upper=True)))
			unknown_p = [p for p in pids if p not in prog_ids]
			if unknown_p and prog_ids:
				self.warn("unknown_program", f"Section {sid} lists unknown programme(s) {', '.join(unknown_p)}.", "Sections", sid)

			term_id = col(r, "term_id").upper() or "FULL"
			if term_id not in term_ids:
				self.error("unknown_term", f"Section {sid} uses unknown term '{term_id}'.", "Sections", sid)
				continue

			try:
				theory = parse_ints(col(r, "theory_durations"))
				lab = parse_ints(col(r, "lab_durations"))
				allowed_slots = parse_optional_ints(col(r, "allowed_slots"))
				allowed_days = parse_optional_ints(col(r, "allowed_days"))
				preferred = parse_ints(col(r, "preferred_slot", "preferred_slots"))
			except ValueError:
				self.error("bad_numbers", f"Section {sid} has a non-numeric duration or slot value.", "Sections", sid)
				continue
			if not (self._check_slots(allowed_slots, "allowed slots", sid) and self._check_slots(preferred, "preferred slots", sid)):
				continue
			if allowed_days and any(not 0 <= x < len(self.week.days) for x in allowed_days):
				self.error("bad_slots", f"Section {sid}: allowed days {allowed_days} are outside the week (0-{len(self.week.days) - 1}).", "Sections", sid)
				continue
			if not theory and not lab:
				self.error("no_sessions", f"Section {sid} has neither theory nor lab durations.", "Sections", sid)
				continue

			cap = col(r, "required_room_capacity")
			lab_type = col(r, "required_lab_type").upper() or None
			if code not in courses:
				try:
					courses[code] = Course(
						id=code,
						name=col(r, "course_name") or code,
						theory_durations=theory,
						lab_durations=lab,
						# virtual courses need no room; 0 keeps the solver's capacity filter happy
						required_classroom_size=int(float(cap)) if cap else (0 if cat.choice_type in VIRTUAL_TYPES or not lab_type else None),
						required_lab_type=lab_type,
						program_ids=pids,
					)
				except (ValueError, ValidationError) as e:
					self.error("bad_course", f"Course {code}: {_short(e)}", "Sections", sid)
					continue
			else:
				c = courses[code]
				if c.theory_durations != theory or c.lab_durations != lab:
					self.warn(
						"inconsistent_course",
						f"Section {sid} has different durations from section 1 of {code}; the solver uses the first row's values.",
						"Sections",
						sid,
					)

			self.section_reqs[sid] = {
				"capacity": int(float(cap)) if cap else (0 if cat.choice_type in VIRTUAL_TYPES or not lab_type else None),
				"lab_type": lab_type,
			}
			try:
				sections.append(
					Section(
						id=sid,
						course_id=code,
						category_id=cat.id,
						faculty_ids=fids,
						eligible_cohorts=sec_cohorts,
						allowed_slots=allowed_slots,
						allowed_days=allowed_days,
						preferred_slots=preferred,
						preferred_theory_buildings=split_list(col(r, "preferred_theory_buildings"), upper=True) or None,
						preferred_lab_buildings=split_list(col(r, "preferred_lab_buildings"), upper=True) or None,
						preferred_theory_layouts=split_list(col(r, "preferred_theory_layouts"), upper=True) or None,
						preferred_lab_layouts=split_list(col(r, "preferred_lab_layouts"), upper=True) or None,
						term_id=term_id,
					)
				)
			except (ValueError, ValidationError) as e:
				self.error("bad_section", f"Section {sid}: {_short(e)}", "Sections", sid)
		return list(courses.values()), sections, cohorts

	# -- capacity checks (from the original loader, now non-fatal issues)
	def check_capacity(self, locations, faculty, courses, sections, categories):
		course_map = {c.id: c for c in courses}
		cat_map = {c.id.lower(): c for c in categories}
		total = self.week.total
		n_lab = sum(1 for loc in locations if loc.type == RoomType.LAB)
		n_class = sum(1 for loc in locations if loc.type in (RoomType.CLASSROOM, RoomType.EITHER))
		need_t = need_l = 0
		for s in sections:
			cat = cat_map.get(s.category_id.lower())
			if cat and cat.choice_type in VIRTUAL_TYPES:
				continue
			c = course_map[s.course_id]
			need_t += sum(c.theory_durations)
			need_l += sum(c.lab_durations)
		if need_t > n_class * total:
			self.error("classroom_capacity", f"Sections need {need_t} classroom slots but only {n_class * total} exist.", "Rooms")
		if need_l > n_lab * total:
			self.error("lab_capacity", f"Sections need {need_l} lab slots but only {n_lab * total} exist.", "Rooms")

		for f in faculty:
			needed = sum(
				sum(course_map[s.course_id].theory_durations) + sum(course_map[s.course_id].lab_durations)
				for s in sections
				if f.id in s.faculty_ids
			)
			if needed > len(f.available_slots):
				self.error(
					"faculty_overload",
					f"{f.name} is assigned {needed} slots but is available for only {len(f.available_slots)}.",
					"Faculty",
					f.id,
				)

		for c in courses:
			n = len(c.theory_durations) + len(c.lab_durations)
			if n > len(self.week.days):
				self.error("too_many_sessions", f"{c.id} needs {n} sessions but the week has {len(self.week.days)} days.", "Sections", c.id)

	def build(self) -> BuildResult:
		categories = self.categories()
		locations = self.locations()
		faculty = self.faculty()
		programs = self.programs()
		terms = self.terms()
		meeting = self.meeting_slots(programs, terms)
		courses, sections, cohorts = self.sections(faculty, categories, programs, terms)

		for name, items in (("Categories", categories), ("Rooms", locations), ("Faculty", faculty), ("Sections", sections)):
			if not items:
				self.error("empty", f"No valid {name.lower()} found.", name)
		if not self.errors_present():
			self.check_capacity(locations, faculty, courses, sections, categories)
		if self.errors_present():
			return BuildResult(None, self.issues, self.section_reqs)

		scenario = TimetableScenario(
			config=self.config,
			cohorts=[Cohort(id=c) for c in sorted(cohorts)],
			faculty=faculty,
			locations=locations,
			courses=courses,
			sections=sections,
			programs=programs,
			course_categories=categories,
			terms=terms,
			program_term_meeting_slots=meeting,
		)
		return BuildResult(scenario, self.issues, self.section_reqs)

	def errors_present(self) -> bool:
		return any(i.level == "error" for i in self.issues)


def _short(e: Exception) -> str:
	if isinstance(e, ValidationError):
		return "; ".join(err.get("msg", "") for err in e.errors())
	return str(e)
