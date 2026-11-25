import { call, toast } from 'frappe-ui'

export function errorMessage(e) {
  if (!e) return 'Something went wrong'
  const msgs = e.messages?.filter(Boolean)
  if (msgs?.length) return stripHtml(msgs[msgs.length - 1])
  return stripHtml(e.message || String(e))
}

export function stripHtml(s) {
  const div = document.createElement('div')
  div.innerHTML = String(s ?? '')
  return div.textContent || div.innerText || ''
}

// call() that shows a toast on failure and re-throws
export async function api(method, args = {}, { silent = false } = {}) {
  try {
    return await call(method, args)
  } catch (e) {
    if (!silent) toast.error(errorMessage(e))
    throw e
  }
}

export function download(method, args = {}) {
  const qs = new URLSearchParams(args).toString()
  window.open(`/api/method/${method}${qs ? `?${qs}` : ''}`, '_blank')
}
