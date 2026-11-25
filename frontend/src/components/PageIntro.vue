<template>
  <div class="flex flex-wrap items-start gap-4 pb-5">
    <div v-if="icon" class="flex size-10 shrink-0 items-center justify-center rounded-lg border border-outline-gray-2 bg-surface-base">
      <span :class="icon" class="size-5 text-ink-gray-7" />
    </div>
    <div class="min-w-0 flex-1">
      <h1 class="text-xl font-semibold tracking-tight text-ink-gray-9">{{ title }}</h1>
      <p v-if="description || $slots.description" class="mt-1 max-w-3xl text-sm leading-relaxed text-ink-gray-5">
        <slot name="description">{{ description }}</slot>
      </p>
    </div>
    <div v-if="$slots.default" class="flex shrink-0 flex-wrap items-center gap-2"><slot /></div>
  </div>
</template>
<script setup>
defineProps({ title: { type: String, required: true }, description: String, icon: String })
</script>
