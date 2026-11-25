<template>
  <DesktopShell>
    <template #sidebar>
      <Sidebar v-model:collapsed="collapsed">
        <SidebarHeader :title="planTitle" :subtitle="subtitle" :logo="logo" :menu-items="menuItems" />
        <div class="flex-1 overflow-y-auto">
          <SidebarItem label="Overview" icon="lucide-layout-dashboard" :route="{ name: 'Overview', params: { plan } }" />
          <SidebarLabel>Setup &amp; data</SidebarLabel>
          <SidebarItem label="Term setup" icon="lucide-calendar-cog" :route="{ name: 'PlanSetup', params: { plan } }" />
          <SidebarItem label="Course list" icon="lucide-book-open" :suffix="count('TT Section')" :route="{ name: 'Sections', params: { plan } }" />
          <SidebarItem label="Faculty availability" icon="lucide-users" :suffix="count('TT Faculty')" :route="{ name: 'Faculty', params: { plan } }" />
          <SidebarItem label="Classrooms & labs" icon="lucide-door-open" :suffix="count('TT Room')" :route="{ name: 'Rooms', params: { plan } }" />
          <SidebarItem label="Course categories" icon="lucide-tags" :suffix="count('TT Category')" :route="{ name: 'Categories', params: { plan } }" />
          <SidebarItem label="Meetings" icon="lucide-calendar-clock" :suffix="count('TT Meeting')" :route="{ name: 'Meetings', params: { plan } }" />
          <SidebarItem label="Bulk upload" icon="lucide-upload" :route="{ name: 'Import', params: { plan } }" />
          <SidebarLabel>Scheduling</SidebarLabel>
          <SidebarItem label="Rules & preferences" icon="lucide-sliders-horizontal" :route="{ name: 'Rules', params: { plan } }" />
          <SidebarItem label="Check & generate" icon="lucide-play" :suffix="running ? 'Running' : ''" :route="{ name: 'Generate', params: { plan } }" />
          <SidebarItem label="Versions & approval" icon="lucide-layers" :route="{ name: 'Versions', params: { plan } }" :active="isVersions" />
          <SidebarItem label="Reports & exports" icon="lucide-file-spreadsheet" :route="{ name: 'Reports', params: { plan } }" />
        </div>
        <div class="border-t border-outline-gray-1 p-2">
          <Dropdown :options="userMenu" side="top" match-trigger-width>
            <template #trigger>
              <button type="button" class="flex w-full items-center gap-2 rounded-md p-1.5 text-left hover:bg-surface-gray-3" :aria-label="`Account: ${session.full_name}`">
                <Avatar :label="session.full_name || session.user" :image="session.user_image" size="sm" />
                <span v-if="!collapsed" class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium text-ink-gray-8">{{ session.full_name || session.user }}</span>
                  <span class="block truncate text-xs text-ink-gray-5">{{ roleLabel }}</span>
                </span>
                <span v-if="!collapsed" class="lucide-chevrons-up-down size-4 text-ink-gray-5" />
              </button>
            </template>
          </Dropdown>
        </div>
        <SidebarCollapseToggle />
      </Sidebar>
    </template>
    <div v-if="planCtx.overview.error" class="p-8">
      <Alert theme="red" title="Could not open this plan" :description="errorMessage(planCtx.overview.error)">
        <template #actions><Button label="All plans" :route="{ name: 'Plans' }" /></template>
      </Alert>
    </div>
    <div v-else class="min-h-[calc(100vh-3rem)] bg-surface-gray-1">
      <router-view :key="$route.params.version || 'page'" />
    </div>
  </DesktopShell>
</template>

<script setup>
import { computed, ref, toRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Alert,
  Avatar,
  Button,
  createResource,
  Dropdown,
  DesktopShell,
  Sidebar,
  SidebarCollapseToggle,
  SidebarHeader,
  SidebarItem,
  SidebarLabel,
} from 'frappe-ui'
import { providePlan } from '@/composables/usePlan'
import { logout, session } from '@/session'
import { errorMessage } from '@/utils/api'

const props = defineProps({ plan: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const logo = '/assets/timetable_app/images/logo.svg'

const planCtx = providePlan(toRef(props, 'plan'))
watch(() => props.plan, () => planCtx.reload(), { immediate: true })

const ov = computed(() => planCtx.overview.data)
const planTitle = computed(() => ov.value?.plan?.plan_name || props.plan)
const subtitle = computed(() => [ov.value?.plan?.campus, ov.value?.plan?.status].filter(Boolean).join(' · ') || 'Timetable')
const running = computed(() => !!ov.value?.running)
const isVersions = computed(() => ['Versions', 'Review'].includes(route.name))
const count = (dt) => {
  const n = ov.value?.counts?.[dt]
  return n ? String(n) : ''
}

const plans = createResource({ url: 'timetable_app.api.session.list_plans', auto: true, onError: () => {} })
const menuItems = computed(() => [
  {
    group: 'Switch plan',
    options: [
      ...(plans.data || []).map((p) => ({
        label: p.plan_name,
        icon: p.name === props.plan ? 'lucide-check' : 'lucide-calendar',
        onClick: () => router.push({ name: 'Overview', params: { plan: p.name } }),
      })),
      { label: 'All plans', icon: 'lucide-layout-grid', onClick: () => router.push({ name: 'Plans' }) },
    ],
  },
])
const roleLabel = computed(() => (session.is_manager ? 'Programme office' : session.is_approver ? 'Approver' : 'Viewer'))
const userMenu = computed(() => [
  { label: 'Open Desk', icon: 'lucide-app-window', onClick: () => window.open('/app/tt-plan', '_blank') },
  { label: 'Log out', icon: 'lucide-log-out', onClick: logout },
])
</script>
