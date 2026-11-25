<template>
  <Dialog v-model:open="open" :title="entry ? sessionLabel(entry) : ''" size="3xl">
    <div v-if="entry" class="space-y-5">
      <div class="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div><span class="text-ink-gray-5">Course</span><div class="text-ink-gray-9">{{ entry.course_name }} ({{ entry.course_code }})</div></div>
        <div><span class="text-ink-gray-5">Category</span><div><CategoryChip :id="entry.category" /></div></div>
        <div><span class="text-ink-gray-5">When</span><div class="text-ink-gray-9">{{ dayLong(entry.day_index) }}, {{ slotText(entry.slot_index) }}<span v-if="entry.duration > 1"> ({{ entry.duration }} slots)</span></div></div>
        <div><span class="text-ink-gray-5">Room</span><div class="text-ink-gray-9">{{ entry.room_name || 'No room (virtual)' }}</div></div>
        <div><span class="text-ink-gray-5">Faculty</span><div class="text-ink-gray-9">{{ entry.faculty_ids.map((f) => faculty[f] || f).join(', ') || '—' }}</div></div>
        <div><span class="text-ink-gray-5">Cohorts</span><div class="text-ink-gray-9">{{ entry.cohorts.join(', ') || '—' }}</div></div>
        <div><span class="text-ink-gray-5">Term</span><div class="text-ink-gray-9">{{ entry.term_id }}</div></div>
        <div><span class="text-ink-gray-5">Session</span><div class="text-ink-gray-9">{{ entry.session_type === 'LAB' ? 'Lab' : 'Theory' }} {{ entry.session_index + 1 }}<span v-if="entry.is_manual"> · moved by hand</span></div></div>
      </div>
      <div v-if="issues.length" class="space-y-1 rounded border border-outline-red-3 bg-surface-red-1 p-3 text-sm">
        <div class="font-medium text-ink-red-7">Clashes involving this session</div>
        <div v-for="(i, n) in issues" :key="n" class="text-ink-gray-8">• {{ i.message }}</div>
      </div>

      <div v-if="editable" class="space-y-3">
        <div class="flex items-center gap-2">
          <h3 class="font-medium text-ink-gray-8">Move to</h3>
          <Spinner v-if="opts.loading" class="size-4" />
          <div class="ml-auto flex items-center gap-3 text-xs text-ink-gray-5">
            <span class="flex items-center gap-1"><i class="inline-block size-3 rounded bg-green-200" /> no clash</span>
            <span class="flex items-center gap-1"><i class="inline-block size-3 rounded bg-amber-200" /> no room free</span>
            <span class="flex items-center gap-1"><i class="inline-block size-3 rounded bg-red-200" /> clash</span>
          </div>
        </div>
        <div v-if="opts.data" class="overflow-x-auto">
          <table class="w-full border-separate border-spacing-1 text-xs">
            <thead><tr><th></th><th v-for="d in days" :key="d" class="font-medium text-ink-gray-6">{{ d }}</th></tr></thead>
            <tbody>
              <tr v-for="s in SLOTS" :key="s">
                <th class="pr-1 text-left font-normal text-ink-gray-5">{{ slots[s]?.label || `Slot ${s}` }}</th>
                <td v-for="(d, di) in days" :key="d">
                  <button v-if="optAt(di, s)" type="button" class="h-9 w-full rounded border text-[11px] leading-tight"
                    :class="[optClass(optAt(di, s)), target && target.day_index === di && target.slot_index === s ? 'ring-2 ring-gray-800' : '']"
                    :title="optAt(di, s).issues.join('\n') || `${optAt(di, s).free_rooms.length} rooms free`" @click="pick(optAt(di, s))">
                    <span v-if="optAt(di, s).current">current</span>
                    <span v-else-if="optAt(di, s).issues.length">{{ optAt(di, s).issues.length }} clash</span>
                    <span v-else-if="opts.data.needs_room">{{ optAt(di, s).free_rooms.length }} rooms</span>
                    <span v-else>ok</span>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="target" class="space-y-3 rounded-lg bg-surface-gray-1 p-3">
          <div class="text-sm text-ink-gray-8">{{ dayLong(target.day_index) }}, {{ slotText(target.slot_index) }}</div>
          <div v-if="target.issues.length" class="text-sm text-ink-red-7"><div v-for="(m, n) in target.issues" :key="n">• {{ m }}</div></div>
          <div v-if="!target.solver_allowed" class="text-sm text-ink-amber-7">Outside the slots the solver was allowed to use for this session (faculty availability or allowed slots).</div>
          <Select v-if="opts.data.needs_room" v-model="room" class="w-full sm:w-96" label="Room" :options="roomOptions" placeholder="Choose a room" />
          <ErrorMessage :message="error" />
          <div class="flex items-center gap-2">
            <Button variant="solid" :loading="moving" :label="needsForce ? 'Move anyway' : 'Move session'" :theme="needsForce ? 'red' : 'gray'" :disabled="opts.data.needs_room && !room" @click="move" />
            <span v-if="needsForce" class="text-xs text-ink-gray-6">This creates clashes that will show as hard issues.</span>
          </div>
        </div>
      </div>
      <p v-else class="text-sm text-ink-gray-5">This version cannot be edited. Create an editable copy from the Versions page to adjust it.</p>
    </div>
  </Dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, Select, Spinner, call, createResource, toast } from 'frappe-ui'
import CategoryChip from './CategoryChip.vue'
import { errorMessage } from '@/utils/api'
import { sessionLabel } from '@/utils/grid'
import { DAYS, DAY_LONG, SLOTS_PER_DAY } from '@/utils/timetable'

const open = defineModel('open', { type: Boolean, default: false })
const props = defineProps({
  entry: { type: Object, default: null },
  slots: { type: Array, default: () => [] },
  faculty: { type: Object, default: () => ({}) },
  rooms: { type: Array, default: () => [] },
  issues: { type: Array, default: () => [] },
  editable: Boolean,
  week: { type: Object, default: null },
})
const emit = defineEmits(['moved'])
const days = computed(() => props.week?.days || DAYS)
const SLOTS = computed(() => [...Array(props.week?.slots_per_day || SLOTS_PER_DAY).keys()])
const dayLong = (i) => DAY_LONG[days.value[i]] || days.value[i] || `Day ${i}`
const opts = createResource({ url: 'timetable_app.api.review.move_options', onError: () => {} })
const target = ref(null)
const room = ref(null)
const error = ref('')
const moving = ref(false)
const forceNeeded = ref(false)

watch([open, () => props.entry?.name], ([o]) => {
  target.value = null
  room.value = null
  error.value = ''
  forceNeeded.value = false
  if (o && props.entry && props.editable) opts.submit({ entry: props.entry.name }).catch(() => {})
})

const slotText = (s) => {
  const x = props.slots[s]
  return x ? `${x.label}${x.start_time ? ` (${x.start_time}–${x.end_time})` : ''}` : `Slot ${s}`
}
const optAt = (d, s) => opts.data?.options.find((o) => o.day_index === d && o.slot_index === s)
const optClass = (o) => {
  if (o.current) return 'border-outline-gray-4 bg-surface-gray-3 text-ink-gray-8'
  if (o.issues.length) return 'border-red-300 bg-red-100 text-red-800 hover:bg-red-200'
  if (opts.data.needs_room && !o.free_rooms.length) return 'border-amber-300 bg-amber-100 text-amber-900 hover:bg-amber-200'
  return 'border-green-300 bg-green-100 text-green-900 hover:bg-green-200'
}
const roomName = (id) => props.rooms.find((r) => r.room_id === id)
const roomOptions = computed(() => {
  if (!target.value) return []
  const free = new Set(target.value.free_rooms)
  const list = props.rooms.map((r) => ({ label: `${r.room_name} · ${r.capacity || 0} seats${free.has(r.room_id) ? '' : ' (busy / unsuitable)'}`, value: r.room_id, free: free.has(r.room_id) }))
  return list.sort((a, b) => Number(b.free) - Number(a.free))
})
const needsForce = computed(() => forceNeeded.value || !!target.value?.issues.length || (room.value && target.value && !target.value.free_rooms.includes(room.value)))

function pick(o) {
  target.value = o
  error.value = ''
  forceNeeded.value = false
  const current = props.entry.room_id
  room.value = o.free_rooms.includes(current) ? current : o.free_rooms[0] || current || null
}
async function move() {
  moving.value = true
  error.value = ''
  try {
    const r = await call('timetable_app.api.review.move_entry', {
      entry: props.entry.name, day_index: target.value.day_index, slot_index: target.value.slot_index,
      room_id: opts.data.needs_room ? room.value : '', force: needsForce.value ? 1 : 0,
    })
    if (!r.saved) {
      forceNeeded.value = true
      error.value = r.issues.map((i) => i.message).join(' ')
      return
    }
    toast.success(r.issues.length ? `Moved with ${r.issues.length} clash(es)` : 'Session moved')
    emit('moved')
    open.value = false
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    moving.value = false
  }
}
defineExpose({ roomName })
</script>
