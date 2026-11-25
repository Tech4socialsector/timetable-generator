<template>
  <PageHead title="Versions & approval">
    <Button v-if="finalised && session.is_manager" icon-left="lucide-lock-open" label="Reopen plan" @click="actions.reopen()" />
    <Button v-if="session.is_manager" variant="solid" icon-left="lucide-play" label="Generate" :route="{ name: 'Generate', params: { plan: plan.name } }" />
  </PageHead>
  <div class="tt-page space-y-4">
    <PageIntro title="Versions & approval" icon="lucide-layers" description="Every generated or imported timetable, its quality and where it is in the approval process." />
    <div v-if="list.loading && !list.data" class="flex justify-center py-20"><Spinner class="size-6" /></div>
    <div v-else-if="!list.data?.length" class="rounded-xl border border-dashed border-outline-gray-3 p-12 text-center text-sm text-ink-gray-6">
      No versions yet. Generate a timetable, or import one with a workbook's Timetable sheet.
    </div>
    <div v-else class="overflow-x-auto rounded-xl border border-outline-gray-2 bg-surface-base">
      <table class="w-full text-left text-sm">
        <thead class="bg-surface-gray-1 text-ink-gray-6">
          <tr>
            <th class="px-3 py-2 font-medium">Version</th><th class="px-3 py-2 font-medium">Run</th><th class="px-3 py-2 font-medium">Approval</th>
            <th class="px-3 py-2 font-medium">Hard issues</th><th class="px-3 py-2 font-medium">Soft issues</th><th class="px-3 py-2 font-medium">Penalty</th>
            <th class="px-3 py-2 font-medium">Run time</th><th class="px-3 py-2 font-medium">Created</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="v in list.data" :key="v.name" class="border-t border-outline-gray-1 hover:bg-surface-gray-1">
            <td class="px-3 py-2">
              <router-link :to="{ name: 'Review', params: { plan: plan.name, version: v.name } }" class="font-medium text-ink-gray-9 hover:underline">{{ v.version_label }}</router-link>
              <div class="text-xs text-ink-gray-5">{{ v.source }}<span v-if="v.notes"> · {{ v.notes }}</span></div>
              <div v-if="v.review_comment" class="text-xs text-ink-amber-7">“{{ v.review_comment }}”</div>
            </td>
            <td class="px-3 py-2"><Badge :theme="RUN_THEME[v.run_status]" :label="v.run_status" /></td>
            <td class="px-3 py-2"><Badge v-if="v.run_status === 'Completed'" :theme="APPROVAL_THEME[v.approval_status]" :label="v.approval_status" /></td>
            <td class="px-3 py-2 tabular-nums" :class="v.hard_issues ? 'font-medium text-ink-red-7' : 'text-ink-gray-6'">{{ v.run_status === 'Completed' ? v.hard_issues : '' }}</td>
            <td class="px-3 py-2 tabular-nums text-ink-gray-6">{{ v.run_status === 'Completed' ? v.soft_issues : '' }}</td>
            <td class="px-3 py-2 tabular-nums text-ink-gray-6">{{ v.run_status === 'Completed' && v.source !== 'Imported' ? formatNumber(v.objective) : '—' }}</td>
            <td class="px-3 py-2 tabular-nums text-ink-gray-6">{{ v.run_status === 'Completed' && v.source !== 'Imported' ? formatDuration(v.wall_time) : '—' }}</td>
            <td class="px-3 py-2 text-ink-gray-6">{{ timeAgo(v.creation) }}</td>
            <td class="px-3 py-2 text-right">
              <Dropdown :button="{ icon: 'lucide-ellipsis', label: 'Actions', variant: 'ghost' }" :options="menu(v)" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="text-xs text-ink-gray-5">Hard issues are clashes that break a rule (double bookings, cohort clashes, wrong rooms). Soft issues are preferences the solver could not meet. Lower penalty is better.</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Button, Dropdown, Spinner, createResource } from 'frappe-ui'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import { usePlan } from '@/composables/usePlan'
import { useVersionActions } from '@/composables/useVersionActions'
import { session } from '@/session'
import { timeAgo } from '@/utils/time'
import { APPROVAL_THEME, RUN_THEME, formatDuration, formatNumber } from '@/utils/timetable'

const plan = usePlan()
const router = useRouter()
const list = createResource({ url: 'timetable_app.api.review.list_versions', params: { plan: plan.name }, auto: true, onError: () => {} })
const actions = useVersionActions(() => list.reload())
const finalised = computed(() => plan.overview.data?.plan?.status === 'Finalised')

function menu(v) {
  const done = v.run_status === 'Completed'
  const editable = ['Draft', 'Changes Requested'].includes(v.approval_status)
  const m = [{ label: 'Open', icon: 'lucide-table', onClick: () => router.push({ name: 'Review', params: { plan: plan.name, version: v.name } }) }]
  if (session.is_manager) {
    if (done && editable) m.push({ label: 'Submit for approval', icon: 'lucide-send', onClick: () => actions.submit(v) })
    if (done && !finalised.value) m.push({ label: 'Create editable copy', icon: 'lucide-copy', onClick: () => actions.copy(v) })
    m.push({ label: 'Rename', icon: 'lucide-pencil', onClick: () => actions.rename(v) })
  }
  if (session.is_approver && v.approval_status === 'Submitted') {
    m.push({ label: 'Approve', icon: 'lucide-badge-check', onClick: () => actions.approve(v) })
    m.push({ label: 'Request changes', icon: 'lucide-message-square-warning', onClick: () => actions.requestChanges(v) })
  }
  if (session.is_manager && v.approval_status !== 'Approved' && !['Queued', 'Running'].includes(v.run_status))
    m.push({ label: 'Delete', icon: 'lucide-trash-2', theme: 'red', onClick: () => actions.remove(v) })
  return m
}
</script>
