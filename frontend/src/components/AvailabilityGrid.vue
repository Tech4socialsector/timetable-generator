<template>
  <div class="overflow-x-auto">
    <table class="w-full border-separate border-spacing-1 text-sm">
      <thead>
        <tr>
          <th class="w-28"></th>
          <th v-for="(d, di) in days" :key="d" class="font-medium text-ink-gray-6">
            <button type="button" class="rounded px-2 py-0.5 hover:bg-surface-gray-2" :disabled="disabled" :title="`Toggle all of ${d}`" @click="toggleDay(di)">{{ d }}</button>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in slotIdx" :key="s">
          <th class="pr-2 text-left font-normal text-ink-gray-6">
            <button type="button" class="truncate rounded px-1 text-left hover:bg-surface-gray-2" :disabled="disabled" @click="toggleSlot(s)">{{ slotLabel(s) }}</button>
          </th>
          <td v-for="(d, di) in days" :key="d">
            <button
              type="button"
              :disabled="disabled"
              class="h-8 w-full rounded border text-xs transition-colors"
              :class="grid[di][s] ? 'border-transparent bg-green-600 text-white hover:bg-green-700' : 'border-outline-gray-2 bg-surface-base text-ink-gray-4 hover:bg-surface-gray-2'"
              :aria-pressed="grid[di][s]"
              :aria-label="`${d} ${slotLabel(s)}: ${grid[di][s] ? 'available' : 'unavailable'}`"
              @click="toggle(di, s)"
            >
              {{ grid[di][s] ? 'Free' : '—' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="mt-1 text-xs text-ink-gray-5">{{ total }} of {{ days.length * spd }} slots available. Click a day or slot name to toggle the whole column or row.</p>
    <AddSlotInline v-if="allowAdd" :disabled="disabled" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AddSlotInline from './AddSlotInline.vue'
import { DAYS, SLOTS_PER_DAY, formatDay, parseDay } from '@/utils/timetable'

const props = defineProps({
  modelValue: { type: Object, required: true }, // { mon: 'ALL', tue: '1,2', ... }
  days: { type: Array, default: () => DAYS },
  spd: { type: Number, default: SLOTS_PER_DAY },
  slots: { type: Array, default: () => [] }, // labels
  disabled: Boolean,
  allowAdd: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])
const slotIdx = computed(() => [...Array(props.spd).keys()])
const fields = computed(() => props.days.map((d) => d.toLowerCase()))
const grid = computed(() => fields.value.map((f) => parseDay(props.modelValue[f], false, props.spd)))
const total = computed(() => grid.value.flat().filter(Boolean).length)
const slotLabel = (s) => props.slots[s]?.label || `Slot ${s}`

function commit(g) {
  const out = { ...props.modelValue }
  fields.value.forEach((f, i) => (out[f] = formatDay(g[i])))
  emit('update:modelValue', out)
}
const copy = () => grid.value.map((r) => [...r])
function toggle(d, s) {
  const g = copy()
  g[d][s] = !g[d][s]
  commit(g)
}
function toggleDay(d) {
  const g = copy()
  const on = !g[d].every(Boolean)
  g[d] = g[d].map(() => on)
  commit(g)
}
function toggleSlot(s) {
  const g = copy()
  const on = !g.every((r) => r[s])
  g.forEach((r) => (r[s] = on))
  commit(g)
}
</script>
