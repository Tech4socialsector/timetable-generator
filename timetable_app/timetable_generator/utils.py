"""Shared validation helpers for the timetable DocTypes."""

import frappe
from frappe import _

from timetable_app.engine.scenario_builder import parse_availability, split_list
from timetable_app.engine.week import ALL_DAYS, DEFAULT_WEEK, Week, week_from

DAY_FIELDS = [d.lower() for d in ALL_DAYS]  # mon ... sun (availability fields on rooms / faculty)


def _local_dict(key: str) -> dict:
	"""A dict stored on frappe.local for the current request / job."""
	value = getattr(frappe.local, key, None)
	if value is None:
		value = {}
		setattr(frappe.local, key, value)
	return value


def plan_week(plan: str | None) -> Week:
	"""The plan's week structure (cached for the request; cleared when the plan is saved)."""
	if not plan:
		return DEFAULT_WEEK
	cache = _local_dict("tt_week_cache")
	if plan not in cache:
		row = frappe.db.get_value("TT Plan", plan, ["teaching_days", "regular_days"], as_dict=True)
		slots = frappe.get_all("TT Plan Slot", filters={"parent": plan, "parenttype": "TT Plan"}, fields=["slot_index", "regular"], order_by="slot_index asc")
		if not row or not slots:
			cache[plan] = DEFAULT_WEEK
		else:
			cache[plan] = week_from(row.teaching_days or ",".join(DEFAULT_WEEK.days), len(slots),
									row.regular_days if row.regular_days is not None else None,
									[s.slot_index for s in slots if s.regular])  # fmt: skip
	return cache[plan]


def clear_week_cache(plan: str | None = None):
	cache = _local_dict("tt_week_cache")
	if plan:
		cache.pop(plan, None)
	else:
		cache.clear()


def clean(doc, *fields):
	for f in fields:
		v = doc.get(f)
		if isinstance(v, str):
			doc.set(f, v.strip())


def ensure_unique(doc, field, label):
	"""A code must be unique within its plan."""
	if doc.flags.skip_unique:
		return
	value = doc.get(field)
	if value and frappe.db.exists(doc.doctype, {"plan": doc.plan, field: value, "name": ("!=", doc.name)}):
		frappe.throw(_("{0} '{1}' already exists in plan {2}.").format(label, value, doc.plan), frappe.DuplicateEntryError)


def validate_int_list(doc, field, label, lo=0, hi=None):
	"""Comma separated numbers within lo..hi (default: the plan's absolute slots)."""
	if hi is None:
		hi = plan_week(doc.get("plan")).total - 1
	raw = doc.get(field)
	if not raw:
		return
	try:
		vals = [int(float(v)) for v in split_list(str(raw))]
	except ValueError:
		frappe.throw(_("{0} must be comma separated numbers.").format(label))
	bad = [v for v in vals if v < lo or v > hi]
	if bad:
		frappe.throw(_("{0}: values must be between {1} and {2} (got {3}).").format(label, lo, hi, bad))
	doc.set(field, ",".join(str(v) for v in vals))


def validate_duration_list(doc, field, label):
	raw = doc.get(field)
	if not raw:
		doc.set(field, "")
		return
	try:
		vals = [int(float(v)) for v in split_list(str(raw))]
	except ValueError:
		frappe.throw(_("{0} must be comma separated numbers, e.g. 1,1 or 2.").format(label))
	spd = plan_week(doc.get("plan")).slots_per_day
	if any(v < 1 or v > spd for v in vals):
		frappe.throw(_("{0}: each session must be 1 to {1} slots long.").format(label, spd))
	doc.set(field, ",".join(str(v) for v in vals))


def validate_availability(doc):
	"""Each day: ALL, NONE or slot numbers within the plan's slots per day."""
	spd = plan_week(doc.get("plan")).slots_per_day
	for f in DAY_FIELDS:
		raw = (doc.get(f) or "").strip().upper()
		if raw in ("", "NONE"):
			doc.set(f, "NONE")
			continue
		try:
			slots = parse_availability(raw, spd)
		except ValueError:
			frappe.throw(_("{0}: use ALL, NONE or slot numbers such as 1,2,4.").format(f.title()))
		if any(s < 0 or s >= spd for s in slots):
			frappe.throw(_("{0}: slot numbers must be 0 to {1}.").format(f.title(), spd - 1))
		doc.set(f, "ALL" if len(slots) == spd else (",".join(map(str, slots)) or "NONE"))


def day_hi(doc) -> int:
	return len(plan_week(doc.get("plan")).days) - 1


def normalise_list(doc, field, upper=False, lower=False):
	items = split_list(doc.get(field) or "")
	if upper:
		items = [i.upper() for i in items]
	if lower:
		items = [i.lower() for i in items]
	doc.set(field, ", ".join(dict.fromkeys(items)))


def assert_plan_editable(doc):
	if doc.flags.ignore_plan_lock or not doc.get("plan"):
		return
	if frappe.db.get_value("TT Plan", doc.plan, "status") == "Finalised":
		frappe.throw(_("Plan {0} is finalised. Reopen it before changing its data.").format(doc.plan))
