import { computed } from 'vue'
import { usePlan } from './usePlan'
import { DEFAULT_WEEK } from '@/utils/timetable'

// The current plan's week: teaching days, slots per day, slot labels.
export function useWeek() {
  const plan = usePlan()
  return computed(() => {
    const w = plan.overview.data?.week || DEFAULT_WEEK
    const slots = plan.overview.data?.slots || []
    const names = (w.regular_slots || []).map((i) => slots[i]?.label || `slot ${i}`)
    const regularText = `Regular slots: ${(w.regular_days || []).join(', ') || 'none'} × ${names.join(', ') || 'none'}`
    return { ...w, slots, dayFields: w.days.map((d) => d.toLowerCase()), regularText }
  })
}
