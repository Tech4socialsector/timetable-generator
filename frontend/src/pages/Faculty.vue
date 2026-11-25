<template>
  <PageHead title="Faculty availability">
    <Button v-if="canEdit" variant="solid" icon-left="lucide-plus" label="New faculty" @click="edit(null)" />
  </PageHead>
  <div class="tt-page">
    <PageIntro title="Faculty availability" icon="lucide-users" description="When each faculty member can teach, and how their teaching load compares with the slots they are free." />
    <DataTable table-key="faculty" :columns="columns" :rows="rows" :loading="list.list.loading" :search-keys="['faculty_id', 'faculty_name', 'program_ids', 'remarks']"
      search-placeholder="Search name, email, programme" :filters="filters" @row-click="edit">
      <template #cell-load="{ row }">
        <span class="inline-flex items-center gap-1.5" :title="`${load(row)} teaching slots of ${available(row)} free`">
          <span class="h-1.5 w-12 overflow-hidden rounded-full bg-surface-gray-3"><i class="block h-full rounded-full" :class="load(row) > available(row) ? 'bg-red-500' : 'bg-green-500'" :style="{ width: `${Math.min(100, available(row) ? (100 * load(row)) / available(row) : load(row) ? 100 : 0)}%` }" /></span>
          <span :class="load(row) > available(row) ? 'font-semibold text-red-700' : 'text-ink-gray-7'">{{ load(row) }}/{{ available(row) }}</span>
        </span>
      </template>
    </DataTable>
  </div>
  <RecordDialog v-model:open="open" doctype="TT Faculty" label="faculty member" :plan="plan.name" :record="current" :fields="fields"
    :slots="slots" :defaults="newDefaults" :readonly="!canEdit"
    :subtitle-fn="(r) => `${r.faculty_id} · ${load(r)} teaching slots, ${available(r)} free`" @saved="saved" @deleted="saved" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Button, createListResource } from 'frappe-ui'
import DataTable from '@/components/DataTable.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import RecordDialog from '@/components/RecordDialog.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { useRecords } from '@/composables/useRecords'
import { useWeek } from '@/composables/useWeek'
import { DAY_FIELDS, countAvailable, splitList } from '@/utils/timetable'

const plan = usePlan()
const { canEdit, slots } = useEditing()
const week = useWeek()
const newDefaults = computed(() => Object.fromEntries(DAY_FIELDS.map((f) => [f, week.value.dayFields.includes(f) ? 'ALL' : 'NONE'])))
const list = useRecords('TT Faculty', ['faculty_id', 'faculty_name', 'program_ids', 'evening', 'remarks', 'user', ...DAY_FIELDS], 'faculty_name asc')
// teaching load: slots per week from the sections
const sections = createListResource({ doctype: 'TT Section', fields: ['faculty_ids', 'theory_durations', 'lab_durations'], filters: { plan: plan.name }, pageLength: 5000, auto: true, onError: () => {} })
const loadMap = computed(() => {
  const m = {}
  for (const s of sections.data || []) {
    const n = [...splitList(s.theory_durations), ...splitList(s.lab_durations)].reduce((a, b) => a + (parseInt(b, 10) || 0), 0)
    for (const f of splitList(s.faculty_ids, { lower: true })) m[f] = (m[f] || 0) + n
  }
  return m
})
const load = (r) => loadMap.value[r.faculty_id] || 0
const available = (r) => countAvailable(r, week.value.days, week.value.slots_per_day)
const rows = computed(() => list.data || [])
// All columns of the workbook's Faculty sheet, in the same order, plus the teaching load.
const columns = computed(() => [
  { key: 'faculty_name', label: 'Name', width: 13, sticky: true, class: 'font-medium text-ink-gray-9' },
  { key: 'faculty_id', label: 'Email (id)', width: 16, class: 'text-ink-gray-6', essential: true },
  ...week.value.days.map((d) => ({ key: d.toLowerCase(), label: d, width: 8.5, type: 'day', spd: week.value.slots_per_day, essential: true, sortable: false })),
  { key: 'program_ids', label: 'Programmes', width: 8, type: 'chips', essential: true },
  { key: 'evening', label: 'Evening?', width: 5.5, type: 'check' },
  { key: 'remarks', label: 'Remarks', width: 14 },
  { key: 'load', label: 'Load / free', width: 8.5, sortable: false, essential: true },
])
const filters = computed(() => [
  { key: 'program_ids', label: 'Programme', options: [...new Set(rows.value.flatMap((r) => splitList(r.program_ids)))].sort(), match: (r, v) => splitList(r.program_ids).includes(v) },
  { key: '_over', label: 'Load', options: [{ label: 'Over-assigned', value: 'over' }, { label: 'Not teaching', value: 'none' }],
    match: (r, v) => (v === 'over' ? load(r) > available(r) : load(r) === 0) },
])
const fields = computed(() => [
  { group: 'Faculty member', fieldname: 'faculty_id', label: 'Faculty ID (email)', reqd: true, setOnly: true },
  { group: 'Faculty member', fieldname: 'faculty_name', label: 'Name' },
  { group: 'Faculty member', fieldname: 'program_ids', label: 'Programmes', type: 'tags', case: 'upper', options: () => (plan.options.data?.programmes || []).map((p) => ({ label: p.program_name, value: p.program_id })), description: 'Used to apply programme meeting slots to the faculty free-day rule.' },
  { group: 'Faculty member', fieldname: 'evening', label: 'Can teach evening classes', type: 'check' },
  { group: 'Weekly availability', fieldname: 'availability', label: 'Click a slot to toggle it; click a day or slot name for the whole column or row.', type: 'availability' },
  { group: 'Notes', fieldname: 'remarks', label: 'Remarks', type: 'textarea' },
])
const open = ref(false)
const current = ref(null)
function edit(row) {
  current.value = row
  open.value = true
}
function saved() {
  list.reload()
  plan.reload()
}
</script>
