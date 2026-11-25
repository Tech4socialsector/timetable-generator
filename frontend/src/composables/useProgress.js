import { onBeforeUnmount, ref, watch } from 'vue'
import { call } from 'frappe-ui'
import { getSocket } from '@/socket'

// Live progress of a generation run: socket events with a polling fallback.
export function useProgress(versionRef, onDone) {
  const state = ref(null)
  let timer = null
  let socket = null

  const handler = (data) => {
    if (data?.version !== versionRef.value) return
    state.value = { ...(state.value || {}), progress: data, run_status: data.run_status || state.value?.run_status }
    if (data.stage === 'done') finish()
  }

  async function poll() {
    if (!versionRef.value) return
    try {
      const r = await call('timetable_app.api.scheduler.get_progress', { version: versionRef.value })
      state.value = r
      if (!['Queued', 'Running'].includes(r.run_status)) finish()
    } catch {
      /* keep polling */
    }
  }

  function start() {
    stop()
    if (!versionRef.value) return
    poll()
    timer = setInterval(poll, 4000)
    try {
      socket = getSocket()
      socket.on('tt_progress', handler)
    } catch {
      socket = null
    }
  }
  function stop() {
    clearInterval(timer)
    timer = null
    socket?.off('tt_progress', handler)
  }
  function finish() {
    const v = versionRef.value
    stop()
    onDone?.(v)
  }

  watch(versionRef, start, { immediate: true })
  onBeforeUnmount(stop)
  return state
}
