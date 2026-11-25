<template>
  <div v-if="canAdd" class="mt-2">
    <button v-if="!open" type="button" class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-ink-gray-7 hover:bg-surface-gray-2" @click="start">
      <span class="lucide-plus size-3.5" /> Add time slot
    </button>
    <!-- not a <form>: this sits inside the record form, and nested forms would submit the record -->
    <div v-else class="space-y-3 rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-3" role="group" aria-label="Add time slot" @keydown.enter.prevent.stop="save">
      <div class="text-xs text-ink-gray-6">
        Adds a slot at the end of <b>every day</b> of this plan ({{ week.days.join(', ') }}).
        To reorder slots or change days use <router-link class="underline" :to="{ name: 'PlanSetup', params: { plan: plan.name } }">Term setup</router-link>.
      </div>
      <div class="grid gap-3 sm:grid-cols-4">
        <TextInput ref="nameInput" v-model="form.label" class="sm:col-span-2" label="Slot name" placeholder="e.g. Late evening" required />
        <TextInput v-model="form.start_time" type="time" label="Starts" />
        <TextInput v-model="form.end_time" type="time" label="Ends" />
      </div>
      <Checkbox v-model="form.regular" label="Regular teaching slot" description="Regular slots are used when a section or category does not list allowed slots." />
      <ErrorMessage :message="error" />
      <div class="flex gap-2">
        <Button variant="solid" size="sm" :loading="saving" label="Add slot" @click="save" />
        <Button size="sm" label="Cancel" @click="open = false" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import { Button, Checkbox, ErrorMessage, TextInput, call, toast } from 'frappe-ui'
import { usePlan } from '@/composables/usePlan'
import { useWeek } from '@/composables/useWeek'
import { session } from '@/session'
import { errorMessage } from '@/utils/api'

const props = defineProps({ disabled: Boolean })
const emit = defineEmits(['added'])
const plan = usePlan()
const week = useWeek()
const open = ref(false)
const saving = ref(false)
const error = ref('')
const nameInput = ref(null)
const form = reactive({ label: '', start_time: '', end_time: '', regular: false })
const canAdd = computed(() => !props.disabled && session.is_manager && plan.overview.data?.plan?.status !== 'Finalised' && week.value.slots_per_day < 12)

async function start() {
  Object.assign(form, { label: '', start_time: '', end_time: '', regular: false })
  error.value = ''
  open.value = true
  await nextTick()
  nameInput.value?.focus?.()
}
async function save() {
  if (!form.label.trim()) return (error.value = 'Give the slot a name.')
  if (form.start_time && form.end_time && form.end_time <= form.start_time) return (error.value = 'The slot ends before it starts.')
  saving.value = true
  error.value = ''
  try {
    await call('timetable_app.api.data_io.add_time_slot', { plan: plan.name, label: form.label.trim(), start_time: form.start_time || null, end_time: form.end_time || null, regular: form.regular ? 1 : 0 })
    await plan.overview.reload()
    plan.options.reload().catch(() => {})
    toast.success(`Added "${form.label.trim()}" to every day`)
    open.value = false
    emit('added')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}
</script>
