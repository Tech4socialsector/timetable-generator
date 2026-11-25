<template>
  <PageHead title="Term setup">
    <Button v-if="canEdit" variant="solid" label="Save" :loading="saving" :disabled="!doc" @click="save" />
  </PageHead>
  <div v-if="!doc" class="flex justify-center py-20"><Spinner class="size-6" /></div>
  <div v-else class="tt-page tt-narrow space-y-8">
    <PageIntro title="Term setup" icon="lucide-calendar-cog" description="Semester dates, the weekly slot structure, sub-terms and programmes." />
    <section class="space-y-4">
      <h2 class="font-medium text-ink-gray-8">Plan</h2>
      <div class="grid gap-4 sm:grid-cols-3">
        <TextInput :model-value="doc.plan_name" label="Plan name" disabled />
        <TextInput v-model="doc.campus" label="Campus" :disabled="!canEdit" />
        <TextInput v-model="doc.academic_year" label="Academic year" :disabled="!canEdit" />
        <TextInput v-model="doc.start_date" type="date" label="Semester starts" :disabled="!canEdit" />
        <TextInput v-model="doc.end_date" type="date" label="Semester ends" :disabled="!canEdit" />
        <TextInput v-model="doc.lunch_slots" label="Slots blocked every day" placeholder="e.g. 3" :description="`Consecutive slot numbers (0–${Math.max(0, (doc.slots?.length || 1) - 1)}) no class may use, e.g. a lunch slot.`" :disabled="!canEdit" />
      </div>
    </section>

    <section class="space-y-4">
      <div>
        <h2 class="font-medium text-ink-gray-8">Week structure</h2>
        <p class="text-sm text-ink-gray-5">
          The days and time slots of this plan's timetable. <b>Regular</b> days and slots are where sessions go by default;
          other slots (e.g. early morning, evening, Saturday) are used only by sections or categories that allow them.
        </p>
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <div>
          <div class="mb-1.5 text-xs text-ink-gray-5">Teaching days</div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="d in ALL_DAYS" :key="d" type="button" :disabled="!canEdit" class="rounded-md border px-3 py-1 text-sm transition"
              :class="days.includes(d) ? 'border-transparent bg-surface-gray-9 text-white' : 'border-outline-gray-2 text-ink-gray-6 hover:bg-surface-gray-2'"
              :aria-pressed="days.includes(d)" @click="toggleDay(d)">{{ d }}</button>
          </div>
        </div>
        <div>
          <div class="mb-1.5 text-xs text-ink-gray-5">Regular days</div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="d in days" :key="d" type="button" :disabled="!canEdit" class="rounded-md border px-3 py-1 text-sm transition"
              :class="regularDays.includes(d) ? 'border-transparent bg-green-600 text-white' : 'border-outline-gray-2 text-ink-gray-6 hover:bg-surface-gray-2'"
              :aria-pressed="regularDays.includes(d)" @click="toggleRegularDay(d)">{{ d }}</button>
          </div>
        </div>
      </div>
      <div class="overflow-x-auto rounded-xl border border-outline-gray-2 bg-surface-base">
        <table class="w-full text-sm">
          <thead class="bg-surface-gray-1 text-left text-ink-gray-6">
            <tr><th class="w-14 px-3 py-2 font-medium">Slot</th><th class="px-3 py-2 font-medium">Label</th><th class="px-3 py-2 font-medium">Starts</th><th class="px-3 py-2 font-medium">Ends</th><th class="px-3 py-2 font-medium">Regular</th><th class="w-32"></th></tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in doc.slots" :key="s.name || s._key" class="border-t border-outline-gray-1">
              <td class="px-3 py-1.5 tabular-nums text-ink-gray-6">{{ i }}</td>
              <td class="px-3 py-1.5"><TextInput v-model="s.label" :disabled="!canEdit" /></td>
              <td class="px-3 py-1.5"><TextInput v-model="s.start_time" type="time" :disabled="!canEdit" /></td>
              <td class="px-3 py-1.5"><TextInput v-model="s.end_time" type="time" :disabled="!canEdit" /></td>
              <td class="px-3 py-1.5"><Checkbox v-model="s.regular" :disabled="!canEdit" /></td>
              <td class="px-3 py-1.5">
                <div v-if="canEdit" class="flex justify-end gap-0.5">
                  <Button icon="lucide-arrow-up" label="Move up" variant="ghost" :disabled="i === 0" @click="move(i, -1)" />
                  <Button icon="lucide-arrow-down" label="Move down" variant="ghost" :disabled="i === doc.slots.length - 1" @click="move(i, 1)" />
                  <Button icon="lucide-trash-2" label="Remove slot" variant="ghost" theme="red" :disabled="doc.slots.length <= 1" @click="doc.slots.splice(i, 1)" />
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="canEdit" class="flex items-center gap-3 border-t border-outline-gray-1 px-3 py-2">
          <Button icon-left="lucide-plus" label="Add slot" :disabled="doc.slots.length >= 12" @click="addSlot" />
          <span class="text-xs text-ink-gray-5">{{ days.length }} days × {{ doc.slots.length }} slots = {{ days.length * doc.slots.length }} slots a week (up to 12 per day)</span>
        </div>
      </div>
      <Alert v-if="weekChanged" theme="amber" title="The week structure will change"
        description="Saved slot choices (allowed slots, meeting slots, availability) follow their day and slot; values on removed days or slots are dropped. Plans that already have timetable versions cannot change their week; copy the plan instead." />
    </section>

    <section class="space-y-3">
      <div class="flex items-center">
        <div>
          <h2 class="font-medium text-ink-gray-8">Terms</h2>
          <p class="text-sm text-ink-gray-5">Sub-terms within the semester (e.g. MA Development has two terms). Sections in non-overlapping terms may share slots.</p>
        </div>
        <Button v-if="canEdit" class="ml-auto" icon-left="lucide-plus" label="Add term" @click="openTerm(null)" />
      </div>
      <DataTable :columns="termCols" :rows="terms.data || []" :loading="terms.list.loading" :search-keys="['term_id']" max-height="24rem" @row-click="openTerm" />
    </section>

    <section class="space-y-3">
      <div class="flex items-center">
        <h2 class="font-medium text-ink-gray-8">Programmes</h2>
        <Button v-if="canEdit" class="ml-auto" icon-left="lucide-plus" label="Add programme" @click="openProg(null)" />
      </div>
      <DataTable :columns="progCols" :rows="progs.data || []" :loading="progs.list.loading" :search-keys="['program_id', 'program_name']" max-height="24rem" @row-click="openProg" />
    </section>
  </div>

  <RecordDialog v-model:open="termOpen" doctype="TT Term" label="term" :plan="plan.name" :record="term" size="lg" :wide="false" :readonly="!canEdit"
    :fields="[{ fieldname: 'term_id', label: 'Term ID', reqd: true, setOnly: true }, { fieldname: 'start_date', label: 'Start date', type: 'date', reqd: true }, { fieldname: 'end_date', label: 'End date', type: 'date', reqd: true }]"
    @saved="reloadAll" @deleted="reloadAll" />
  <RecordDialog v-model:open="progOpen" doctype="TT Programme" label="programme" :plan="plan.name" :record="prog" size="lg" :wide="false" :readonly="!canEdit"
    :fields="[{ fieldname: 'program_id', label: 'Programme ID', reqd: true, setOnly: true }, { fieldname: 'program_name', label: 'Name' }, { fieldname: 'school', label: 'School' }]"
    @saved="reloadAll" @deleted="reloadAll" />
</template>

<script setup>
import { computed, ref } from 'vue'
import { Alert, Button, Checkbox, Spinner, TextInput, call, toast } from 'frappe-ui'
import DataTable from '@/components/DataTable.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import RecordDialog from '@/components/RecordDialog.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { useRecords } from '@/composables/useRecords'
import { api } from '@/utils/api'
import { ALL_DAYS } from '@/utils/timetable'

const plan = usePlan()
const { canEdit } = useEditing()
const doc = ref(null)
const saving = ref(false)
const terms = useRecords('TT Term', ['term_id', 'start_date', 'end_date'], 'start_date asc')
const progs = useRecords('TT Programme', ['program_id', 'program_name', 'school'], 'program_id asc')
const termCols = [{ key: 'term_id', label: 'Term ID' }, { key: 'start_date', label: 'Starts' }, { key: 'end_date', label: 'Ends' }]
const progCols = [{ key: 'program_id', label: 'ID', width: '10rem' }, { key: 'program_name', label: 'Name' }, { key: 'school', label: 'School' }]

const days = ref([])
const regularDays = ref([])
const original = ref('')
const weekSignature = () => JSON.stringify([days.value, (doc.value?.slots || []).map((s) => s.name || s._key)])
const weekChanged = computed(() => !!doc.value && original.value !== weekSignature())
let keySeq = 0
// '6:30:00' -> '06:30' (what <input type="time"> and the server expect)
function toHHMM(t) {
  if (!t) return ''
  const [h = '', m = '00'] = String(t).split(':')
  return h === '' ? '' : `${h.padStart(2, '0')}:${m.padStart(2, '0').slice(0, 2)}`
}

async function load() {
  const d = await call('frappe.client.get', { doctype: 'TT Plan', name: plan.name })
  d.slots = (d.slots || []).map((s) => ({ ...s, regular: !!s.regular, start_time: toHHMM(s.start_time), end_time: toHHMM(s.end_time) }))
  doc.value = d
  days.value = (d.teaching_days || 'Mon,Tue,Wed,Thu,Fri,Sat').split(',').filter(Boolean)
  regularDays.value = (d.regular_days || 'Mon,Tue,Wed,Thu,Fri').split(',').filter(Boolean)
  original.value = weekSignature()
}
load()

function toggleDay(d) {
  days.value = days.value.includes(d) ? days.value.filter((x) => x !== d) : ALL_DAYS.filter((x) => x === d || days.value.includes(x))
  regularDays.value = regularDays.value.filter((x) => days.value.includes(x))
}
function toggleRegularDay(d) {
  regularDays.value = regularDays.value.includes(d) ? regularDays.value.filter((x) => x !== d) : days.value.filter((x) => x === d || regularDays.value.includes(x))
}
function move(i, step) {
  const rows = doc.value.slots
  ;[rows[i], rows[i + step]] = [rows[i + step], rows[i]]
}
function addSlot() {
  doc.value.slots.push({ _key: `new-${++keySeq}`, label: `Slot ${doc.value.slots.length}`, start_time: '', end_time: '', regular: false })
}

async function save() {
  if (!days.value.length) return toast.error('Choose at least one teaching day.')
  if (!regularDays.value.length) return toast.error('Choose at least one regular day.')
  saving.value = true
  try {
    const d = doc.value
    await api('frappe.client.set_value', {
      doctype: 'TT Plan',
      name: plan.name,
      fieldname: {
        campus: d.campus, academic_year: d.academic_year, start_date: d.start_date || null, end_date: d.end_date || null, lunch_slots: d.lunch_slots || '',
        teaching_days: days.value.join(','), regular_days: regularDays.value.join(','),
        // existing rows keep their id so the server can follow moved / removed slots
        slots: d.slots.map((s, i) => ({ ...(s.name ? { name: s.name } : {}), idx: i + 1, slot_index: i, label: s.label, start_time: s.start_time || null, end_time: s.end_time || null, regular: s.regular ? 1 : 0 })),
      },
    })
    toast.success('Saved')
    await load()
    plan.reload()
  } finally {
    saving.value = false
  }
}

const termOpen = ref(false), term = ref(null), progOpen = ref(false), prog = ref(null)
const openTerm = (r) => ((term.value = r), (termOpen.value = true))
const openProg = (r) => ((prog.value = r), (progOpen.value = true))
function reloadAll() {
  terms.reload()
  progs.reload()
  plan.reload()
}
</script>
