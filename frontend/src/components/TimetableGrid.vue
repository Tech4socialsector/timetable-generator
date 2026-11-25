<template>
  <div class="overflow-x-auto">
    <table class="w-full min-w-[44rem] table-fixed border-separate border-spacing-0 text-sm">
      <thead>
        <tr>
          <th class="sticky left-0 z-10 w-28 border-b border-outline-gray-2 bg-surface-base"></th>
          <th v-for="d in days" :key="d" class="border-b border-outline-gray-2 bg-surface-base px-2 py-2 text-left font-medium text-ink-gray-7">{{ DAY_LONG[d] || d }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in SLOTS" :key="s">
          <th class="sticky left-0 z-10 border-b border-r border-outline-gray-1 bg-surface-base px-2 py-2 text-left align-top font-normal">
            <div class="text-ink-gray-8">{{ slots[s]?.label || `Slot ${s}` }}</div>
            <div v-if="slots[s]?.start_time" class="text-xs tabular-nums text-ink-gray-5">{{ slots[s].start_time }}–{{ slots[s].end_time }}</div>
            <Badge v-if="slots[s] && !slots[s].regular" size="sm" class="mt-1" label="non-regular" />
          </th>
          <td v-for="(d, di) in days" :key="d" class="h-20 border-b border-r border-outline-gray-1 p-1 align-top"
            :class="[cellClass(di, s), dropTarget === `${di}-${s}` ? 'ring-2 ring-inset ring-outline-gray-4' : '']"
            @dragover.prevent="editable && (dropTarget = `${di}-${s}`)" @dragleave="dropTarget = null" @drop.prevent="onDrop(di, s)">
            <!-- dense mode: categories summary -->
            <div v-if="dense" class="flex flex-wrap gap-1">
              <button v-for="g in grouped(cells[di][s])" :key="g.category" type="button" class="max-w-full truncate rounded px-1.5 py-0.5 text-xs" :style="chipStyle(g.category)"
                :title="`${g.category}: ${g.items.length} sessions`" @click="emit('pick-category', g.category)">
                {{ g.category }} <b>{{ g.items.length }}</b>
              </button>
            </div>
            <div v-else class="flex flex-col gap-1">
              <button v-for="e in cells[di][s]" :key="e.name + (e.continued ? '-c' : '')" type="button"
                class="group rounded border px-1.5 py-1 text-left text-xs leading-tight transition-shadow hover:shadow"
                :class="[issues[e.name]?.length ? 'ring-2 ring-red-500' : '', e.continued ? 'opacity-60' : '', selected === e.name ? 'outline outline-2 outline-offset-1 outline-gray-700' : '']"
                :style="cardStyle(e.category)" :draggable="editable && !e.continued" @dragstart="dragging = e" @dragend="dragging = null; dropTarget = null"
                :title="issues[e.name]?.length ? issues[e.name].map((i) => i.message).join('\n') : `${e.course_name}\n${e.room_name || 'No room'}`"
                @click="emit('open', e)">
                <div class="flex items-center gap-1 font-semibold">
                  <span class="truncate">{{ sessionLabel(e) }}</span>
                  <span v-if="e.is_manual" class="lucide-hand ml-auto size-3 shrink-0" title="Moved by hand" />

                </div>
                <div class="truncate opacity-90">{{ e.course_name }}</div>
                <div class="truncate opacity-75">{{ e.room_name || 'No room' }}<span v-if="showFaculty"> · {{ facultyShort(e) }}</span></div>
              </button>
              <span v-if="highlightFree && !cells[di][s].length" class="m-auto text-xs text-ink-green-7">free</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Badge } from 'frappe-ui'
import { buildCells, sessionLabel } from '@/utils/grid'
import { cardStyle, chipStyle } from '@/utils/colors'
import { DAYS, DAY_LONG, SLOTS_PER_DAY } from '@/utils/timetable'

const props = defineProps({
  entries: { type: Array, default: () => [] },
  slots: { type: Array, default: () => [] },
  issues: { type: Object, default: () => ({}) },
  faculty: { type: Object, default: () => ({}) },
  dense: Boolean,
  editable: Boolean,
  highlightFree: Boolean,
  showFaculty: { type: Boolean, default: true },
  selected: { type: String, default: null },
  week: { type: Object, default: null }, // { days, slots_per_day, regular_days }
})
const emit = defineEmits(['open', 'drop', 'pick-category'])
const days = computed(() => props.week?.days || DAYS)
const spd = computed(() => props.week?.slots_per_day || SLOTS_PER_DAY)
const SLOTS = computed(() => [...Array(spd.value).keys()])
const cells = computed(() => buildCells(props.entries, days.value.length, spd.value))
const dragging = ref(null)
const dropTarget = ref(null)

const facultyShort = (e) => e.faculty_ids.map((f) => props.faculty[f] || f.split('@')[0]).join(', ')
const cellClass = (d, s) => {
  const regularDays = props.week?.regular_days || DAYS.slice(0, 5)
  return (props.slots[s] && !props.slots[s].regular) || !regularDays.includes(days.value[d]) ? 'bg-surface-gray-1' : 'bg-surface-base'
}
function grouped(list) {
  const m = {}
  for (const e of list) (m[e.category] ||= []).push(e)
  return Object.entries(m).map(([category, items]) => ({ category, items })).sort((a, b) => b.items.length - a.items.length)
}
function onDrop(d, s) {
  dropTarget.value = null
  if (props.editable && dragging.value && !(dragging.value.day_index === d && dragging.value.slot_index === s)) emit('drop', { entry: dragging.value, day_index: d, slot_index: s })
  dragging.value = null
}
</script>
