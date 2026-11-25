<template>
  <nav aria-label="Workflow" class="overflow-x-auto">
    <ol class="flex min-w-max items-center">
      <li v-for="(s, i) in steps" :key="s.key" class="flex items-center">
        <router-link :to="{ name: s.route, params: { plan } }" class="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-gray-2"
          :aria-current="s.current ? 'step' : undefined">
          <span class="flex size-6 items-center justify-center rounded-full text-xs font-semibold transition"
            :class="s.done ? 'bg-green-600 text-white' : s.current ? 'bg-surface-gray-9 text-white ring-4 ring-gray-200' : 'border border-outline-gray-3 bg-surface-base text-ink-gray-5'">
            <span v-if="s.done" class="lucide-check size-3.5" />
            <template v-else>{{ i + 1 }}</template>
          </span>
          <span class="text-sm" :class="s.current ? 'font-semibold text-ink-gray-9' : s.done ? 'text-ink-gray-7' : 'text-ink-gray-5'">{{ s.label }}</span>
        </router-link>
        <span v-if="i < steps.length - 1" class="mx-1 h-px w-6 lg:w-10" :class="s.done ? 'bg-green-500' : 'bg-surface-gray-4'" />
      </li>
    </ol>
  </nav>
</template>
<script setup>
defineProps({ steps: { type: Array, default: () => [] }, plan: { type: String, required: true } })
</script>
