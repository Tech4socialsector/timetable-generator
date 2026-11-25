<template>
  <PageHead title="Classrooms & labs">
    <Button v-if="canEdit" variant="solid" icon-left="lucide-plus" label="New room" @click="edit(null)" />
  </PageHead>
  <div class="tt-page">
    <PageIntro title="Classrooms & labs" icon="lucide-door-open" description="Rooms shared across schools: capacity, type, layout and the slots each room can be used." />
    <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard v-for="s in summary" :key="s.label" :label="s.label" :value="s.value" :icon="s.icon" />
    </div>
    <DataTable table-key="rooms" :columns="columns" :rows="rows" :loading="list.list.loading" :search-keys="['room_id', 'room_name', 'building', 'lab_type', 'layouts']"
      search-placeholder="Search room, building, lab type, layout" :filters="filters" @row-click="edit">
      <template #cell-room_type="{ value }"><Badge size="sm" :theme="value === 'LAB' ? 'violet' : value === 'EITHER' ? 'blue' : 'gray'" :label="value" /></template>
    </DataTable>
  </div>
  <RecordDialog v-model:open="open" doctype="TT Room" label="room" :plan="plan.name" :record="current" :fields="fields" :slots="slots"
    :defaults="{ room_type: 'CLASSROOM', mon: 'ALL', tue: 'ALL', wed: 'ALL', thu: 'ALL', fri: 'ALL', sat: 'ALL', sun: 'ALL' }" :readonly="!canEdit"
    :subtitle-fn="(r) => [r.building, r.room_type, r.capacity ? `${r.capacity} seats` : ''].filter(Boolean).join(' · ')" @saved="saved" @deleted="saved" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Badge, Button } from 'frappe-ui'
import DataTable from '@/components/DataTable.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import RecordDialog from '@/components/RecordDialog.vue'
import StatCard from '@/components/StatCard.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { useRecords } from '@/composables/useRecords'
import { useWeek } from '@/composables/useWeek'
import { DAY_FIELDS } from '@/utils/timetable'

const plan = usePlan()
const { canEdit, slots } = useEditing()
const week = useWeek()
const list = useRecords('TT Room', ['room_id', 'room_name', 'building', 'room_type', 'capacity', 'lab_type', 'layouts', ...DAY_FIELDS], 'building asc, room_name asc')
const rows = computed(() => list.data || [])
const summary = computed(() => {
  const r = rows.value
  const cls = r.filter((x) => x.room_type !== 'LAB')
  return [
    { label: 'Classrooms', value: cls.length, icon: 'lucide-presentation' },
    { label: 'Labs', value: r.filter((x) => x.room_type !== 'CLASSROOM').length, icon: 'lucide-flask-conical' },
    { label: 'Total seats', value: cls.reduce((a, b) => a + (b.capacity || 0), 0).toLocaleString(), icon: 'lucide-armchair' },
    { label: 'Buildings', value: new Set(r.map((x) => x.building)).size, icon: 'lucide-building-2' },
  ]
})
// All columns of the workbook's Rooms sheet, in the same order.
const columns = computed(() => [
  { key: 'room_id', label: 'ID', width: 4.5, sticky: true, class: 'text-ink-gray-5' },
  { key: 'room_name', label: 'Name', width: 15, sticky: true, class: 'font-medium text-ink-gray-9' },
  { key: 'room_type', label: 'Type', width: 7.5, essential: true },
  { key: 'capacity', label: 'Capacity', width: 6, align: 'right', essential: true, format: (r) => (r.room_type === 'LAB' ? '' : r.capacity) },
  { key: 'layouts', label: 'Layout', width: 10, type: 'chips' },
  { key: 'lab_type', label: 'Lab type', width: 8 },
  { key: 'building', label: 'Building', width: 10, essential: true },
  ...week.value.days.map((d) => ({ key: d.toLowerCase(), label: d, width: 8.5, type: 'day', spd: week.value.slots_per_day, sortable: false })),
])
const uniq = (k) => [...new Set(rows.value.map((r) => r[k]).filter(Boolean))].sort()
const filters = computed(() => [
  { key: 'building', label: 'Building', options: uniq('building') },
  { key: 'room_type', label: 'Type', options: ['CLASSROOM', 'LAB', 'EITHER'] },
  { key: 'capacity', label: 'Seats', options: [30, 50, 70, 100].map((n) => ({ label: `${n}+ seats`, value: String(n) })), match: (r, v) => (r.capacity || 0) >= Number(v) },
])
const fields = computed(() => [
  { group: 'Room', fieldname: 'room_id', label: 'Room ID', reqd: true, setOnly: true },
  { group: 'Room', fieldname: 'room_name', label: 'Room name' },
  { group: 'Room', fieldname: 'building', label: 'Building' },
  { group: 'Room', fieldname: 'room_type', label: 'Type', type: 'select', options: [{ label: 'Classroom', value: 'CLASSROOM' }, { label: 'Lab', value: 'LAB' }, { label: 'Either', value: 'EITHER' }] },
  { group: 'Room', fieldname: 'capacity', label: 'Capacity', type: 'int', depends: (f) => f.room_type !== 'LAB' },
  { group: 'Room', fieldname: 'lab_type', label: 'Lab type', depends: (f) => f.room_type !== 'CLASSROOM' },
  { group: 'Room', fieldname: 'layouts', label: 'Layouts', type: 'tags', case: 'upper', options: () => plan.options.data?.layouts || [] },
  { group: 'Weekly availability', fieldname: 'availability', label: 'Click a slot to toggle it; click a day or slot name for the whole column or row.', type: 'availability' },
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
