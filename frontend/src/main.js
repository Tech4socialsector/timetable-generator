import { createApp } from 'vue'
import { setConfig, frappeRequest, toast } from 'frappe-ui'
import 'frappe-ui/style.css'
import './index.css'
import App from './App.vue'
import router from './router'
import { errorMessage, stripHtml } from './utils/api'

setConfig('resourceFetcher', frappeRequest)
setConfig('fallbackErrorHandler', (e) => toast.error(errorMessage(e)))
// msgprint / alerts sent by the server with a successful response
setConfig('serverMessagesHandler', (messages) => {
  for (const raw of messages || []) {
    let m = raw
    try { m = typeof raw === 'string' ? JSON.parse(raw) : raw } catch { /* plain text */ }
    const text = stripHtml(m?.message ?? m)
    if (!text) continue
    const tone = m?.indicator
    if (tone === 'red') toast.error(text)
    else if (tone === 'orange' || tone === 'yellow') toast.warning(text, { duration: 8000 })
    else toast.info(text)
  }
})

createApp(App).use(router).mount('#app')
