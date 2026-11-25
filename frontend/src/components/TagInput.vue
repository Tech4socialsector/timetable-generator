<template>
  <div class="space-y-1.5">
    <div v-if="label" class="text-xs text-ink-gray-5">{{ label }}</div>
    <div class="flex min-h-8 flex-wrap items-center gap-1 rounded bg-surface-gray-2 px-1.5 py-1 focus-within:ring-2 focus-within:ring-outline-gray-3">
      <span v-for="t in tags" :key="t" class="inline-flex items-center gap-1 rounded bg-surface-base px-1.5 py-0.5 text-sm text-ink-gray-8">
        {{ display(t) }}
        <button v-if="!disabled" type="button" class="text-ink-gray-5 hover:text-ink-gray-8" :aria-label="`Remove ${t}`" @click="remove(t)">×</button>
      </span>
      <input
        v-if="!disabled"
        v-model="query"
        :list="listId"
        class="min-w-32 flex-1 border-none bg-transparent p-0.5 text-sm focus:ring-0"
        :placeholder="tags.length ? '' : placeholder"
        @keydown.enter.prevent="add(query)"
        @keydown.,.prevent="add(query)"
        @keydown.backspace="!query && tags.length && remove(tags[tags.length - 1])"
        @change="onChange"
        @blur="add(query)"
      />
      <datalist :id="listId">
        <option v-for="o in available" :key="o.value" :value="o.value">{{ o.label }}</option>
      </datalist>
    </div>
    <p v-if="description" class="text-xs text-ink-gray-5">{{ description }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { joinList, splitList } from '@/utils/timetable'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] }, // strings or {label, value}
  label: String,
  description: String,
  placeholder: { type: String, default: 'Type and press Enter' },
  case: { type: String, default: '' }, // 'upper' | 'lower'
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const query = ref('')
const listId = `tags-${Math.random().toString(36).slice(2)}`
const opts = computed(() => props.options.map((o) => (typeof o === 'string' ? { label: o, value: o } : o)))
const tags = computed(() => splitList(props.modelValue))
const available = computed(() => opts.value.filter((o) => !tags.value.includes(o.value)))
const display = (v) => {
  const o = opts.value.find((x) => x.value === v)
  return o && o.label !== v ? `${o.label}` : v
}
const norm = (v) => (props.case === 'upper' ? v.toUpperCase() : props.case === 'lower' ? v.toLowerCase() : v)
function add(v) {
  const items = splitList(v).map(norm)
  if (items.length) emit('update:modelValue', joinList([...tags.value, ...items]))
  query.value = ''
}
function onChange() {
  if (opts.value.some((o) => o.value === query.value)) add(query.value)
}
function remove(t) {
  emit('update:modelValue', joinList(tags.value.filter((x) => x !== t)))
}
</script>
