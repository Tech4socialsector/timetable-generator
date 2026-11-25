<template>
  <PageHead title="Reports & exports" />
  <div class="tt-page tt-narrow space-y-6">
    <PageIntro title="Reports & exports" icon="lucide-file-spreadsheet" description="Excel outputs for programme offices, faculty and students, plus a free-slot finder." />
    <div class="flex flex-wrap items-end gap-3">
      <Select v-model="version" class="w-80" label="Timetable version" :options="versionOptions" placeholder="Choose a version" />
      <p v-if="approved" class="pb-1.5 text-sm text-ink-gray-5">Defaults to the approved version.</p>
    </div>
    <p v-if="!versionOptions.length && !list.loading" class="text-sm text-ink-gray-5">No completed versions yet.</p>

    <div v-if="version" class="grid gap-3 sm:grid-cols-2">
      <button v-for="r in REPORTS" :key="r.key" type="button" class="flex items-start gap-3 rounded-xl border border-outline-gray-2 bg-surface-base p-4 text-left hover:border-outline-gray-3 hover:bg-surface-gray-1"
        @click="download('timetable_app.api.reports.download', { version, report: r.key })">
        <span :class="r.icon" class="mt-0.5 size-5 shrink-0 text-ink-gray-6" />
        <span>
          <span class="block font-medium text-ink-gray-8">{{ r.label }}</span>
          <span class="block text-sm text-ink-gray-5">{{ r.help }}</span>
        </span>
        <span class="lucide-download ml-auto size-4 text-ink-gray-5" />
      </button>
    </div>

    <section v-if="version" class="space-y-3 rounded-xl border border-outline-gray-2 bg-surface-base p-4">
      <h2 class="font-medium text-ink-gray-8">Find free slots</h2>
      <div class="flex flex-wrap items-end gap-2">
        <TabButtons v-model="freeKind" :options="[{ label: 'Cohort', value: 'cohort' }, { label: 'Faculty', value: 'faculty' }, { label: 'Room', value: 'room' }]" />
        <TextInput v-model="freeKey" :placeholder="freeKind === 'cohort' ? 'e.g. BSCBIO25' : freeKind === 'faculty' ? 'email' : 'room ID'" class="w-64" />
        <Button label="Show free slots" :loading="free.loading" :disabled="!freeKey" @click="free.submit({ version, kind: freeKind, key: freeKey }).catch(() => {})" />
      </div>
      <ErrorMessage :message="free.error" />
      <div v-if="free.data" class="overflow-x-auto">
        <table class="border-separate border-spacing-1 text-xs">
          <thead><tr><th></th><th v-for="d in week.days" :key="d" class="font-medium text-ink-gray-6">{{ d }}</th></tr></thead>
          <tbody>
            <tr v-for="s in week.slots_per_day" :key="s">
              <th class="pr-2 text-left font-normal text-ink-gray-5">{{ slots[s - 1]?.label || `Slot ${s - 1}` }}</th>
              <td v-for="(d, di) in week.days" :key="d" class="h-7 w-20 rounded text-center" :class="free.data.includes(di * week.slots_per_day + s - 1) ? 'bg-green-100 text-green-900' : 'bg-surface-gray-2 text-ink-gray-4'">
                {{ free.data.includes(di * week.slots_per_day + s - 1) ? 'free' : 'busy' }}
              </td>
            </tr>
          </tbody>
        </table>
        <p class="mt-1 text-xs text-ink-gray-5">{{ free.data.length }} free slots (faculty and room availability included).</p>
      </div>
    </section>

    <section class="space-y-2 rounded-xl border border-outline-gray-2 bg-surface-base p-4">
      <h2 class="font-medium text-ink-gray-8">Input data</h2>
      <p class="text-sm text-ink-gray-5">The plan's data as a planning workbook, re-importable into any plan.</p>
      <Button icon-left="lucide-download" label="Download input workbook" @click="download('timetable_app.api.data_io.export_inputs', { plan: plan.name })" />
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Button, ErrorMessage, Select, TabButtons, TextInput, createResource } from 'frappe-ui'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import { usePlan } from '@/composables/usePlan'
import { download } from '@/utils/api'
import { useWeek } from '@/composables/useWeek'

const plan = usePlan()
const route = useRoute()
const REPORTS = [
  { key: 'full', label: 'Complete workbook', help: 'Every report below in one file, plus the checks.', icon: 'lucide-files' },
  { key: 'timetable', label: 'Overall timetable', help: 'Course-wise list of every session.', icon: 'lucide-list' },
  { key: 'cohort', label: 'Cohort-wise timetable', help: 'Each cohort’s sessions in list format.', icon: 'lucide-users' },
  { key: 'faculty', label: 'Faculty timetable', help: 'Each faculty member’s courses and times.', icon: 'lucide-user-round' },
  { key: 'room', label: 'Room-wise timetable', help: 'What happens in each room and when.', icon: 'lucide-door-open' },
  { key: 'skeleton', label: 'Skeleton', help: 'Categories scheduled in each day and slot.', icon: 'lucide-grid-3x3' },
  { key: 'complete', label: 'Complete-category availability', help: 'Which cohorts can attend each Complete-category course.', icon: 'lucide-circle-check-big' },
  { key: 'utilisation', label: 'Room utilisation', help: 'Rooms in use per slot.', icon: 'lucide-chart-column' },
  { key: 'free_cohort', label: 'Free slots per cohort', help: 'Free slots for every cohort.', icon: 'lucide-calendar-check' },
  { key: 'free_faculty', label: 'Free slots per faculty', help: 'Free slots for every faculty member.', icon: 'lucide-calendar-check-2' },
  { key: 'with_inputs', label: 'Input workbook with timetable', help: 'The old command-line output format.', icon: 'lucide-file-spreadsheet' },
]
const list = createResource({ url: 'timetable_app.api.review.list_versions', params: { plan: plan.name }, auto: true, onError: () => {} })
const approved = computed(() => plan.overview.data?.plan?.active_version)
const versionOptions = computed(() => (list.data || []).filter((v) => v.run_status === 'Completed').map((v) => ({ label: `${v.version_label} · ${v.approval_status}`, value: v.name })))
const version = ref(route.query.version || null)
watch([versionOptions, approved], () => {
  if (!version.value) version.value = approved.value || versionOptions.value[0]?.value || null
}, { immediate: true })
const slots = computed(() => plan.overview.data?.slots || [])
const week = useWeek()
const freeKind = ref('cohort')
const freeKey = ref('')
const free = createResource({ url: 'timetable_app.api.review.get_free_slots', onError: () => {} })
watch([freeKind, version], () => free.reset())
</script>
