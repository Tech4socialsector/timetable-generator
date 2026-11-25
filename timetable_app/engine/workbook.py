"""Read / write planning workbooks (.xlsx) as plain row dictionaries."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import IO

import openpyxl

from .scenario_builder import text

# Canonical input sheets and their columns (also used for the download template).
INPUT_SHEETS: dict[str, list[str]] = {
	"Programs": ["program_id", "program_name"],
	"Terms": ["term_id", "start_date", "end_date"],
	"Categories": ["Name", "ID", "choice_type", "choice_count", "allowed_slots", "allowed_days", "preferred_slot"],
	"Rooms": ["id", "name", "type", "classroom_capacity", "room_layout", "lab_type", "building", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
	"Faculty": ["id", "name", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "program_id", "Evening?", "Remarks"],
	"Meeting Slots": ["program_id", "term_id", "meeting_slots", "attendee_type"],
	"Sections": [
		"SI no", "course_code", "section_number", "course_name", "category", "faculty_id", "theory_durations", "lab_durations",
		"required_room_capacity", "preferred_theory_layouts", "preferred_theory_buildings", "required_lab_type",
		"required_cohorts", "optional_cohorts", "allowed_slots", "allowed_days", "preferred_slot", "program_ids", "term_id",
		"Start date", "End date", "preferred_lab_buildings", "preferred_lab_layouts", "school", "Remarks", "Credits", "Group",
	],
}  # fmt: skip


def read_workbook(source: str | bytes | IO[bytes]) -> dict[str, list[dict]]:
	"""Return {sheet name: [row dict]} for every known input sheet that exists.

	Sheet names are matched case-insensitively. Header cells become dict keys.
	"""
	if isinstance(source, bytes):
		source = io.BytesIO(source)
	wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
	try:
		by_lower = {ws.title.strip().lower(): ws for ws in wb.worksheets}
		out: dict[str, list[dict]] = {}
		for sheet in INPUT_SHEETS:
			ws = by_lower.get(sheet.lower())
			if ws is None:
				continue
			rows = ws.iter_rows(values_only=True)
			header = next(rows, None)
			if not header:
				out[sheet] = []
				continue
			keys = [text(h) for h in header]
			data = []
			for values in rows:
				row = {k: v for k, v in zip(keys, values) if k}
				if any(text(v) for v in row.values()):
					data.append(row)
			out[sheet] = data
		return out
	finally:
		wb.close()


def write_workbook(sheets: dict[str, tuple[list[str], list[list]]]) -> bytes:
	"""sheets: {name: (header, rows)} -> xlsx bytes."""
	wb = openpyxl.Workbook()
	wb.remove(wb.active)
	for name, (header, rows) in sheets.items():
		ws = wb.create_sheet(title=name[:31])
		ws.append(header)
		for r in rows:
			ws.append([_cell(v) for v in r])
		for i, h in enumerate(header, start=1):
			ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = max(10, min(45, len(str(h)) + 4))
		ws.freeze_panes = "A2"
	buf = io.BytesIO()
	wb.save(buf)
	return buf.getvalue()


def _cell(v):
	if isinstance(v, (list, tuple, set)):
		return ", ".join(str(x) for x in v)
	if isinstance(v, (datetime, date)) or v is None or isinstance(v, (int, float)):
		return v
	return str(v)
