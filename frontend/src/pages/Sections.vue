<template>
  <PageHead title="Course list">
    <Button icon-left="lucide-download" label="Export" @click="download('timetable_app.api.data_io.export_inputs', { plan: plan.name })" />
    <Button v-if="canEdit" variant="solid" icon-left="lucide-plus" label="New section" @click="edit(null)" />
  </PageHead>
  <div class="tt-page">
    <PageIntro title="Course list" icon="lucide-book-open" description="Every section to schedule: course, category, faculty, cohorts and the sessions it needs each week. Click a row to edit." />
    <DataTable table-key="sections" :columns="columns" :rows="rows" :loading="list.list.loading"
      :search-keys="['serial_no', 'course_code', 'course_name', 'faculty_ids', 'required_cohorts', 'optional_cohorts', 'category', 'school', 'remarks']"
      search-placeholder="Search code, course, faculty, cohort, school" :filters="filters" @row-click="edit">
      <template #cell-category="{ value }"><CategoryChip v-if="value" :id="value" /></template>
    </DataTable>
  </div>
  <RecordDialog v-model:open="open" doctype="TT Section" label="section" :plan="plan.name" :record="current" :fields="fields"
    :slots="slots" :defaults="{ section_number: 1, term_id: 'FULL' }" :readonly="!canEdit"
    :subtitle-fn="(r) => `${r.course_name || ''} · section ${r.section_number}`" @saved="saved" @deleted="saved" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Button } from 'frappe-ui'
import CategoryChip from '@/components/CategoryChip.vue'
import DataTable from '@/components/DataTable.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import RecordDialog from '@/components/RecordDialog.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { useRecords } from '@/composables/useRecords'
import { useWeek } from '@/composables/useWeek'
import { download } from '@/utils/api'
import { slotName, splitList } from '@/utils/timetable'

const plan = usePlan()
const { canEdit, slots } = useEditing()
const week = useWeek()
const slotTitle = (n) => slotName(n, week.value.slots, week.value.slots_per_day, week.value.days)
const F = ['serial_no', 'course_code', 'section_number', 'course_name', 'category', 'faculty_ids', 'theory_durations', 'lab_durations', 'required_room_capacity',
  'required_lab_type', 'required_cohorts', 'optional_cohorts', 'allowed_slots', 'allowed_days', 'preferred_slot', 'program_ids', 'term_id',
  'start_date', 'end_date', 'preferred_theory_buildings', 'preferred_theory_layouts', 'preferred_lab_buildings', 'preferred_lab_layouts',
  'school', 'credits', 'group_name', 'remarks']
const list = useRecords('TT Section', F, 'course_code asc, section_number asc')
const rows = computed(() => list.data || [])
const opt = computed(() => plan.options.data || {})
// All columns of the workbook's Sections sheet, in the same order. The first four stay pinned.
const columns = [
  { key: 'serial_no', label: 'SI no', width: 4.5, sticky: true, class: 'text-ink-gray-5' },
  { key: 'course_code', label: 'Code', width: 7.5, sticky: true, class: 'font-medium text-ink-gray-9' },
  { key: 'section_number', label: 'Sec', width: 4.5, sticky: true, align: 'right' },
  { key: 'course_name', label: 'Course', width: 16, sticky: true },
  { key: 'category', label: 'Category', width: 12, essential: true },
  { key: 'faculty_ids', label: 'Faculty', width: 15, type: 'chips', essential: true },
  { key: 'theory_durations', label: 'Theory', width: 5.5, essential: true },
  { key: 'lab_durations', label: 'Lab', width: 4.5, essential: true },
  { key: 'required_room_capacity', label: 'Seats', width: 5, align: 'right', essential: true, format: (r) => r.required_room_capacity || '' },
  { key: 'preferred_theory_layouts', label: 'Theory layouts', width: 10, type: 'chips' },
  { key: 'preferred_theory_buildings', label: 'Theory buildings', width: 10, type: 'chips' },
  { key: 'required_lab_type', label: 'Lab type', width: 8 },
  { key: 'required_cohorts', label: 'Cohorts', width: 12, type: 'chips', essential: true },
  { key: 'allowed_slots', label: 'Allowed slots', width: 8, type: 'slots', slotTitle },
  { key: 'program_ids', label: 'Programmes', width: 9, type: 'chips', essential: true },
  { key: 'term_id', label: 'Term', width: 12, essential: true },
  { key: 'start_date', label: 'Start date', width: 7.5, type: 'date' },
  { key: 'end_date', label: 'End date', width: 7.5, type: 'date' },
  { key: 'preferred_lab_buildings', label: 'Lab buildings', width: 9, type: 'chips' },
  { key: 'preferred_lab_layouts', label: 'Lab layouts', width: 9, type: 'chips' },
  { key: 'optional_cohorts', label: 'Optional cohorts', width: 11, type: 'chips' },
  { key: 'school', label: 'School', width: 6.5 },
  { key: 'remarks', label: 'Remarks', width: 14 },
  { key: 'credits', label: 'Credits', width: 5, align: 'right', format: (r) => r.credits || '' },
  { key: 'group_name', label: 'Group', width: 7 },
]
const uniq = (k) => [...new Set(rows.value.flatMap((r) => splitList(r[k])))].sort()
const filters = computed(() => [
  { key: 'category', label: 'Category', options: uniq('category') },
  { key: 'program_ids', label: 'Programme', options: uniq('program_ids'), match: (r, v) => splitList(r.program_ids).includes(v) },
  { key: 'term_id', label: 'Term', options: uniq('term_id') },
  { key: 'school', label: 'School', options: uniq('school') },
])
const fields = computed(() => [
  { group: 'Course', fieldname: 'course_code', label: 'Course code', reqd: true },
  { group: 'Course', fieldname: 'section_number', label: 'Section number', type: 'int', reqd: true },
  { group: 'Course', fieldname: 'course_name', label: 'Course name', full: true },
  { group: 'Course', fieldname: 'category', label: 'Category', type: 'select', reqd: true, options: (opt.value.categories || []).map((c) => ({ label: `${c.category_name} (${c.choice_type})`, value: c.category_id })) },
  { group: 'Course', fieldname: 'term_id', label: 'Term', type: 'select', options: [{ label: 'Full semester', value: 'FULL' }, ...(opt.value.terms || []).map((t) => ({ label: t.term_id, value: t.term_id }))] },
  { group: 'Course', fieldname: 'program_ids', label: 'Programmes', type: 'tags', case: 'upper', options: () => (opt.value.programmes || []).map((p) => ({ label: p.program_name, value: p.program_id })) },
  { group: 'Course', fieldname: 'school', label: 'School' },
  { group: 'Course', fieldname: 'credits', label: 'Credits', type: 'float' },
  { group: 'Course', fieldname: 'group_name', label: 'Group' },
  { group: 'Course', fieldname: 'serial_no', label: 'SI no', description: 'Row reference from the workbook.' },
  { group: 'Teaching', fieldname: 'faculty_ids', label: 'Faculty', type: 'tags', case: 'lower', options: () => (opt.value.faculty || []).map((f) => ({ label: `${f.faculty_name} (${f.faculty_id})`, value: f.faculty_id })) },
  { group: 'Teaching', fieldname: 'required_cohorts', label: 'Cohorts', type: 'tags', case: 'upper', options: () => opt.value.cohorts || [], description: 'Student groups that must not clash. Use ALL for every cohort.' },
  { group: 'Teaching', fieldname: 'optional_cohorts', label: 'Optional cohorts', type: 'tags', case: 'upper', options: () => opt.value.cohorts || [] },
  { group: 'Teaching', fieldname: 'theory_durations', label: 'Theory sessions', placeholder: '1,1', description: 'Slots per session; 1,1 = two one-slot sessions, 2 = one double session.' },
  { group: 'Teaching', fieldname: 'lab_durations', label: 'Lab sessions', placeholder: 'e.g. 2' },
  { group: 'Teaching', fieldname: 'required_room_capacity', label: 'Room capacity', type: 'int' },
  { group: 'Teaching', fieldname: 'required_lab_type', label: 'Lab type', type: 'select', options: [{ label: 'None', value: '' }, ...(opt.value.lab_types || []).map((l) => ({ label: l, value: l }))] },
  { group: 'Room & schedule preferences', fieldname: 'preferred_theory_buildings', label: 'Preferred buildings (theory)', type: 'tags', case: 'upper', options: () => opt.value.buildings || [] },
  { group: 'Room & schedule preferences', fieldname: 'preferred_theory_layouts', label: 'Preferred layouts (theory)', type: 'tags', case: 'upper', options: () => opt.value.layouts || [] },
  { group: 'Room & schedule preferences', fieldname: 'preferred_lab_buildings', label: 'Preferred buildings (lab)', type: 'tags', case: 'upper', options: () => opt.value.buildings || [] },
  { group: 'Room & schedule preferences', fieldname: 'preferred_lab_layouts', label: 'Preferred layouts (lab)', type: 'tags', case: 'upper', options: () => opt.value.layouts || [] },
  { group: 'Room & schedule preferences', fieldname: 'allowed_slots', label: 'Allowed start slots (leave empty for the regular weekday slots)', type: 'slots', emptyText: week.value.regularText },
  { group: 'Dates & notes', fieldname: 'start_date', label: 'Start date', type: 'date' },
  { group: 'Dates & notes', fieldname: 'end_date', label: 'End date', type: 'date' },
  { group: 'Dates & notes', fieldname: 'remarks', label: 'Remarks', type: 'textarea' },
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
