<template>
  <PageHead title="Overview" />
  <div v-if="!ov" class="tt-page space-y-4">
    <div class="h-10 w-72 animate-pulse rounded bg-surface-gray-2" />
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4"><div v-for="n in 4" :key="n" class="h-28 animate-pulse rounded-xl bg-surface-gray-2" /></div>
  </div>
  <div v-else class="tt-page space-y-6">
    <PageIntro :title="ov.plan.plan_name" icon="lucide-calendar-range">
      <template #description>
        {{ [ov.plan.campus, ov.plan.academic_year].filter(Boolean).join(' · ') }}
        <span v-if="ov.plan.start_date"> · {{ fmtDate(ov.plan.start_date) }} – {{ fmtDate(ov.plan.end_date) }}</span>
      </template>
      <Badge size="lg" :theme="statusTheme[ov.plan.status]" :label="ov.plan.status" />
      <Button v-if="ov.is_manager" icon-left="lucide-upload" label="Import" :route="{ name: 'Import', params: { plan: plan.name } }" />
      <Button v-if="ov.is_manager" variant="solid" icon-left="lucide-play" label="Check & generate" :route="{ name: 'Generate', params: { plan: plan.name } }" />
    </PageIntro>

    <Card flush>
      <div class="px-4 py-3"><StepBar :steps="ov.steps" :plan="plan.name" /></div>
      <div v-if="next" class="flex flex-wrap items-center gap-4 border-t border-outline-gray-1 bg-surface-gray-1 px-5 py-4">
        <div class="flex size-9 items-center justify-center rounded-full bg-surface-base"><span :class="next.icon" class="size-4 text-ink-gray-8" /></div>
        <div class="min-w-0 flex-1">
          <div class="text-xs font-medium uppercase tracking-wide text-ink-gray-5">Next step</div>
          <div class="font-medium text-ink-gray-9">{{ next.title }}</div>
          <div class="text-sm text-ink-gray-6">{{ next.text }}</div>
        </div>
        <Button variant="solid" :label="next.action" icon-right="lucide-arrow-right" :route="next.route" />
      </div>
    </Card>

    <div v-if="ov.running" class="flex flex-wrap items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-5 py-4">
      <span class="relative flex size-3"><span class="absolute inline-flex size-full animate-ping rounded-full bg-blue-400 opacity-75" /><span class="relative inline-flex size-3 rounded-full bg-blue-500" /></span>
      <div class="min-w-0 flex-1">
        <div class="font-medium text-blue-900">A timetable is being generated</div>
        <div class="text-sm text-blue-800">You can keep working. The result appears under Versions when it finishes.</div>
      </div>
      <Button label="View progress" icon-right="lucide-arrow-right" :route="{ name: 'Generate', params: { plan: plan.name } }" />
    </div>
    <Alert v-else-if="ov.plan.status === 'Finalised'" theme="green" title="This plan is finalised"
      description="The approved timetable is published. Data is locked until the plan is reopened."
      :primary-action="{ label: 'Open approved timetable', onClick: () => router.push({ name: 'Review', params: { plan: plan.name, version: ov.plan.active_version } }) }" />

    <div class="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      <StatCard v-for="t in tiles" :key="t.dt" :label="t.label" :value="ov.counts[t.dt]" :icon="t.icon" :to="{ name: t.route, params: { plan: plan.name } }" />
    </div>

    <div class="grid gap-6 lg:grid-cols-5">
      <Card class="lg:col-span-3" title="Readiness" :description="ov.readiness ? `Checked ${timeAgo(ov.readiness.checked_on)}` : 'Validate the data before generating.'">
        <template #actions><Button size="sm" label="Open checks" :route="{ name: 'Generate', params: { plan: plan.name } }" /></template>
        <EmptyState v-if="!ov.readiness" icon="lucide-list-checks" title="Not checked yet" description="The readiness check finds data problems that would make a timetable impossible.">
          <Button label="Run readiness check" :route="{ name: 'Generate', params: { plan: plan.name } }" />
        </EmptyState>
        <div v-else class="space-y-4">
          <div class="grid grid-cols-3 gap-3">
            <div class="rounded-lg p-3" :class="ov.readiness.ok ? 'bg-green-50' : 'bg-red-50'">
              <div class="text-xs text-ink-gray-6">Status</div>
              <div class="mt-0.5 flex items-center gap-1.5 font-semibold" :class="ov.readiness.ok ? 'text-green-700' : 'text-red-700'">
                <span :class="ov.readiness.ok ? 'lucide-circle-check' : 'lucide-circle-x'" class="size-4" />{{ ov.readiness.ok ? 'Ready' : 'Blocked' }}
              </div>
            </div>
            <div class="rounded-lg bg-surface-gray-1 p-3"><div class="text-xs text-ink-gray-6">Blocking</div><div class="mt-0.5 font-semibold tabular-nums" :class="ov.readiness.errors ? 'text-red-700' : 'text-ink-gray-9'">{{ ov.readiness.errors }}</div></div>
            <div class="rounded-lg bg-surface-gray-1 p-3"><div class="text-xs text-ink-gray-6">Warnings</div><div class="mt-0.5 font-semibold tabular-nums" :class="ov.readiness.warnings ? 'text-amber-700' : 'text-ink-gray-9'">{{ ov.readiness.warnings }}</div></div>
          </div>
          <ul v-if="ov.readiness.top?.length" class="divide-y divide-outline-gray-1 rounded-lg border border-outline-gray-1">
            <li v-for="t in ov.readiness.top" :key="t.code" class="flex items-start gap-3 px-3 py-2.5 text-sm">
              <span :class="t.level === 'error' ? 'lucide-circle-x text-red-600' : 'lucide-triangle-alert text-amber-600'" class="mt-0.5 size-4 shrink-0" />
              <div class="min-w-0 flex-1">
                <div class="font-medium text-ink-gray-8">{{ issueLabel(t.code) }}</div>
                <div class="truncate text-ink-gray-5" :title="t.sample">{{ t.sample }}</div>
              </div>
              <Badge size="sm" :theme="t.level === 'error' ? 'red' : 'amber'" :label="t.count" />
            </li>
          </ul>
          <p v-else class="flex items-center gap-2 text-sm text-green-700"><span class="lucide-sparkles size-4" /> No problems found.</p>
          <div v-if="ov.readiness.stats?.sessions" class="text-xs text-ink-gray-5">
            {{ ov.readiness.stats.sessions }} sessions to place for {{ ov.readiness.stats.cohorts }} cohorts.
          </div>
        </div>
      </Card>

      <Card class="lg:col-span-2" title="Recent versions" flush>
        <template #actions><Button size="sm" label="All versions" :route="{ name: 'Versions', params: { plan: plan.name } }" /></template>
        <div v-if="!ov.versions.length" class="p-5">
          <EmptyState icon="lucide-layers" title="No timetables yet" description="Generated and imported timetables appear here." />
        </div>
        <ul v-else class="divide-y divide-outline-gray-1">
          <li v-for="v in ov.versions" :key="v.name">
            <router-link :to="{ name: 'Review', params: { plan: plan.name, version: v.name } }" class="flex items-center gap-3 px-5 py-3 hover:bg-surface-gray-1">
              <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-gray-2">
                <span :class="v.source === 'Imported' ? 'lucide-file-input' : 'lucide-cpu'" class="size-4 text-ink-gray-6" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm font-medium text-ink-gray-9">{{ v.version_label }}</div>
                <div class="text-xs text-ink-gray-5">{{ timeAgo(v.creation) }}
                  <template v-if="v.run_status === 'Completed'"> · <span :class="v.hard_issues ? 'text-red-600' : 'text-green-700'">{{ v.hard_issues ? `${v.hard_issues} clashes` : 'no clashes' }}</span></template>
                </div>
              </div>
              <Badge size="sm" :theme="v.run_status === 'Completed' ? APPROVAL_THEME[v.approval_status] : RUN_THEME[v.run_status]" :label="v.run_status === 'Completed' ? v.approval_status : v.run_status" />
            </router-link>
          </li>
        </ul>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Alert, Badge, Button } from 'frappe-ui'
import Card from '@/components/Card.vue'
import EmptyState from '@/components/EmptyState.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import StatCard from '@/components/StatCard.vue'
import StepBar from '@/components/StepBar.vue'
import { usePlan } from '@/composables/usePlan'
import { timeAgo } from '@/utils/time'
import { APPROVAL_THEME, RUN_THEME, issueLabel } from '@/utils/timetable'

const plan = usePlan()
const router = useRouter()
const ov = computed(() => plan.overview.data)
onMounted(() => plan.overview.data && plan.overview.reload().catch(() => {}))
const statusTheme = { Setup: 'gray', Ready: 'blue', Generated: 'violet', Finalised: 'green' }
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '…')
const tiles = [
  { dt: 'TT Section', label: 'Sections', route: 'Sections', icon: 'lucide-book-open' },
  { dt: 'TT Faculty', label: 'Faculty', route: 'Faculty', icon: 'lucide-users' },
  { dt: 'TT Room', label: 'Rooms', route: 'Rooms', icon: 'lucide-door-open' },
  { dt: 'TT Category', label: 'Categories', route: 'Categories', icon: 'lucide-tags' },
  { dt: 'TT Meeting', label: 'Meetings', route: 'Meetings', icon: 'lucide-calendar-clock' },
  { dt: 'TT Term', label: 'Terms', route: 'PlanSetup', icon: 'lucide-calendar-range' },
  { dt: 'TT Programme', label: 'Programmes', route: 'PlanSetup', icon: 'lucide-graduation-cap' },
]
const NEXT = {
  setup: { icon: 'lucide-calendar-cog', title: 'Set the semester dates and terms', text: 'Add the semester dates, time-slot labels and the sub-terms used by programmes.', action: 'Term setup' },
  data: { icon: 'lucide-upload', title: 'Bring in the course list', text: 'Import the planning workbook, or add sections, faculty and rooms by hand.', action: 'Import workbook', route: 'Import' },
  validate: { icon: 'lucide-list-checks', title: 'Run the readiness check', text: 'Find data problems that would make a timetable impossible before you generate.', action: 'Run check' },
  rules: { icon: 'lucide-sliders-horizontal', title: 'Review rules & preferences', text: 'Decide how strongly each preference counts.', action: 'Open rules' },
  generate: { icon: 'lucide-play', title: 'Generate a timetable', text: 'The solver runs in the background; you can keep working.', action: 'Generate' },
  review: { icon: 'lucide-table', title: 'Review and submit a version', text: 'Check clashes, adjust sessions by hand and submit the best version for approval.', action: 'Open versions' },
  finalise: { icon: 'lucide-badge-check', title: 'Approve the timetable', text: 'An approver approves the submitted version, which finalises the plan.', action: 'Open versions' },
  outputs: { icon: 'lucide-file-spreadsheet', title: 'Share the outputs', text: 'Download cohort, faculty and room timetables.', action: 'Reports' },
}
const next = computed(() => {
  const s = ov.value?.steps.find((x) => x.current)
  if (!s) return null
  const n = NEXT[s.key]
  return { ...n, route: { name: n.route || s.route, params: { plan: plan.name } } }
})
</script>
