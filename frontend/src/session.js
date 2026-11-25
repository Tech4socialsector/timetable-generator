import { reactive } from 'vue'
import { call } from 'frappe-ui'

export const session = reactive({
  loaded: false,
  user: null,
  full_name: '',
  roles: [],
  is_manager: false,
  is_approver: false,
  has_access: false,
})

export async function loadSession() {
  if (session.loaded) return session
  const boot = window.tt_session
  const data = boot && boot.user ? boot : await call('timetable_app.api.session.get_session')
  Object.assign(session, data, { loaded: true })
  return session
}

export function logout() {
  call('logout').finally(() => (window.location.href = '/login'))
}
