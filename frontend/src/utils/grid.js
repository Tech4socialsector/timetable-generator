import { DAYS, SLOTS_PER_DAY } from './timetable'

// Which entries belong to a view (cohort / faculty / room / programme / category / all)
export function filterEntries(entries, view, value, term) {
  return entries.filter((e) => {
    if (term && term !== 'ALL' && e.term_id !== term) return false
    if (!value || view === 'all') return true
    switch (view) {
      case 'cohort':
        return e.cohorts.includes(value) || e.cohorts.includes('ALL')
      case 'faculty':
        return e.faculty_ids.includes(value)
      case 'room':
        return e.room_id === value
      case 'programme':
        return e.program_ids.includes(value)
      case 'category':
        return e.category === value
      case 'section':
        return e.section_key === value
      default:
        return true
    }
  })
}

// cells[day][slot] -> entries occupying that cell (a 2-slot session appears in both cells)
export function buildCells(entries, nDays = DAYS.length, spd = SLOTS_PER_DAY) {
  const cells = Array.from({ length: nDays }, () => Array.from({ length: spd }, () => []))
  for (const e of entries) {
    if (e.day_index < 0 || e.day_index >= nDays) continue
    for (let k = 0; k < (e.duration || 1); k++) {
      const s = e.slot_index + k
      if (s < spd) cells[e.day_index][s].push({ ...e, continued: k > 0 })
    }
  }
  return cells
}

// name -> list of hard issues mentioning that entry
export function issuesByEntry(checks) {
  const map = {}
  for (const c of checks || []) for (const n of c.entries || []) (map[n] ||= []).push(c)
  return map
}

export function sessionLabel(e) {
  const sec = e.section_key?.split('__Section_')[1]
  return `${e.course_code}${sec ? ` · S${sec}` : ''}${e.session_type === 'LAB' ? ' · Lab' : ''}`
}
