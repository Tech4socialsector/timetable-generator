import { createRouter, createWebHistory } from 'vue-router'
import { loadSession, session } from './session'

const routes = [
  { path: '/', name: 'Plans', component: () => import('./pages/Plans.vue') },
  {
    path: '/plans/:plan',
    component: () => import('./components/PlanLayout.vue'),
    props: true,
    children: [
      { path: '', name: 'Overview', component: () => import('./pages/Overview.vue') },
      { path: 'setup', name: 'PlanSetup', component: () => import('./pages/PlanSetup.vue') },
      { path: 'sections', name: 'Sections', component: () => import('./pages/Sections.vue') },
      { path: 'faculty', name: 'Faculty', component: () => import('./pages/Faculty.vue') },
      { path: 'rooms', name: 'Rooms', component: () => import('./pages/Rooms.vue') },
      { path: 'categories', name: 'Categories', component: () => import('./pages/Categories.vue') },
      { path: 'meetings', name: 'Meetings', component: () => import('./pages/Meetings.vue') },
      { path: 'import', name: 'Import', component: () => import('./pages/Import.vue') },
      { path: 'rules', name: 'Rules', component: () => import('./pages/Rules.vue') },
      { path: 'generate', name: 'Generate', component: () => import('./pages/Generate.vue') },
      { path: 'versions', name: 'Versions', component: () => import('./pages/Versions.vue') },
      { path: 'versions/:version', name: 'Review', component: () => import('./pages/Review.vue'), props: true },
      { path: 'reports', name: 'Reports', component: () => import('./pages/Reports.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('./pages/NotFound.vue') },
]

const router = createRouter({ history: createWebHistory('/timetable'), routes })

router.beforeEach(async () => {
  try {
    await loadSession()
  } catch {
    window.location.href = `/login?redirect-to=${encodeURIComponent(window.location.pathname)}`
    return false
  }
  if (!session.has_access) {
    window.location.href = '/app'
    return false
  }
})

export default router
