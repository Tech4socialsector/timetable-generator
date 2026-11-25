<template>
  <span v-if="isEmpty" class="text-ink-gray-4">—</span>
  <span v-else-if="type === 'chips'" class="flex min-w-0 items-center gap-1" :title="items.join(', ')">
    <span v-for="i in items.slice(0, max)" :key="i" class="truncate rounded-md bg-surface-gray-2 px-1.5 py-0.5 text-xs text-ink-gray-8">{{ i }}</span>
    <span v-if="items.length > max" class="shrink-0 rounded-md px-1 text-xs text-ink-gray-5">+{{ items.length - max }}</span>
  </span>
  <span v-else-if="type === 'day'" class="flex items-center gap-2" :title="`${value}`">
    <span class="flex gap-0.5">
      <i v-for="(on, s) in parseDay(value, false, spd)" :key="s" class="block h-3.5 w-1.5 rounded-sm" :class="on ? 'bg-green-500' : 'bg-surface-gray-3'" />
    </span>
    <span class="truncate text-xs text-ink-gray-6">{{ value }}</span>
  </span>
  <span v-else-if="type === 'check'">
    <span v-if="value" class="lucide-check size-4 text-green-600" aria-label="Yes" />
    <span v-else class="text-ink-gray-4">—</span>
  </span>
  <span v-else-if="type === 'date'" class="tabular-nums">{{ fmtDate(value) }}</span>
  <span v-else-if="type === 'slots'" class="block truncate tabular-nums" :title="slotTitle">{{ value }}</span>
  <span v-else class="block truncate" :class="type === 'number' ? 'tabular-nums' : ''" :title="String(value)">{{ value }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { parseDay, parseInts, slotName, splitList } from '@/utils/timetable'

const props = defineProps({ value: { default: null }, type: { type: String, default: 'text' }, max: { type: Number, default: 2 }, spd: { type: Number, default: 6 }, slotTitle: { type: Function, default: null } })
const isEmpty = computed(() => props.type !== 'check' && (props.value === null || props.value === undefined || props.value === ''))
const items = computed(() => splitList(props.value))
const slotTitle = computed(() => parseInts(props.value).map((n) => (props.slotTitle ? props.slotTitle(n) : slotName(n))).join(', '))
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '')
</script>
