<template>
  <section class="rounded-xl border border-outline-gray-2 bg-surface-base">
    <header v-if="title || $slots.actions" class="flex flex-wrap items-center gap-3 border-b border-outline-gray-1 px-5 py-3.5">
      <div class="min-w-0">
        <h2 class="font-medium text-ink-gray-9">{{ title }}</h2>
        <p v-if="description" class="mt-0.5 text-sm text-ink-gray-5">{{ description }}</p>
      </div>
      <div class="ml-auto flex items-center gap-2"><slot name="actions" /></div>
    </header>
    <div :class="flush ? '' : 'p-5'"><slot /></div>
  </section>
</template>
<script setup>
defineProps({ title: String, description: String, flush: Boolean })
</script>
