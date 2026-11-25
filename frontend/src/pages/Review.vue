<template>
  <PageHead :title="v?.version_label || 'Timetable'" :trail="[{ label: 'Versions', route: { name: 'Versions', params: { plan: plan.name } } }]">
    <template v-if="v">
      <Badge :theme="RUN_THEME[v.run_status]" :label="v.run_status" />
      <Badge v-if="v.run_status === 'Completed'" :theme="APPROVAL_THEME[v.approval_status]" :label="v.approval_status" />
      <Button v-if="v.run_status === 'Completed'" icon-left="lucide-download" label="Excel" @click="download('timetable_app.api.reports.download', { version, report: 'full' })" />
      <Dropdown v-if="menu.length" :button="{ label: 'Actions', iconRight: 'lucide-chevron-down', variant: 'solid' }" :options="menu" />
    </template>
  </PageHead>

  <div v-if="ver.loading && !v" class="flex justify-center py-20"><Spinner class="size-6" /></div>
  <div v-else-if="ver.error" class="p-6"><ErrorMessage :message="ver.error" /></div>
  <div v-else-if="v && v.run_status !== 'Completed'" class="mx-auto max-w-3xl space-y-4 p-6">
    <Alert :theme="v.run_status === 'Failed' ? 'red' : v.run_status === 'Cancelled' ? 'amber' : 'blue'"
      :title="v.run_status === 'Failed' ? 'Generation failed' : v.run_status === 'Cancelled' ? 'Generation was cancelled' : 'Generation in progress'"
      :description="(v.error || '').split('\n')[0] || 'Follow progress on the Check & generate page.'"
      :primary-action="{ label: 'Check & generate', onClick: () => router.push({ name: 'Generate', params: { plan: plan.name } }) }" />
    <details v-if="v.error" class="rounded border border-outline-gray-2 p-3 text-xs"><summary class="cursor-pointer text-ink-gray-6">Technical details</summary><pre class="mt-2 whitespace-pre-wrap">{{ v.error }}</pre></details>
  </div>

  <div v-else-if="v" class="space-y-4 p-6">
    <div class="grid grid-cols-2 gap-3 md:grid-cols-5">
      <StatCard label="Sessions" :value="v.entries_count" icon="lucide-calendar-days" />
      <StatCard label="Hard issues" :value="v.hard_issues" icon="lucide-octagon-alert" :tone="v.hard_issues ? 'red' : 'green'" :hint="v.hard_issues ? 'Clashes that break a rule' : 'Every hard rule is met'" />
      <StatCard label="Preference misses" :value="v.soft_issues" icon="lucide-thumbs-down" :tone="v.soft_issues ? 'amber' : 'gray'" />
      <StatCard label="Penalty" :value="v.source === 'Imported' ? '—' : formatNumber(v.objective)" icon="lucide-gauge" hint="Lower is better" />
      <StatCard label="Run time" :value="v.source === 'Imported' ? 'Imported' : formatDuration(v.wall_time)" icon="lucide-timer" :hint="v.solver_status && v.source !== 'Imported' ? v.solver_status.toLowerCase() : ''" />
    </div>

    <div class="flex flex-col gap-4 xl:flex-row">
      <div class="min-w-0 flex-1 overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-base">
        <div class="flex flex-wrap items-center gap-2 border-b border-outline-gray-1 px-3 py-2.5">
          <TabButtons v-model="view" :options="VIEWS" />
          <Combobox v-if="view !== 'all'" v-model="value" class="w-64" :options="valueOptions" :placeholder="`Choose ${viewLabel.toLowerCase()}`" />
          <Select v-model="term" :options="termOptions" placeholder="All terms" />
          <TextInput v-if="view === 'all'" v-model="search" type="search" placeholder="Course, faculty, room" class="w-56" :debounce="200" />
          <div class="ml-auto flex items-center gap-2">
            <span class="text-sm tabular-nums text-ink-gray-5">{{ shown.length }} sessions</span>
            <Button :icon="showIssues ? 'lucide-panel-right-close' : 'lucide-panel-right-open'" :label="showIssues ? 'Hide issues' : 'Show issues'" variant="ghost" @click="showIssues = !showIssues" />
          </div>
        </div>
        <div v-if="view !== 'all' && !value" class="p-6">
          <EmptyState icon="lucide-mouse-pointer-click" :title="`Choose a ${viewLabel.toLowerCase()}`" :description="`Pick a ${viewLabel.toLowerCase()} above to see its weekly timetable, or switch to All for the skeleton view.`" />
        </div>
        <TimetableGrid v-else :entries="shown" :slots="v.slots" :week="v.week" :issues="byEntry" :faculty="data?.faculty || {}"
          :dense="view === 'all' && !search" :editable="v.editable" :highlight-free="['cohort', 'faculty', 'room'].includes(view)"
          :show-faculty="view !== 'faculty'" :selected="selected?.name" @open="openEntry" @drop="onDrop" @pick-category="(c) => { view = 'category'; setTimeout(() => (value = c)) }" />
        <div class="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-outline-gray-1 px-4 py-2.5 text-xs text-ink-gray-5">
          <span class="flex items-center gap-1.5"><i class="inline-block size-3 rounded ring-2 ring-red-500" /> clash</span>
          <span class="flex items-center gap-1.5"><span class="lucide-hand size-3" /> moved by hand</span>
          <span class="flex items-center gap-1.5"><i class="inline-block size-3 rounded bg-surface-gray-2" /> non-regular slot</span>
          <span v-if="['cohort', 'faculty', 'room'].includes(view)" class="flex items-center gap-1.5 text-green-700">free = nothing scheduled</span>
          <span class="ml-auto">{{ v.editable ? 'Click a session to move it, or drag it to another slot.' : view === 'all' && !search ? 'Skeleton view: categories per slot. Click one to see its sessions.' : 'Read only.' }}</span>
        </div>
      </div>

      <aside v-if="showIssues" class="w-full shrink-0 space-y-3 xl:w-96">
        <div class="overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-base">
          <div class="border-b border-outline-gray-1 p-2">
            <TabButtons v-model="issueTab" :options="[{ label: `Hard issues (${checks.length})`, value: 'hard' }, { label: `Preferences (${violations.length})`, value: 'soft' }]" />
          </div>
          <div v-if="ruleChips.length > 1" class="flex flex-wrap gap-1.5 border-b border-outline-gray-1 p-2.5">
            <button v-for="c in ruleChips" :key="c.value" type="button" class="rounded-full border px-2.5 py-0.5 text-xs transition"
              :class="(ruleFilter || '__all') === c.value ? 'border-transparent bg-surface-gray-9 text-white' : 'border-outline-gray-2 text-ink-gray-7 hover:bg-surface-gray-2'"
              @click="ruleFilter = c.value === '__all' ? null : c.value">{{ c.label }}</button>
          </div>
          <ul class="max-h-[60vh] divide-y divide-outline-gray-1 overflow-y-auto text-sm">
            <li v-if="!issueList.length" class="flex flex-col items-center gap-2 p-8 text-center text-ink-gray-5">
              <span class="lucide-circle-check-big size-6 text-green-600" />
              {{ issueTab === 'hard' ? 'No clashes. Every hard rule is satisfied.' : 'No preference misses.' }}
            </li>
            <li v-for="(i, n) in issueList.slice(0, issueLimit)" :key="n">
              <button type="button" class="flex w-full gap-2.5 px-3 py-2.5 text-left hover:bg-surface-gray-1" @click="focusIssue(i)">
                <span :class="issueTab === 'hard' ? 'lucide-circle-x text-red-600' : 'lucide-circle-alert text-amber-600'" class="mt-0.5 size-4 shrink-0" />
                <span class="min-w-0">
                  <span class="block text-xs font-medium" :class="issueTab === 'hard' ? 'text-red-700' : 'text-amber-800'">{{ ruleLabel(i.rule) }}</span>
                  <span class="block text-ink-gray-8">{{ i.message }}</span>
                </span>
              </button>
            </li>
            <li v-if="issueList.length > issueLimit" class="p-2 text-center"><Button size="sm" label="Show more" @click="issueLimit += 100" /></li>
          </ul>
          <div class="border-t border-outline-gray-1 p-2">
            <Button class="w-full" icon-left="lucide-refresh-cw" label="Re-run checks" :loading="rechecking" @click="recheck" />
          </div>
        </div>
        <div v-if="v.notes || v.review_comment" class="space-y-2 rounded-xl border border-outline-gray-2 bg-surface-base p-4 text-sm">
          <div v-if="v.notes"><div class="text-xs font-medium text-ink-gray-5">Notes</div>{{ v.notes }}</div>
          <div v-if="v.review_comment"><div class="text-xs font-medium text-ink-gray-5">Reviewer comment</div>{{ v.review_comment }}</div>
        </div>
      </aside>
    </div>
  </div>

  <EntryDialog v-model:open="entryOpen" :entry="selected" :slots="v?.slots || []" :week="v?.week" :faculty="data?.faculty || {}" :rooms="data?.rooms || []"
    :issues="selected ? byEntry[selected.name] || [] : []" :editable="!!v?.editable" @moved="reloadAll" />
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Alert, Badge, Button, Combobox, Dropdown, ErrorMessage, Select, Spinner, TabButtons, TextInput, call, createResource, dialog, toast } from 'frappe-ui'
import EmptyState from '@/components/EmptyState.vue'
import EntryDialog from '@/components/EntryDialog.vue'
import PageHead from '@/components/PageHead.vue'
import StatCard from '@/components/StatCard.vue'
import TimetableGrid from '@/components/TimetableGrid.vue'
import { usePlan } from '@/composables/usePlan'
import { useVersionActions } from '@/composables/useVersionActions'
import { session } from '@/session'
import { api, download } from '@/utils/api'
import { filterEntries, issuesByEntry } from '@/utils/grid'
import { APPROVAL_THEME, RUN_THEME, formatDuration, formatNumber, ruleLabel } from '@/utils/timetable'

const props = defineProps({ version: { type: String, required: true } })
const plan = usePlan()
const route = useRoute()
const router = useRouter()
const ver = createResource({ url: 'timetable_app.api.review.get_version', params: { version: props.version }, auto: true, onError: () => {} })
const ents = createResource({ url: 'timetable_app.api.review.get_entries', params: { version: props.version }, auto: true, onError: () => {} })
const v = computed(() => ver.data)
const data = computed(() => ents.data)
const entries = computed(() => data.value?.entries || [])
const checks = computed(() => v.value?.checks || [])
const violations = computed(() => v.value?.violations || [])
const byEntry = computed(() => issuesByEntry(checks.value))
const actions = useVersionActions(() => ver.reload())

const VIEWS = [
  { label: 'Cohort', value: 'cohort' }, { label: 'Faculty', value: 'faculty' }, { label: 'Room', value: 'room' },
  { label: 'Programme', value: 'programme' }, { label: 'Category', value: 'category' }, { label: 'All', value: 'all' },
]
const view = ref(route.query.view || 'cohort')
const value = ref(route.query.value || null)
const term = ref(null)
const search = ref('')
watch(view, () => (value.value = null))
watch([view, value], () => router.replace({ query: { ...route.query, view: view.value, value: value.value || undefined } }))
const viewLabel = computed(() => VIEWS.find((x) => x.value === view.value)?.label || '')

const valueOptions = computed(() => {
  const e = entries.value
  const uniq = (arr) => [...new Set(arr)].filter(Boolean).sort()
  switch (view.value) {
    case 'cohort': return uniq(e.flatMap((x) => x.cohorts)).filter((c) => c !== 'ALL')
    case 'faculty': return uniq(e.flatMap((x) => x.faculty_ids)).map((f) => ({ label: data.value.faculty[f] || f, value: f })).sort((a, b) => a.label.localeCompare(b.label))
    case 'room': return (data.value?.rooms || []).map((r) => ({ label: `${r.room_name} (${r.capacity || 0})`, value: r.room_id }))
    case 'programme': return uniq(e.flatMap((x) => x.program_ids))
    case 'category': return uniq(e.map((x) => x.category))
    default: return []
  }
})
const termOptions = computed(() => [{ label: 'All terms', value: 'ALL' }, ...[...new Set(entries.value.map((e) => e.term_id))].sort().map((t) => ({ label: t, value: t }))])
const shown = computed(() => {
  let list = filterEntries(entries.value, view.value, value.value, term.value)
  const q = search.value.trim().toLowerCase()
  if (view.value === 'all' && q)
    list = list.filter((e) => [e.course_code, e.course_name, e.room_name, e.category, ...e.faculty_ids, ...e.cohorts].some((x) => String(x || '').toLowerCase().includes(q)))
  return list
})

const issueTab = ref('hard')
const ruleFilter = ref(null)
const issueLimit = ref(100)
watch(issueTab, () => ((ruleFilter.value = null), (issueLimit.value = 100)))
const ruleChips = computed(() => {
  const list = issueTab.value === 'hard' ? checks.value : violations.value
  const counts = list.reduce((m, i) => ((m[i.rule] = (m[i.rule] || 0) + 1), m), {})
  return [{ label: `All ${list.length}`, value: '__all' }, ...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([r, n]) => ({ label: `${ruleLabel(r)} ${n}`, value: r }))]
})
const showIssues = ref(true)
const setTimeout = window.setTimeout.bind(window)
const issueList = computed(() => {
  const list = issueTab.value === 'hard' ? checks.value : violations.value
  return ruleFilter.value && ruleFilter.value !== '__all' ? list.filter((i) => i.rule === ruleFilter.value) : list
})

const selected = ref(null)
const entryOpen = ref(false)
function openEntry(e) {
  selected.value = entries.value.find((x) => x.name === e.name) || e
  entryOpen.value = true
}
function focusIssue(i) {
  const name = i.entries?.[0] || entries.value.find((e) => e.session_key === i.session_key)?.name
  const e = entries.value.find((x) => x.name === name)
  if (e) {
    // show the context: cohort view for cohort clashes, room for rooms, faculty otherwise
    if (i.rule?.startsWith('room') && e.room_id) { view.value = 'room'; setTimeout(() => (value.value = e.room_id)) }
    else if (i.rule === 'cohort_clash' && i.message.match(/Cohort ([^ ]+?)[,:]/)) { view.value = 'cohort'; setTimeout(() => (value.value = i.message.match(/Cohort ([^ ]+?)[,:]/)[1])) }
    else if (e.faculty_ids[0]) { view.value = 'faculty'; setTimeout(() => (value.value = e.faculty_ids[0])) }
    openEntry(e)
  } else if (i.faculty_id) { view.value = 'faculty'; setTimeout(() => (value.value = i.faculty_id)) }
  else if (i.cohort) { view.value = 'cohort'; setTimeout(() => (value.value = i.cohort)) }
}

async function onDrop({ entry, day_index, slot_index }) {
  try {
    const r = await call('timetable_app.api.review.move_entry', { entry: entry.name, day_index, slot_index })
    if (r.saved) {
      toast.success('Session moved')
      return reloadAll()
    }
    dialog.confirm({
      title: 'This move creates clashes',
      message: r.issues.map((i) => `• ${i.message}`).join('\n'),
      confirmLabel: 'Move anyway',
      actions: [{ label: 'Choose slot & room…', onClick: ({ close }) => { close(); openEntry(entry) } }],
      onConfirm: async () => {
        await api('timetable_app.api.review.move_entry', { entry: entry.name, day_index, slot_index, force: 1 }, { silent: true })
        toast.success('Moved with clashes')
        reloadAll()
      },
    })
  } catch (e) {
    toast.error(e.messages?.[0] || e.message)
  }
}

function reloadAll() {
  ver.reload().catch(() => {})
  ents.reload().catch(() => {})
  plan.reload()
}
const rechecking = ref(false)
async function recheck() {
  rechecking.value = true
  try {
    await api('timetable_app.api.scheduler.rerun_checks', { version: props.version })
    await ver.reload()
    toast.success('Checks updated')
  } finally {
    rechecking.value = false
  }
}

const menu = computed(() => {
  const x = v.value
  if (!x || x.run_status !== 'Completed') return []
  const row = { ...x, name: x.name }
  const m = []
  const editable = ['Draft', 'Changes Requested'].includes(x.approval_status)
  if (session.is_manager && editable) m.push({ label: 'Submit for approval', icon: 'lucide-send', onClick: () => actions.submit(row) })
  if (session.is_approver && x.approval_status === 'Submitted') {
    m.push({ label: 'Approve', icon: 'lucide-badge-check', onClick: () => actions.approve(row) })
    m.push({ label: 'Request changes', icon: 'lucide-message-square-warning', onClick: () => actions.requestChanges(row) })
  }
  if (session.is_manager && x.plan_status !== 'Finalised') m.push({ label: 'Create editable copy', icon: 'lucide-copy', onClick: () => actions.copy(row) })
  if (session.is_manager) m.push({ label: 'Rename', icon: 'lucide-pencil', onClick: () => actions.rename(row) })
  m.push({ label: 'Reports', icon: 'lucide-file-spreadsheet', onClick: () => router.push({ name: 'Reports', params: { plan: plan.name }, query: { version: x.name } }) })
  if (x.has_log) m.push({ label: 'Solver log', icon: 'lucide-scroll-text', onClick: showLog })
  return m
})
async function showLog() {
  const log = await api('timetable_app.api.review.get_log', { version: props.version })
  const w = window.open('', '_blank')
  if (w) {
    w.document.title = 'Solver log'
    const pre = w.document.createElement('pre')
    pre.textContent = log || '(empty)'
    w.document.body.appendChild(pre)
  }
}
</script>
