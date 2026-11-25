<template>
  <PageHeader>
    <Breadcrumbs :items="items" />
    <div class="flex items-center gap-2"><slot /></div>
  </PageHeader>
</template>
<script setup>
import { computed } from 'vue'
import { Breadcrumbs, PageHeader } from 'frappe-ui'
import { usePlan } from '@/composables/usePlan'

const props = defineProps({ title: { type: String, required: true }, trail: { type: Array, default: () => [] } })
const plan = usePlan()
const items = computed(() => [
  { label: plan.overview.data?.plan?.plan_name || plan.name, route: { name: 'Overview', params: { plan: plan.name } } },
  ...props.trail,
  { label: props.title },
])
</script>
