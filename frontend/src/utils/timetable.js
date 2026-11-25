// Week helpers. Each plan defines its own week (teaching days x slots per day);
// the defaults are the original 6-day x 6-slot week.
export const ALL_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const DAY_LONG = { Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday' }
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
export const DAY_NAMES = DAYS.map((d) => DAY_LONG[d])
export const DAY_FIELDS = ALL_DAYS.map((d) => d.toLowerCase()) // availability fields on rooms / faculty
export const SLOTS_PER_DAY = 6
export const DEFAULT_WEEK = { days: DAYS, slots_per_day: SLOTS_PER_DAY, regular_days: DAYS.slice(0, 5), regular_slots: [1, 2, 3, 4], total: 36 }

export const absSlot = (day, slot, spd = SLOTS_PER_DAY) => day * spd + slot
export const fromAbs = (abs, spd = SLOTS_PER_DAY) => [Math.floor(abs / spd), abs % spd]
export const slotName = (abs, labels = [], spd = SLOTS_PER_DAY, days = DAYS) => {
  const [d, s] = fromAbs(abs, spd)
  return `${days[d] ?? `Day ${d}`} · ${labels[s]?.label || `Slot ${s}`}`
}

export function splitList(value, { upper = false, lower = false } = {}) {
  if (Array.isArray(value)) return value
  const items = String(value ?? '')
    .split(',')
    .map((v) => v.trim())
    .filter((v) => v && !['none', 'nan'].includes(v.toLowerCase()))
  if (upper) return items.map((v) => v.toUpperCase())
  if (lower) return items.map((v) => v.toLowerCase())
  return items
}

export const joinList = (items) => [...new Set(items.filter(Boolean))].join(', ')

export function parseInts(value) {
  return splitList(value)
    .map((v) => parseInt(v, 10))
    .filter((v) => !Number.isNaN(v))
}

// "ALL" | "NONE" | "1,2,4" -> boolean[spd]
export function parseDay(value, emptyMeansAll = false, spd = SLOTS_PER_DAY) {
  const v = String(value ?? '').trim().toUpperCase()
  if (v === 'ALL' || (!v && emptyMeansAll)) return Array(spd).fill(true)
  const out = Array(spd).fill(false)
  if (!v || v === 'NONE') return out
  for (const n of parseInts(v)) if (n >= 0 && n < spd) out[n] = true
  return out
}

export function formatDay(bools) {
  if (bools.every(Boolean)) return 'ALL'
  if (!bools.some(Boolean)) return 'NONE'
  return bools.map((b, i) => (b ? i : null)).filter((i) => i !== null).join(',')
}

export const countAvailable = (doc, days = DAYS, spd = SLOTS_PER_DAY) =>
  days.reduce((n, d) => n + parseDay(doc[d.toLowerCase()], false, spd).filter(Boolean).length, 0)

// Stable colour per category / programme
const PALETTE = ['blue', 'green', 'amber', 'violet', 'pink', 'teal', 'orange', 'cyan', 'red', 'gray']
export function colorFor(key) {
  let h = 0
  for (const ch of String(key || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

export const CHOICE_TYPES = [
  { value: 'NONE', label: 'None (core)', help: 'No special rules. Cohorts must not clash.' },
  { value: 'CONSTRAINED', label: 'Constrained', help: 'Same cohort, scheduled together; students take one (OT, CRX, minors).' },
  { value: 'COMPLETE', label: 'Complete', help: 'Offered to as many tagged cohorts as possible; not all need to be free.' },
  { value: 'GROUPED', label: 'Grouped', help: 'A set of courses repeated with similar grouping (PG electives).' },
  { value: 'VIRTUAL_STAFFED', label: 'Virtual staffed', help: 'Needs faculty, no room.' },
  { value: 'VIRTUAL_OPEN', label: 'Virtual open', help: 'No faculty check and no room.' },
]
export const choiceLabel = (v) => CHOICE_TYPES.find((c) => c.value === v)?.label || v

export const RULE_LABELS = {
  room_double_booked: 'Room double booked',
  faculty_double_booked: 'Faculty double booked',
  cohort_clash: 'Cohort clash',
  room_capacity: 'Room too small',
  room_type: 'Wrong room type',
  room_unavailable: 'Room unavailable',
  faculty_unavailable: 'Faculty unavailable',
  no_room: 'No room',
  unknown_room: 'Unknown room',
  same_day: 'Same section twice in a day',
  day_boundary: 'Runs past end of day',
  meeting: 'In a meeting slot',
  faculty_rest: 'Back-to-back classes',
  faculty_free_day: 'No free day',
  section_alignment: 'Sections not together',
  building: 'Not in preferred building',
  layout: 'Not in preferred layout',
}
export const ruleLabel = (r) => RULE_LABELS[r] || r

export const RUN_THEME = { Queued: 'gray', Running: 'blue', Completed: 'green', Failed: 'red', Cancelled: 'orange' }
export const APPROVAL_THEME = { Draft: 'gray', Submitted: 'blue', Approved: 'green', 'Changes Requested': 'orange', Superseded: 'gray' }

export function formatDuration(seconds) {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export const formatNumber = (n) => (n == null ? '—' : Math.round(n).toLocaleString())

// Readiness issue codes -> labels
export const ISSUE_LABELS = {
  no_room: 'No suitable room', zero_starts: 'No valid time slot', day_conflict: 'Not enough days', low_options: 'Very few time options',
  faculty_conflict: 'Faculty over-booked', faculty_overload: 'Faculty load exceeds availability', cohort_load: 'Heavy cohort load',
  no_capacity: 'No room capacity given', unknown_faculty: 'Unknown faculty', unknown_category: 'Unknown category', unknown_term: 'Unknown term',
  unknown_program: 'Unknown programme', duplicate_section: 'Duplicate section', duplicate_category: 'Duplicate category', duplicate_room: 'Duplicate room',
  duplicate_faculty: 'Duplicate faculty', no_cohorts: 'No cohorts', no_faculty: 'No faculty', no_sessions: 'No sessions', bad_room: 'Invalid room',
  bad_faculty: 'Invalid faculty', bad_choice_type: 'Invalid choice type', classroom_capacity: 'Not enough classroom slots', lab_capacity: 'Not enough lab slots',
  too_many_sessions: 'More sessions than days', inconsistent_course: 'Sections differ', empty: 'Missing data', bad_attendee_type: 'Invalid attendee type',
  bad_meeting_slots: 'Invalid meeting slots', bad_term: 'Invalid term', preflight_failed: 'Check failed',
}
export const issueLabel = (c) => ISSUE_LABELS[c] || c
