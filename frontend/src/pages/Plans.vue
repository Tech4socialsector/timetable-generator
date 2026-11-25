<template>
  <div class="min-h-full bg-surface-gray-1">
    <header class="border-b border-outline-gray-2 bg-surface-base">
      <div class="mx-auto flex max-w-6xl items-center gap-3 px-6 py-4">
        <img :src="LOGO" alt="" class="size-8" />
        <span class="font-semibold text-ink-gray-9">Timetable</span>
        <span class="hidden text-sm text-ink-gray-5 sm:inline">Azim Premji University</span>
        <div class="ml-auto flex items-center gap-2">
          <Dropdown :options="userMenu">
            <template #trigger>
              <button type="button" class="flex items-center gap-2 rounded-full p-0.5 pr-2 hover:bg-surface-gray-2">
                <Avatar :label="session.full_name || session.user" :image="session.user_image" size="sm" />
                <span class="hidden text-sm text-ink-gray-7 sm:inline">{{ session.full_name }}</span>
              </button>
            </template>
          </Dropdown>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-6xl px-6 py-10">
      <div class="mb-8 flex flex-wrap items-end gap-4">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Timetable plans</h1>
          <p class="mt-1 text-sm text-ink-gray-5">Each plan is one campus and semester: its courses, faculty, rooms and timetable versions.</p>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <TextInput v-if="(plans.data || []).length > 3" v-model="q" type="search" placeholder="Search plans" class="w-56" />
          <Button v-if="session.is_manager" variant="solid" icon-left="lucide-plus" label="New plan" @click="openNew()" />
        </div>
      </div>

      <div v-if="plans.loading && !plans.data" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="n in 3" :key="n" class="h-48 animate-pulse rounded-xl border border-outline-gray-2 bg-surface-base" />
      </div>
      <EmptyState v-else-if="!plans.data?.length" icon="lucide-calendar-plus" title="No plans yet"
        description="Create a plan for a campus and semester, then import your course list workbook or enter the data by hand.">
        <Button v-if="session.is_manager" variant="solid" label="Create the first plan" @click="openNew()" />
      </EmptyState>
      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <router-link v-for="p in shown" :key="p.name" :to="{ name: 'Overview', params: { plan: p.name } }"
          class="group flex flex-col rounded-xl border border-outline-gray-2 bg-surface-base p-5 transition hover:-translate-y-0.5 hover:border-outline-gray-3 hover:shadow-md">
          <div class="flex items-start gap-3">
            <div class="flex size-10 shrink-0 items-center justify-center rounded-lg text-sm font-semibold" :style="chipStyle(p.campus || p.name)">
              {{ initials(p.campus || p.plan_name) }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="truncate font-semibold text-ink-gray-9">{{ p.plan_name }}</div>
              <div class="truncate text-sm text-ink-gray-5">{{ [p.campus, p.academic_year].filter(Boolean).join(' · ') || '—' }}</div>
            </div>
            <Badge :theme="statusTheme[p.status] || 'gray'" :label="p.running ? 'Generating' : p.status" />
          </div>
          <div class="mt-5">
            <div class="mb-1.5 flex justify-between text-xs text-ink-gray-5"><span>Workflow</span><span>{{ p.progress }} / 8 steps</span></div>
            <div class="flex gap-1">
              <span v-for="n in 8" :key="n" class="h-1.5 flex-1 rounded-full" :class="n <= p.progress ? 'bg-green-500' : 'bg-surface-gray-3'" />
            </div>
          </div>
          <dl class="mt-5 grid grid-cols-3 gap-2 text-center">
            <div class="rounded-lg bg-surface-gray-1 py-2"><dt class="text-xs text-ink-gray-5">Sections</dt><dd class="font-semibold tabular-nums text-ink-gray-8">{{ p.sections }}</dd></div>
            <div class="rounded-lg bg-surface-gray-1 py-2"><dt class="text-xs text-ink-gray-5">Faculty</dt><dd class="font-semibold tabular-nums text-ink-gray-8">{{ p.faculty }}</dd></div>
            <div class="rounded-lg bg-surface-gray-1 py-2"><dt class="text-xs text-ink-gray-5">Versions</dt><dd class="font-semibold tabular-nums text-ink-gray-8">{{ p.versions }}</dd></div>
          </dl>
          <div class="mt-4 flex items-center text-xs text-ink-gray-5">
            <span v-if="p.start_date">{{ fmtDate(p.start_date) }} – {{ fmtDate(p.end_date) }}</span>
            <span class="ml-auto inline-flex items-center gap-1 font-medium text-ink-gray-7 opacity-0 transition group-hover:opacity-100">Open <span class="lucide-arrow-right size-3.5" /></span>
          </div>
        </router-link>
      </div>
    </main>

    <Dialog v-model:open="showNew" title="New plan" size="lg">
      <form class="space-y-4" @submit.prevent="create">
        <TextInput v-model="form.plan_name" label="Plan name" placeholder="Bangalore Jan 2027" required />
        <div class="grid grid-cols-2 gap-3">
          <TextInput v-model="form.campus" label="Campus" placeholder="Bangalore" />
          <TextInput v-model="form.academic_year" label="Academic year" placeholder="2026-27" />
          <TextInput v-model="form.start_date" type="date" label="Semester starts" />
          <TextInput v-model="form.end_date" type="date" label="Semester ends" />
        </div>
        <Select v-if="plans.data?.length" v-model="form.copy_from" class="w-full" label="Start from"
          description="Copying brings over programmes, terms, categories, rooms, faculty, meetings and sections."
          :options="[{ label: 'An empty plan', value: '' }, ...plans.data.map((p) => ({ label: `Copy of ${p.plan_name}`, value: p.name }))]" />
        <ErrorMessage :message="error" />
        <div class="flex justify-end gap-2 pt-2">
          <Button label="Cancel" @click="showNew = false" />
          <Button type="submit" variant="solid" label="Create plan" :loading="creating" />
        </div>
      </form>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Avatar, Badge, Button, Dialog, Dropdown, ErrorMessage, Select, TextInput, call, createResource } from 'frappe-ui'
import EmptyState from '@/components/EmptyState.vue'
import { logout, session } from '@/session'
import { errorMessage } from '@/utils/api'
import { chipStyle } from '@/utils/colors'

const router = useRouter()
const LOGO = '/assets/timetable_app/images/logo.svg'
const statusTheme = { Setup: 'gray', Ready: 'blue', Generated: 'violet', Finalised: 'green' }
const plans = createResource({ url: 'timetable_app.api.session.list_plans', auto: true, onError: () => {} })
const q = ref('')
const shown = computed(() => (plans.data || []).filter((p) => !q.value || `${p.plan_name} ${p.campus || ''}`.toLowerCase().includes(q.value.toLowerCase())))
const showNew = ref(false)
const creating = ref(false)
const error = ref('')
const form = reactive({ plan_name: '', campus: '', academic_year: '', start_date: '', end_date: '', copy_from: '' })
const userMenu = [
  { label: 'Open Desk', icon: 'lucide-app-window', onClick: () => window.open('/app', '_blank') },
  { label: 'Log out', icon: 'lucide-log-out', onClick: logout },
]
const initials = (s) => String(s || '').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('')
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '…')

function openNew() {
  Object.assign(form, { plan_name: '', campus: '', academic_year: '', start_date: '', end_date: '', copy_from: '' })
  error.value = ''
  showNew.value = true
}
async function create() {
  if (!form.plan_name.trim()) return (error.value = 'Give the plan a name.')
  creating.value = true
  error.value = ''
  try {
    const name = await call('timetable_app.api.data_io.create_plan', { ...form, copy_from: form.copy_from || null, start_date: form.start_date || null, end_date: form.end_date || null })
    showNew.value = false
    router.push({ name: form.copy_from ? 'Overview' : 'Import', params: { plan: name } })
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    creating.value = false
  }
}
</script>
