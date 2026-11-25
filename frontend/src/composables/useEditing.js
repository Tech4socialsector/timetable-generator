import { computed } from 'vue'
import { usePlan } from './usePlan'
import { session } from '@/session'

// Masters are editable by managers while the plan is not finalised.
export function useEditing() {
  const plan = usePlan()
  const canEdit = computed(() => session.is_manager && plan.overview.data?.plan?.status !== 'Finalised')
  const slots = computed(() => plan.overview.data?.slots || [])
  return { canEdit, slots }
}
