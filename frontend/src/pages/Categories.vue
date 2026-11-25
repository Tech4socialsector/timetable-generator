<template>
  <PageHead title="Course categories">
    <Button v-if="canEdit" variant="solid" icon-left="lucide-plus" label="New category" @click="edit(null)" />
  </PageHead>
  <div class="tt-page space-y-4">
    <PageIntro title="Course categories" icon="lucide-tags" description="How groups of courses may be scheduled together. The choice type decides which cohort overlaps are allowed." />
    <div class="grid gap-2 sm:grid-cols-3">
      <div v-for="c in CHOICE_TYPES" :key="c.value" class="rounded-xl border border-outline-gray-2 bg-surface-base p-3 text-sm">
        <div class="flex items-center gap-2">
          <span class="font-medium text-ink-gray-8">{{ c.label }}</span>
          <span class="ml-auto tabular-nums text-ink-gray-5">{{ rows.filter((r) => r.choice_type === c.value).length }}</span>
        </div>
        <p class="mt-0.5 text-xs text-ink-gray-5">{{ c.help }}</p>
      </div>
    </div>
    <DataTable table-key="categories" :columns="columns" :rows="rows" :loading="list.list.loading" :search-keys="['category_id', 'category_name']"
      :filters="[{ key: 'choice_type', label: 'Choice type', options: CHOICE_TYPES.map((c) => ({ label: c.label, value: c.value })) }]" @row-click="edit">
      <template #cell-category_id="{ value }"><CategoryChip :id="value" /></template>
      <template #cell-choice_type="{ value }">{{ choiceLabel(value) }}</template>
      <template #cell-sections="{ row }">{{ counts[row.category_id] || 0 }}</template>
    </DataTable>
  </div>
  <RecordDialog v-model:open="open" doctype="TT Category" label="category" :plan="plan.name" :record="current" :fields="fields" :slots="slots"
    :defaults="{ choice_type: 'NONE' }" :readonly="!canEdit" @saved="saved" @deleted="saved" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Button, createListResource } from 'frappe-ui'
import CategoryChip from '@/components/CategoryChip.vue'
import DataTable from '@/components/DataTable.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import RecordDialog from '@/components/RecordDialog.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { useRecords } from '@/composables/useRecords'
import { useWeek } from '@/composables/useWeek'
import { CHOICE_TYPES, choiceLabel, slotName } from '@/utils/timetable'

const plan = usePlan()
const { canEdit, slots } = useEditing()
const week = useWeek()
const slotTitle = (n) => slotName(n, week.value.slots, week.value.slots_per_day, week.value.days)
const list = useRecords('TT Category', ['category_id', 'category_name', 'choice_type', 'choice_count', 'allowed_slots', 'allowed_days', 'preferred_slots'], 'category_id asc')
const sections = createListResource({ doctype: 'TT Section', fields: ['category'], filters: { plan: plan.name }, pageLength: 5000, auto: true, onError: () => {} })
const counts = computed(() => (sections.data || []).reduce((m, s) => ((m[s.category] = (m[s.category] || 0) + 1), m), {}))
const rows = computed(() => list.data || [])
// The workbook's Categories sheet (Name, ID, choice_type, choice_count) plus scheduling limits.
const columns = [
  { key: 'category_name', label: 'Name', width: 14, sticky: true, class: 'font-medium text-ink-gray-9' },
  { key: 'category_id', label: 'ID', width: 14, essential: true },
  { key: 'choice_type', label: 'Choice type', width: 10, essential: true },
  { key: 'choice_count', label: 'Choice count', width: 7, align: 'right', essential: true, format: (r) => r.choice_count || '' },
  { key: 'allowed_slots', label: 'Allowed slots', width: 9, type: 'slots', slotTitle },
  { key: 'allowed_days', label: 'Allowed days', width: 7 },
  { key: 'preferred_slots', label: 'Preferred slots', width: 8, type: 'slots', slotTitle },
  { key: 'sections', label: 'Sections', width: 6, align: 'right', sortable: false, essential: true },
]
const fields = computed(() => [
  { fieldname: 'category_id', label: 'Category ID', reqd: true, setOnly: true },
  { fieldname: 'category_name', label: 'Name' },
  { fieldname: 'choice_type', label: 'Choice type', type: 'select', options: CHOICE_TYPES.map((c) => ({ label: c.label, value: c.value, description: c.help })) },
  { fieldname: 'choice_count', label: 'Choice count', type: 'int', description: 'How many courses of this category a student takes (for Constrained / Grouped).' },
  { fieldname: 'allowed_slots', label: 'Allowed start slots (empty = regular weekday slots)', type: 'slots', emptyText: week.value.regularText },
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
