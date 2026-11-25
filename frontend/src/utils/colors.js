// Category / programme colours: soft background + readable text, light and dark friendly enough.
const PALETTE = [
  ['#dbeafe', '#1e40af'], ['#dcfce7', '#166534'], ['#fef3c7', '#92400e'], ['#ede9fe', '#5b21b6'], ['#fce7f3', '#9d174d'],
  ['#ccfbf1', '#115e59'], ['#ffedd5', '#9a3412'], ['#cffafe', '#155e75'], ['#fee2e2', '#991b1b'], ['#e0e7ff', '#3730a3'],
  ['#ecfccb', '#3f6212'], ['#f3e8ff', '#6b21a8'],
]
export function colorIndex(key) {
  let h = 0
  for (const ch of String(key || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h % PALETTE.length
}
export function chipStyle(key) {
  const [bg, fg] = PALETTE[colorIndex(key)]
  return { backgroundColor: bg, color: fg }
}
export function cardStyle(key) {
  const [bg, fg] = PALETTE[colorIndex(key)]
  return { backgroundColor: bg, color: fg, borderColor: fg + '33' }
}
