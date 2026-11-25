import { createListResource } from 'frappe-ui'
import { usePlan } from './usePlan'

export function useRecords(doctype, fields, orderBy = 'creation asc') {
  const plan = usePlan()
  return createListResource({
    doctype,
    fields: ['name', ...fields],
    filters: { plan: plan.name },
    orderBy,
    pageLength: 5000,
    auto: true,
    onError: () => {},
  })
}
