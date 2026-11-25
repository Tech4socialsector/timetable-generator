"""The week structure of a plan: teaching days, slots per day and the regular slots.

Absolute slot numbers (used in allowed slots, meeting slots, solver starts) are
``day_index * slots_per_day + slot_index``, where ``day_index`` is the position of
the day in ``days``. The default reproduces the original engine: Mon-Sat, six slots,
regular teaching on Mon-Fri slots 1-4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_SLOTS_PER_DAY = 12


@dataclass(frozen=True)
class Week:
	days: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
	slots_per_day: int = 6
	regular_days: frozenset[str] = field(default_factory=lambda: frozenset({"Mon", "Tue", "Wed", "Thu", "Fri"}))
	regular_slots: frozenset[int] = field(default_factory=lambda: frozenset({1, 2, 3, 4}))

	def __post_init__(self):
		if not self.days:
			raise ValueError("A week needs at least one teaching day.")
		bad = [d for d in self.days if d not in ALL_DAYS]
		if bad or len(set(self.days)) != len(self.days):
			raise ValueError(f"Invalid or repeated days: {', '.join(bad) or ', '.join(self.days)}")
		if not 1 <= self.slots_per_day <= MAX_SLOTS_PER_DAY:
			raise ValueError(f"Slots per day must be 1 to {MAX_SLOTS_PER_DAY}.")

	@property
	def total(self) -> int:
		return len(self.days) * self.slots_per_day

	def abs(self, day_index: int, slot_index: int) -> int:
		return day_index * self.slots_per_day + slot_index

	def split(self, abs_slot: int) -> tuple[int, int]:
		return divmod(int(abs_slot), self.slots_per_day)

	def label(self, abs_slot: int) -> str:
		d, s = self.split(abs_slot)
		return f"{self.days[d]} slot {s}" if 0 <= d < len(self.days) else f"slot {abs_slot}"

	@property
	def regular_starts(self) -> list[int]:
		"""Absolute slots a session may use when no allowed slots are given."""
		return [
			self.abs(d, s)
			for d, name in enumerate(self.days)
			if name in self.regular_days
			for s in range(self.slots_per_day)
			if s in self.regular_slots
		]

	def same_day(self, a: int, b: int) -> bool:
		return a // self.slots_per_day == b // self.slots_per_day


DEFAULT_WEEK = Week()


def week_from(days, slots_per_day: int, regular_days=None, regular_slots=None) -> Week:
	"""Build a Week from loose values (lists, comma strings)."""

	def as_list(v):
		if v is None:
			return []
		if isinstance(v, str):
			return [x.strip() for x in v.split(",") if x.strip()]
		return list(v)

	day_list = [d[:3].title() for d in as_list(days)] or list(DEFAULT_WEEK.days)
	reg_days = {d[:3].title() for d in as_list(regular_days)} if regular_days is not None else set(day_list) - {"Sat", "Sun"}
	reg_slots = {int(s) for s in as_list(regular_slots)} if regular_slots is not None else set(range(int(slots_per_day)))
	return Week(tuple(day_list), int(slots_per_day), frozenset(reg_days & set(day_list)), frozenset(s for s in reg_slots if 0 <= s < int(slots_per_day)))
