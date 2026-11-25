<template>
  <div class="space-y-1">
    <div v-if="label" class="text-xs text-ink-gray-5">{{ label }}</div>
    <div class="overflow-x-auto">
      <table class="border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th></th>
            <th v-for="d in days" :key="d" class="px-1 font-medium text-ink-gray-6">{{ d }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in slotIdx" :key="s">
            <th class="pr-2 text-left font-normal text-ink-gray-5">{{ slots[s]?.label || `Slot ${s}` }}</th>
            <td v-for="(d, di) in days" :key="d">
              <button
                type="button"
                :disabled="disabled"
                class="h-6 w-12 rounded border"
                :class="selected.has(abs(di, s)) ? 'border-transparent bg-surface-gray-7 text-white' : 'border-outline-gray-2 hover:bg-surface-gray-2 text-ink-gray-4'"
                :aria-pressed="selected.has(abs(di, s))"
                :aria-label="`${d} ${slots[s]?.label || `slot ${s}`}`"
                @click="toggle(abs(di, s))"
              >{{ abs(di, s) }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="flex items-center gap-2 text-xs text-ink-gray-5">
      <span>{{ selected.size ? `${selected.size} selected` : emptyText }}</span>
      <button v-if="selected.size && !disabled" type="button" class="underline" @click="emit('update:modelValue', '')">Clear</button>
    </div>
    <AddSlotInline v-if="allowAdd" :disabled="disabled" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AddSlotInline from './AddSlotInline.vue'
import { DAYS, SLOTS_PER_DAY, parseInts } from '@/utils/timetable'

const props = defineProps({
  modelValue: { type: String, default: '' },
  days: { type: Array, default: () => DAYS },
  spd: { type: Number, default: SLOTS_PER_DAY },
  slots: { type: Array, default: () => [] },
  label: String,
  emptyText: { type: String, default: 'None selected' },
  disabled: Boolean,
  allowAdd: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])
const slotIdx = computed(() => [...Array(props.spd).keys()])
const abs = (d, s) => d * props.spd + s
const selected = computed(() => new Set(parseInts(props.modelValue)))
function toggle(n) {
  const s = new Set(selected.value)
  s.has(n) ? s.delete(n) : s.add(n)
  emit('update:modelValue', [...s].sort((a, b) => a - b).join(','))
}
</script>
