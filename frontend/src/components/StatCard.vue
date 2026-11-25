<template>
  <component :is="to ? 'router-link' : 'div'" :to="to"
    class="group flex flex-col gap-2 rounded-xl border bg-surface-base p-4 transition"
    :class="[toneBorder, to ? 'hover:-translate-y-px hover:shadow-md' : '']">
    <div class="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-gray-5">
      <span v-if="icon" class="flex size-6 items-center justify-center rounded-md" :class="toneBg"><span :class="icon" class="size-3.5" /></span>
      {{ label }}
      <span v-if="to" class="lucide-arrow-up-right ml-auto size-3.5 opacity-0 transition group-hover:opacity-100" />
    </div>
    <div class="text-2xl font-semibold tabular-nums tracking-tight" :class="toneText">{{ value }}</div>
    <div v-if="hint" class="text-xs text-ink-gray-5">{{ hint }}</div>
  </component>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ label: String, value: [String, Number], hint: String, icon: String, to: [String, Object], tone: { type: String, default: 'gray' } })
const toneBg = computed(() => ({ gray: 'bg-surface-gray-2 text-ink-gray-7', red: 'bg-red-100 text-red-700', green: 'bg-green-100 text-green-700', amber: 'bg-amber-100 text-amber-800', blue: 'bg-blue-100 text-blue-700', violet: 'bg-violet-100 text-violet-700' })[props.tone])
const toneText = computed(() => ({ red: 'text-red-700', green: 'text-green-700', amber: 'text-amber-800' })[props.tone] || 'text-ink-gray-9')
const toneBorder = computed(() => ({ red: 'border-red-200', amber: 'border-amber-200' })[props.tone] || 'border-outline-gray-2')
</script>
