<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <TabButtons v-model="level" :options="[{ label: `All (${issues.length})`, value: 'all' }, { label: `Blocking (${errors})`, value: 'error' }, { label: `Warnings (${warnings})`, value: 'warning' }]" />
      <TextInput v-model="q" type="search" placeholder="Filter messages" class="w-56" />
    </div>
    <p v-if="!issues.length" class="flex items-center gap-2 text-sm text-ink-green-7"><span class="lucide-circle-check size-4" /> {{ emptyText }}</p>
    <div v-for="g in groups" :key="g.key" class="rounded-lg border border-outline-gray-2 bg-surface-base">
      <button type="button" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" @click="toggle(g.key)">
        <span :class="g.level === 'error' ? 'lucide-circle-x text-ink-red-7' : 'lucide-triangle-alert text-ink-amber-7'" class="size-4 shrink-0" />
        <span class="font-medium text-ink-gray-8">{{ codeLabel(g.code) }}</span>
        <span class="text-ink-gray-5">{{ g.sheet }}</span>
        <Badge class="ml-auto" size="sm" :theme="g.level === 'error' ? 'red' : 'amber'" :label="g.items.length" />
        <span :class="openKeys.has(g.key) ? 'lucide-chevron-up' : 'lucide-chevron-down'" class="size-4 text-ink-gray-5" />
      </button>
      <ul v-if="openKeys.has(g.key)" class="max-h-72 overflow-y-auto border-t border-outline-gray-1 px-3 py-2 text-sm text-ink-gray-7">
        <li v-for="(i, n) in g.items" :key="n" class="py-0.5">{{ i.message }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Badge, TabButtons, TextInput } from 'frappe-ui'
import { issueLabel } from '@/utils/timetable'

const props = defineProps({ issues: { type: Array, default: () => [] }, emptyText: { type: String, default: 'No problems found.' } })
const level = ref('all')
const q = ref('')
const openKeys = ref(new Set())
const errors = computed(() => props.issues.filter((i) => i.level === 'error').length)
const warnings = computed(() => props.issues.filter((i) => i.level === 'warning').length)
const codeLabel = issueLabel
const groups = computed(() => {
  const m = new Map()
  const query = q.value.trim().toLowerCase()
  for (const i of props.issues) {
    if (level.value !== 'all' && i.level !== level.value) continue
    if (query && !i.message.toLowerCase().includes(query)) continue
    const key = `${i.level}|${i.code}`
    if (!m.has(key)) m.set(key, { key, level: i.level, code: i.code, sheet: i.sheet, items: [] })
    m.get(key).items.push(i)
  }
  return [...m.values()].sort((a, b) => (a.level === b.level ? b.items.length - a.items.length : a.level === 'error' ? -1 : 1))
})
function toggle(k) {
  const s = new Set(openKeys.value)
  s.has(k) ? s.delete(k) : s.add(k)
  openKeys.value = s
}
</script>
