<template>
  <PageHead title="Rules & preferences">
    <Button v-if="canEdit" variant="solid" label="Save" :loading="saving" :disabled="!form" @click="save" />
  </PageHead>
  <div v-if="!form" class="flex justify-center py-20"><Spinner class="size-6" /></div>
  <div v-else class="tt-page tt-narrow space-y-8">
    <PageIntro title="Rules & preferences" icon="lucide-sliders-horizontal" description="Hard rules are always enforced. Preferences are weighed against each other; raise a weight to make it matter more." />
    <section class="space-y-3">
      <h2 class="font-medium text-ink-gray-8">Hard constraints <span class="font-normal text-ink-gray-5">(always enforced)</span></h2>
      <ul class="grid gap-x-6 gap-y-1.5 text-sm text-ink-gray-7 sm:grid-cols-2">
        <li v-for="h in HARD" :key="h" class="flex gap-2"><span class="lucide-lock mt-0.5 size-3.5 shrink-0 text-ink-gray-5" />{{ h }}</li>
      </ul>
      <Switch v-model="form.cross_term_overlap" :disabled="!canEdit" label="Prevent double booking across overlapping terms"
        description="Recommended. Without it, rooms and faculty can be double booked between different terms whose dates overlap (the original engine's behaviour)." />
    </section>

    <section class="space-y-4">
      <div class="flex flex-wrap items-center gap-3">
        <div>
          <h2 class="font-medium text-ink-gray-8">Preferences <span class="font-normal text-ink-gray-5">(soft constraints)</span></h2>
          <p class="text-sm text-ink-gray-5">How hard the solver tries to honour each preference. 100 is the standard weight; 0 ignores it.</p>
        </div>
        <TabButtons class="ml-auto" :model-value="preset" :options="Object.entries(PRESETS).map(([value, p]) => ({ label: p.label, value }))" @update:model-value="applyPreset" />
      </div>
      <div class="divide-y divide-outline-gray-1 rounded-xl border border-outline-gray-2 bg-surface-base">
        <div v-for="r in RULES" :key="r.field" class="grid items-center gap-3 p-4 sm:grid-cols-[1fr_16rem_3.5rem]">
          <div>
            <div class="text-sm font-medium text-ink-gray-8">{{ r.label }}</div>
            <div class="text-xs text-ink-gray-5">{{ r.help }}</div>
          </div>
          <Slider :model-value="[form[r.field]]" :min="0" :max="300" :step="10" :disabled="!canEdit" @update:model-value="(v) => (form[r.field] = v[0])" />
          <div class="text-right text-sm tabular-nums" :class="form[r.field] === 100 ? 'text-ink-gray-5' : 'font-medium text-ink-gray-9'">{{ form[r.field] }}</div>
        </div>
      </div>
    </section>

    <section class="space-y-3">
      <h2 class="font-medium text-ink-gray-8">Solver</h2>
      <div class="grid gap-4 sm:grid-cols-2">
        <TextInput v-model.number="form.time_limit" type="number" label="Time limit (minutes)" :disabled="!canEdit"
          description="Large plans need 30–90 minutes to find a good timetable. The best timetable found so far is kept." />
        <TextInput v-model.number="form.num_workers" type="number" label="Solver threads" :disabled="!canEdit" description="CPU cores used while generating (1–64)." />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Button, Slider, Spinner, Switch, TabButtons, TextInput, call, toast } from 'frappe-ui'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { api } from '@/utils/api'

const plan = usePlan()
const { canEdit } = useEditing()
const HARD = [
  'No room double booking', 'No student (cohort) clash', 'Room capacity fits the section', 'Faculty only when available',
  'Multiple sessions of a section on different days', 'Right room type (classroom / lab)', 'Rooms only when available',
  'Only regular slots unless a section or category allows others',
]
const RULES = [
  { field: 'w_meeting', label: 'Keep meeting slots free', help: 'Avoid classes in programme meeting slots (highest priority).' },
  { field: 'w_faculty_rest', label: 'Faculty rest', help: 'No back-to-back classes for a faculty member.' },
  { field: 'w_faculty_free_day', label: 'Faculty free day', help: 'At least one day per week without classes or meetings.' },
  { field: 'w_session_gap', label: 'Gap between sessions', help: 'Sessions of a section more than a day apart (Mon–Wed, Tue–Thu).' },
  { field: 'w_balance', label: 'Balanced week', help: 'Avoid days without classes for a cohort.' },
  { field: 'w_building', label: 'Preferred building', help: 'Use the section’s preferred building.' },
  { field: 'w_layout', label: 'Preferred room layout', help: 'Use a room with the requested layout.' },
]
const PRESETS = {
  balanced: { label: 'Standard', w: { w_meeting: 100, w_faculty_rest: 100, w_faculty_free_day: 100, w_session_gap: 100, w_balance: 100, w_building: 100, w_layout: 100 } },
  faculty: { label: 'Faculty-friendly', w: { w_meeting: 100, w_faculty_rest: 200, w_faculty_free_day: 200, w_session_gap: 100, w_balance: 60, w_building: 100, w_layout: 100 } },
  student: { label: 'Student-friendly', w: { w_meeting: 100, w_faculty_rest: 60, w_faculty_free_day: 60, w_session_gap: 150, w_balance: 200, w_building: 80, w_layout: 80 } },
}
const form = ref(null)
const saving = ref(false)
const preset = computed(() => {
  if (!form.value) return null
  return Object.keys(PRESETS).find((k) => Object.entries(PRESETS[k].w).every(([f, v]) => form.value[f] === v)) || null
})
function applyPreset(k) {
  if (canEdit.value) Object.assign(form.value, PRESETS[k].w)
}
async function load() {
  const d = await call('frappe.client.get', { doctype: 'TT Plan', name: plan.name })
  form.value = Object.fromEntries([...RULES.map((r) => [r.field, d[r.field] ?? 100]), ['time_limit', d.time_limit], ['num_workers', d.num_workers], ['cross_term_overlap', !!d.cross_term_overlap]])
}
load()
async function save() {
  saving.value = true
  try {
    await api('frappe.client.set_value', { doctype: 'TT Plan', name: plan.name, fieldname: { ...form.value, cross_term_overlap: form.value.cross_term_overlap ? 1 : 0 } })
    toast.success('Rules saved')
    plan.reload()
  } finally {
    saving.value = false
  }
}
</script>
