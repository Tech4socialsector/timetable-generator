<template>
  <div class="flex flex-col items-center justify-center rounded-xl border border-dashed border-outline-gray-3 bg-surface-base px-6 py-14 text-center">
    <div class="mb-4 flex size-12 items-center justify-center rounded-full bg-surface-gray-2"><span :class="icon" class="size-6 text-ink-gray-6" /></div>
    <h3 class="font-medium text-ink-gray-8">{{ title }}</h3>
    <p v-if="description" class="mt-1 max-w-md text-sm text-ink-gray-5">{{ description }}</p>
    <div v-if="$slots.default" class="mt-5 flex gap-2"><slot /></div>
  </div>
</template>
<script setup>
defineProps({ title: String, description: String, icon: { type: String, default: 'lucide-inbox' } })
</script>
