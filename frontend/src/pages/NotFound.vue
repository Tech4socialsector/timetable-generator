<template>
  <div class="flex h-full flex-col items-center justify-center gap-3 text-ink-gray-6">
    <span class="lucide-map-pin-off size-8" />
    <p>This page does not exist.</p>
    <Button label="Go to plans" :route="{ name: 'Plans' }" />
  </div>
</template>
<script setup>
import { Button } from 'frappe-ui'
</script>
