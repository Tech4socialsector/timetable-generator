<template>
  <span class="inline-flex max-w-full items-center gap-1 truncate rounded px-1.5 py-0.5 text-xs font-medium" :style="style" :title="title">{{ id }}</span>
</template>
<script setup>
import { computed } from 'vue'
import { usePlan } from '@/composables/usePlan'
import { chipStyle } from '@/utils/colors'
import { choiceLabel } from '@/utils/timetable'

const props = defineProps({ id: { type: String, default: '' } })
const plan = usePlan()
const style = computed(() => chipStyle(props.id))
const title = computed(() => {
  const c = plan.options.data?.categories?.find((x) => x.category_id === props.id)
  return c ? `${c.category_name} · ${choiceLabel(c.choice_type)}` : props.id
})
</script>
