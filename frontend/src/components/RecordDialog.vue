<template>
  <SidePanel v-model:open="open" :title="title" :subtitle="subtitle" :width="wide ? '48rem' : '34rem'">
    <form :id="formId" class="space-y-6" @submit.prevent="save">
      <section v-for="g in groups" :key="g.name" class="space-y-3">
        <h3 v-if="g.name" class="text-xs font-semibold uppercase tracking-wide text-ink-gray-5">{{ g.name }}</h3>
        <div class="grid gap-4" :class="wide ? 'sm:grid-cols-2' : ''">
          <template v-for="f in g.fields" :key="f.fieldname">
            <div :class="f.full || ['availability', 'slots', 'textarea', 'tags'].includes(f.type) ? 'sm:col-span-2' : ''">
              <TextInput v-if="!f.type || ['text', 'int', 'float', 'date'].includes(f.type)" v-model="form[f.fieldname]"
                :type="f.type === 'int' || f.type === 'float' ? 'number' : f.type === 'date' ? 'date' : 'text'"
                :label="f.label" :description="f.description" :required="f.reqd" :placeholder="f.placeholder" :disabled="readonly || (f.setOnly && !isNew)" />
              <Select v-else-if="f.type === 'select'" v-model="form[f.fieldname]" class="w-full" :label="f.label" :description="f.description"
                :options="f.options" :disabled="readonly" />
              <Textarea v-else-if="f.type === 'textarea'" v-model="form[f.fieldname]" :label="f.label" :description="f.description" :rows="2" :disabled="readonly" />
              <Checkbox v-else-if="f.type === 'check'" v-model="form[f.fieldname]" :label="f.label" :description="f.description" :disabled="readonly" />
              <TagInput v-else-if="f.type === 'tags'" v-model="form[f.fieldname]" :label="f.label" :description="f.description"
                :options="typeof f.options === 'function' ? f.options() : f.options || []" :case="f.case" :disabled="readonly" />
              <SlotPicker v-else-if="f.type === 'slots'" v-model="form[f.fieldname]" :label="f.label" :days="week.days" :spd="week.slots_per_day" :slots="labels" :empty-text="f.emptyText" :disabled="readonly" />
              <div v-else-if="f.type === 'availability'" class="space-y-1">
                <div class="text-xs text-ink-gray-5">{{ f.label }}</div>
                <AvailabilityGrid v-model="availability" :days="week.days" :spd="week.slots_per_day" :slots="labels" :disabled="readonly" />
              </div>
            </div>
          </template>
        </div>
      </section>
      <ErrorMessage :message="error" />
    </form>
    <template #footer>
      <Button v-if="!isNew && !readonly" theme="red" variant="ghost" icon-left="lucide-trash-2" label="Delete" @click="remove" />
      <div class="ml-auto flex gap-2">
        <Button :label="readonly ? 'Close' : 'Cancel'" @click="open = false" />
        <Button v-if="!readonly" type="submit" :form="formId" variant="solid" :loading="saving" :label="isNew ? 'Create' : 'Save'" />
      </div>
    </template>
  </SidePanel>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Checkbox, ErrorMessage, Select, TextInput, Textarea, call, dialog, toast } from 'frappe-ui'
import SidePanel from './SidePanel.vue'
import AvailabilityGrid from './AvailabilityGrid.vue'
import SlotPicker from './SlotPicker.vue'
import TagInput from './TagInput.vue'
import { errorMessage } from '@/utils/api'
import { DAY_FIELDS } from '@/utils/timetable'
import { useWeek } from '@/composables/useWeek'

const open = defineModel('open', { type: Boolean, default: false })
const props = defineProps({
  doctype: { type: String, required: true },
  plan: { type: String, required: true },
  record: { type: Object, default: null },
  fields: { type: Array, required: true },
  defaults: { type: Object, default: () => ({}) },
  label: { type: String, default: 'record' },
  slots: { type: Array, default: () => [] },
  size: { type: String, default: '2xl' },
  wide: { type: Boolean, default: true },
  readonly: Boolean,
  subtitleFn: { type: Function, default: null },
})
const emit = defineEmits(['saved', 'deleted'])
const week = useWeek()
const labels = computed(() => (props.slots.length ? props.slots : week.value.slots))
const form = ref({})
const error = ref('')
const saving = ref(false)
const isNew = computed(() => !props.record?.name)
const title = computed(() => (isNew.value ? `New ${props.label}` : props.readonly ? props.label : `Edit ${props.label}`))
const subtitle = computed(() => (props.record && props.subtitleFn ? props.subtitleFn(props.record) : ''))
const formId = `rec-${Math.random().toString(36).slice(2)}`
const groups = computed(() => {
  const out = []
  for (const f of visibleFields.value) {
    const name = f.group || ''
    let g = out.find((x) => x.name === name)
    if (!g) out.push((g = { name, fields: [] }))
    g.fields.push(f)
  }
  return out
})
const visibleFields = computed(() => props.fields.filter((f) => !f.depends || f.depends(form.value)))
const availability = computed({
  get: () => Object.fromEntries(DAY_FIELDS.map((d) => [d, form.value[d]])),
  set: (v) => Object.assign(form.value, v),
})

watch(open, (o) => {
  if (!o) return
  error.value = ''
  const base = { ...props.defaults, ...(props.record || {}) }
  const f = {}
  for (const fd of props.fields) {
    if (fd.type === 'availability') DAY_FIELDS.forEach((d) => (f[d] = base[d] ?? 'ALL'))
    else if (fd.type === 'check') f[fd.fieldname] = !!base[fd.fieldname]
    else f[fd.fieldname] = base[fd.fieldname] ?? (fd.type === 'select' ? fd.options?.[0]?.value ?? fd.options?.[0] : '')
  }
  form.value = f
})

function payload() {
  const out = {}
  for (const [k, v] of Object.entries(form.value)) {
    const fd = props.fields.find((x) => x.fieldname === k)
    if (fd?.type === 'int') out[k] = v === '' || v == null ? 0 : parseInt(v, 10)
    else if (fd?.type === 'float') out[k] = v === '' || v == null ? 0 : parseFloat(v)
    else if (fd?.type === 'check') out[k] = v ? 1 : 0
    else if (fd?.type === 'date') out[k] = v || null
    else out[k] = v
  }
  return out
}

async function save() {
  for (const f of visibleFields.value)
    if (f.reqd && (form.value[f.fieldname] === '' || form.value[f.fieldname] == null)) {
      error.value = `${f.label} is required.`
      return
    }
  saving.value = true
  error.value = ''
  try {
    let doc
    if (isNew.value) doc = await call('frappe.client.insert', { doc: { doctype: props.doctype, plan: props.plan, ...payload() } })
    else doc = await call('frappe.client.set_value', { doctype: props.doctype, name: props.record.name, fieldname: payload() })
    toast.success(isNew.value ? `${props.label} created` : 'Saved')
    emit('saved', doc)
    open.value = false
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

function remove() {
  dialog.danger({
    title: `Delete this ${props.label}?`,
    message: 'This cannot be undone.',
    onConfirm: async () => {
      await call('frappe.client.delete', { doctype: props.doctype, name: props.record.name })
      toast.success('Deleted')
      emit('deleted', props.record)
      open.value = false
    },
  })
}
</script>
