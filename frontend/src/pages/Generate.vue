<template>
  <PageHead title="Check & generate" />
  <div class="tt-page tt-narrow space-y-6">
    <PageIntro title="Check & generate" icon="lucide-play" description="Validate the data, then let the solver build a clash-free timetable in the background." />
    <!-- Running -->
    <section v-if="runningVersion" class="rounded-lg border border-outline-blue-2 bg-surface-blue-1 p-5">
      <div class="flex items-center gap-3">
        <Spinner class="size-5 text-ink-blue-7" />
        <div>
          <h2 class="font-medium text-ink-gray-9">Generating {{ runningLabel }}</h2>
          <p class="text-sm text-ink-gray-6">{{ progress?.message || 'Waiting for the worker…' }}</p>
        </div>
        <Button v-if="session.is_manager" class="ml-auto" theme="red" variant="subtle" label="Stop" :loading="cancelling" @click="cancel" />
      </div>
      <Progress class="mt-4" :value="pct" size="md" />
      <div class="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><div class="text-xs text-ink-gray-5">Elapsed</div><div class="tabular-nums">{{ formatDuration(elapsed) }} / {{ formatDuration(progress?.time_limit) }}</div></div>
        <div><div class="text-xs text-ink-gray-5">Timetables found</div><div class="tabular-nums">{{ progress?.solutions ?? 0 }}</div></div>
        <div><div class="text-xs text-ink-gray-5">Penalty score</div><div class="tabular-nums">{{ formatNumber(progress?.objective) }}</div></div>
        <div><div class="text-xs text-ink-gray-5">Sessions</div><div class="tabular-nums">{{ progress?.sessions ?? '—' }}</div></div>
      </div>
      <p class="mt-3 text-xs text-ink-gray-5">Lower penalty is better. You can leave this page; the run continues on the server. Stopping keeps the best timetable found so far.</p>
      <p v-if="progress?.stage === 'queued' && queuedLong" class="mt-2 text-sm text-ink-amber-7">Still queued. Make sure a background worker is running (<code>bench start</code> or the long-queue worker in production).</p>
    </section>

    <!-- Readiness -->
    <section class="rounded-xl border border-outline-gray-2 bg-surface-base p-5">
      <div class="flex flex-wrap items-center gap-3">
        <div>
          <h2 class="font-medium text-ink-gray-8">1. Readiness check</h2>
          <p class="text-sm text-ink-gray-5">Validates the data and finds problems that would make a timetable impossible.</p>
        </div>
        <Button class="ml-auto" icon-left="lucide-list-checks" :loading="checking" label="Run check" @click="runCheck" />
      </div>
      <div v-if="readiness" class="mt-4 space-y-4">
        <div class="flex flex-wrap items-center gap-3 text-sm">
          <Badge :theme="readiness.ok ? 'green' : 'red'" size="lg" :label="readiness.ok ? 'Ready to generate' : `${readiness.errors} blocking problems`" />
          <span v-if="readiness.stats?.sessions" class="text-ink-gray-6">{{ readiness.stats.sessions }} sessions · {{ readiness.stats.sections }} sections · {{ readiness.stats.cohorts }} cohorts · {{ readiness.stats.faculty }} faculty · {{ readiness.stats.rooms }} rooms</span>
          <span class="text-ink-gray-5">Checked {{ timeAgo(readiness.checked_on) }}</span>
        </div>
        <IssueList :issues="readiness.issues" />
      </div>
    </section>

    <!-- Generate -->
    <section class="rounded-xl border border-outline-gray-2 bg-surface-base p-5">
      <h2 class="font-medium text-ink-gray-8">2. Generate a timetable</h2>
      <p class="text-sm text-ink-gray-5">Runs the CP-SAT solver in the background with the current <router-link class="underline" :to="{ name: 'Rules', params: { plan: plan.name } }">rules & preferences</router-link>.</p>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <TextInput v-model="form.label" label="Version name" placeholder="e.g. Draft 1" />
        <TextInput v-model.number="form.time_limit" type="number" label="Time limit (minutes)" />
        <Select v-model="form.hint_from" class="w-full" label="Start from" description="Re-using a previous timetable makes the solver much faster."
          :options="[{ label: 'Scratch', value: '' }, ...completed.map((v) => ({ label: v.version_label, value: v.name }))]" />
      </div>
      <TextInput v-model="form.notes" class="mt-4" label="Notes (optional)" placeholder="What changed in this run?" />
      <div class="mt-4 flex items-center gap-3">
        <Button variant="solid" icon-left="lucide-play" label="Generate" :loading="starting"
          :disabled="!session.is_manager || !!runningVersion || (readiness && !readiness.ok) || finalised" @click="generate" />
        <span v-if="finalised" class="text-sm text-ink-gray-6">The plan is finalised; reopen it from Versions to generate again.</span>
        <span v-else-if="!readiness" class="text-sm text-ink-gray-6">Run the readiness check first.</span>
        <span v-else-if="!readiness.ok" class="text-sm text-ink-red-7">Fix the blocking problems first.</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Button, Progress, Select, Spinner, TextInput, call, createResource, toast } from 'frappe-ui'
import IssueList from '@/components/IssueList.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import { usePlan } from '@/composables/usePlan'
import { useProgress } from '@/composables/useProgress'
import { session } from '@/session'
import { api } from '@/utils/api'
import { timeAgo } from '@/utils/time'
import { formatDuration, formatNumber } from '@/utils/timetable'

const plan = usePlan()
const router = useRouter()
const checking = ref(false)
const starting = ref(false)
const cancelling = ref(false)
const readiness = ref(null)
const versions = createResource({ url: 'timetable_app.api.review.list_versions', params: { plan: plan.name }, auto: true, onError: () => {} })
const completed = computed(() => (versions.data || []).filter((v) => v.run_status === 'Completed'))
const finalised = computed(() => plan.overview.data?.plan?.status === 'Finalised')
const form = reactive({ label: '', time_limit: null, hint_from: '', notes: '' })
watch(() => plan.overview.data?.plan?.time_limit, (t) => form.time_limit ??= t, { immediate: true })

// last saved readiness result
call('frappe.client.get_value', { doctype: 'TT Plan', filters: plan.name, fieldname: 'readiness' })
  .then((r) => { if (r?.readiness && !readiness.value) readiness.value = JSON.parse(r.readiness) })
  .catch(() => {})

const runningVersion = ref(null)
const runningLabel = computed(() => (versions.data || []).find((v) => v.name === runningVersion.value)?.version_label || '')
watch(() => plan.overview.data?.running, (v) => { if (v) runningVersion.value = v }, { immediate: true })
const live = useProgress(runningVersion, onDone)
const progress = computed(() => live.value?.progress)
const elapsed = computed(() => {
  const p = progress.value
  if (!p) return 0
  if (p.stage === 'solving' && p.started) return Math.max(0, now.value / 1000 - p.started)
  return p.elapsed || 0
})
const pct = computed(() => {
  const p = progress.value
  if (!p || !p.time_limit) return p?.stage === 'saving' ? 100 : 2
  return p.stage === 'saving' ? 100 : Math.min(99, Math.round((100 * elapsed.value) / p.time_limit))
})
const queuedSince = ref(Date.now())
const now = ref(Date.now())
const tick = setInterval(() => (now.value = Date.now()), 1000)
onBeforeUnmount(() => clearInterval(tick))
const queuedLong = computed(() => now.value - queuedSince.value > 30000)

function onDone(v) {
  runningVersion.value = null
  plan.reload()
  versions.reload()
  call('timetable_app.api.scheduler.get_progress', { version: v }).then((r) => {
    if (r.run_status === 'Completed') {
      toast.success('Timetable generated', { action: { label: 'Open', onClick: () => router.push({ name: 'Review', params: { plan: plan.name, version: v } }) } })
      router.push({ name: 'Review', params: { plan: plan.name, version: v } })
    } else toast.error(`Generation ${r.run_status.toLowerCase()}`, { description: (r.error || '').split('\n')[0], duration: 10000 })
  })
}

async function runCheck() {
  checking.value = true
  try {
    readiness.value = await api('timetable_app.api.scheduler.check_readiness', { plan: plan.name })
    plan.reload()
  } finally {
    checking.value = false
  }
}
async function generate() {
  starting.value = true
  try {
    const v = await api('timetable_app.api.scheduler.generate', { plan: plan.name, label: form.label || null, time_limit: form.time_limit || null, hint_from: form.hint_from || null, notes: form.notes || null })
    queuedSince.value = Date.now()
    runningVersion.value = v
    versions.reload()
    plan.reload()
    toast.success('Generation started')
  } finally {
    starting.value = false
  }
}
async function cancel() {
  cancelling.value = true
  try {
    await api('timetable_app.api.scheduler.cancel', { version: runningVersion.value })
    toast.info('Stopping… the best timetable found so far will be kept.')
  } finally {
    cancelling.value = false
  }
}
</script>
