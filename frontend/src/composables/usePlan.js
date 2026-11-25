import { inject, provide, reactive } from 'vue'
import { createResource } from 'frappe-ui'

const KEY = Symbol('plan')

export function providePlan(planRef) {
  const overview = createResource({
    url: 'timetable_app.api.session.get_overview',
    makeParams: () => ({ plan: planRef.value }),
    onError: () => {},
  })
  const options = createResource({
    url: 'timetable_app.api.data_io.get_options',
    makeParams: () => ({ plan: planRef.value }),
    onError: () => {},
  })
  const ctx = reactive({
    name: planRef,
    overview,
    options,
    reload() {
      overview.reload().catch(() => {})
      options.reload().catch(() => {})
    },
  })
  provide(KEY, ctx)
  return ctx
}

export function usePlan() {
  const ctx = inject(KEY)
  if (!ctx) throw new Error('usePlan() used outside PlanLayout')
  return ctx
}
