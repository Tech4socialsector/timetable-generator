export function timeAgo(value) {
  if (!value) return ''
  const t = new Date(String(value).replace(' ', 'T'))
  const s = Math.round((Date.now() - t.getTime()) / 1000)
  if (Number.isNaN(s)) return String(value)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return t.toLocaleDateString()
}
export const formatDateTime = (v) => (v ? new Date(String(v).replace(' ', 'T')).toLocaleString() : '—')
