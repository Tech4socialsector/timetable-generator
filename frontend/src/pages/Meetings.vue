<template>
  <PageHead title="Meetings">
    <Button v-if="canEdit" variant="solid" icon-left="lucide-plus" label="New meeting slot" @click="edit(null)" />
  </PageHead>
  <div class="tt-page space-y-4">
    <PageIntro title="Meetings" icon="lucide-calendar-clock" description="Programme meeting and seminar slots that classes should avoid." />
    <p class="max-w-3xl text-sm text-ink-gray-6">
      Programme meeting and seminar slots. The solver avoids scheduling classes of that programme in these slots (high-priority preference).
      Faculty-only and both-type meetings also count as busy days for the faculty free-day rule. Use programme <b>GLOBAL</b> for everyone.
    </p>
    <DataTable table-key="meetings" :columns="columns" :rows="rows" :loading="list.list.loading" :search-keys="['program_id', 'term_id', 'description']" @row-click="edit">
      <template #cell-meeting_slots="{ value }">
        <div class="flex flex-wrap gap-1">
          <span v-for="s in parseInts(value)" :key="s" class="rounded bg-surface-gray-2 px-1.5 py-0.5 text-xs">{{ slotName(s, slots, week.slots_per_day, week.days) }}</span>
        </div>
      </template>
      <template #cell-attendee_type="{ value }">{{ attendee[value] || value }}</template>
    </DataTable>
  </div>
  <RecordDialog v-model:open="open" doctype="TT Meeting" label="meeting slot" :plan="plan.name" :record="current" :fields="fields" :slots="slots"
    :defaults="{ term_id: 'FULL', attendee_type: 'BOTH' }" :readonly="!canEdit" @saved="saved" @deleted="saved" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Button } from 'frappe-ui'
import DataTable from '@/components/DataTable.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import RecordDialog from '@/components/RecordDialog.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { useRecords } from '@/composables/useRecords'
import { useWeek } from '@/composables/useWeek'
import { parseInts, slotName } from '@/utils/timetable'

const plan = usePlan()
const { canEdit, slots } = useEditing()
const week = useWeek()
const attendee = { STUDENT_ONLY: 'Students only', FACULTY_ONLY: 'Faculty only', BOTH: 'Students and faculty' }
const list = useRecords('TT Meeting', ['program_id', 'term_id', 'attendee_type', 'meeting_slots', 'description'], 'program_id asc')
const rows = computed(() => list.data || [])
const opt = computed(() => plan.options.data || {})
// The workbook's Meeting Slots sheet, in the same order.
const columns = [
  { key: 'program_id', label: 'Programme', width: 9, sticky: true, class: 'font-medium text-ink-gray-9' },
  { key: 'term_id', label: 'Term', width: 13 },
  { key: 'meeting_slots', label: 'Meeting slots', width: 26, sortable: false },
  { key: 'attendee_type', label: 'Attendees', width: 10 },
  { key: 'description', label: 'Description', width: 14 },
]
const fields = computed(() => [
  { fieldname: 'program_id', label: 'Programme', type: 'select', reqd: true, options: [{ label: 'GLOBAL (all programmes)', value: 'GLOBAL' }, ...(opt.value.programmes || []).map((p) => ({ label: `${p.program_name} (${p.program_id})`, value: p.program_id }))] },
  { fieldname: 'term_id', label: 'Term', type: 'select', options: [{ label: 'Full semester', value: 'FULL' }, ...(opt.value.terms || []).map((t) => ({ label: t.term_id, value: t.term_id }))] },
  { fieldname: 'attendee_type', label: 'Attendees', type: 'select', options: Object.entries(attendee).map(([value, label]) => ({ label, value })) },
  { fieldname: 'description', label: 'Description' },
  { fieldname: 'meeting_slots', label: 'Meeting slots', type: 'slots', reqd: true },
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
