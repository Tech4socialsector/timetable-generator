<template>
  <div class="overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-base">
    <!-- toolbar -->
    <div class="flex flex-wrap items-center gap-2 border-b border-outline-gray-1 px-3 py-2.5">
      <TextInput v-model="search" type="search" :placeholder="searchPlaceholder" class="w-full sm:w-72" :debounce="150">
        <template #prefix><span class="lucide-search size-4 text-ink-gray-5" /></template>
      </TextInput>
      <Select v-for="f in filters" :key="f.key" :model-value="active[f.key] ?? null"
        :options="[{ label: `All ${f.label.toLowerCase()}`, value: '__all' }, ...f.options.map((o) => (typeof o === 'string' ? { label: o, value: o } : o))]"
        :placeholder="f.label" @update:model-value="(v) => (active[f.key] = v === '__all' ? null : v)">
        <template v-if="active[f.key] != null" #prefix><span class="size-1.5 rounded-full bg-surface-gray-9" /></template>
      </Select>
      <Button v-if="hasFilters || search" variant="ghost" icon-left="lucide-x" label="Clear" @click="clear" />
      <div class="ml-auto flex items-center gap-1.5">
        <span class="mr-1 text-sm tabular-nums text-ink-gray-5">{{ filtered.length === rows.length ? `${rows.length} records` : `${filtered.length} of ${rows.length}` }}</span>
        <Popover v-if="hideable.length">
          <template #trigger>
            <Button icon-left="lucide-columns-3" :label="`Columns ${visibleColumns.length}/${columns.length}`" />
          </template>
          <template #default="{ close }">
            <div class="w-72 rounded-lg border border-outline-gray-2 bg-surface-base p-2 text-sm" style="box-shadow: 0 12px 32px rgba(15, 23, 42, 0.14)">
              <div class="flex gap-1 border-b border-outline-gray-1 pb-2">
                <Button size="sm" label="All (Excel view)" @click="setAll(true)" />
                <Button v-if="hasEssential" size="sm" label="Essential" @click="setEssential" />
              </div>
              <div class="tt-scroll max-h-80 overflow-y-auto py-1">
                <label v-for="c in columns" :key="c.key" class="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-surface-gray-2" :class="c.sticky ? 'opacity-60' : ''">
                  <input type="checkbox" class="rounded border-outline-gray-3" :checked="isVisible(c)" :disabled="c.sticky" @change="toggle(c)" />
                  <span class="flex-1 truncate text-ink-gray-8">{{ c.label }}</span>
                  <span v-if="c.sticky" class="lucide-pin size-3 text-ink-gray-5" />
                </label>
              </div>
              <div class="flex justify-end border-t border-outline-gray-1 pt-2"><Button size="sm" variant="solid" label="Done" @click="close" /></div>
            </div>
          </template>
        </Popover>
        <Button :icon="dense ? 'lucide-rows-3' : 'lucide-rows-2'" :label="dense ? 'Comfortable rows' : 'Compact rows'" :tooltip="dense ? 'Comfortable rows' : 'Compact rows'" variant="ghost" @click="setDense(!dense)" />
        <slot name="toolbar" />
      </div>
    </div>
    <!-- table -->
    <div class="tt-scroll overflow-auto" :style="{ maxHeight }" @scroll="onScroll">
      <table class="tt-table text-left text-sm" :style="{ width: `max(100%, ${tableWidth}rem)` }">
        <colgroup><col v-for="c in visibleColumns" :key="c.key" :style="{ width: `${c.width || 9}rem` }" /></colgroup>
        <thead>
          <tr>
            <th v-for="c in visibleColumns" :key="c.key" scope="col"
              class="whitespace-nowrap border-b border-outline-gray-2 bg-surface-gray-1 px-3 text-xs font-medium text-ink-gray-5"
              :class="[dense ? 'py-1.5' : 'py-2.5', c.align === 'right' ? 'text-right' : '', stickyClass(c)]" :style="stickyStyle(c, true)"
              :aria-sort="sort.key === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : undefined">
              <button v-if="c.sortable !== false" type="button" class="group/sort inline-flex max-w-full items-center gap-1 hover:text-ink-gray-8" @click="sortBy(c.key)">
                <span class="truncate">{{ c.label }}</span>
                <span :class="sort.key === c.key ? (sort.dir === 1 ? 'lucide-arrow-up' : 'lucide-arrow-down') : 'lucide-arrow-up-down opacity-0 group-hover/sort:opacity-50'" class="size-3 shrink-0" />
              </button>
              <span v-else class="truncate">{{ c.label }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-if="loading && !rows.length">
            <tr v-for="n in 8" :key="n" class="border-b border-outline-gray-1">
              <td v-for="c in visibleColumns" :key="c.key" class="px-3 py-3"><div class="h-3 animate-pulse rounded bg-surface-gray-2" :style="{ width: `${40 + ((n * 17 + c.key.length * 7) % 50)}%` }" /></td>
            </tr>
          </template>
          <tr v-else-if="!filtered.length">
            <td :colspan="visibleColumns.length" class="px-3 py-14">
              <slot name="empty">
                <div class="sticky left-0 flex flex-col items-center gap-2 text-sm text-ink-gray-5" style="width: min(100%, 70vw)">
                  <span class="lucide-search-x size-6" />
                  {{ rows.length ? 'Nothing matches your search or filters.' : 'No records yet.' }}
                  <Button v-if="rows.length && (hasFilters || search)" size="sm" label="Clear search & filters" @click="clear" />
                </div>
              </slot>
            </td>
          </tr>
          <tr v-for="row in visible" v-else :key="row[rowKey]" class="group/row cursor-pointer focus:outline-none" tabindex="0"
            @click="emit('row-click', row)" @keydown.enter="emit('row-click', row)">
            <td v-for="c in visibleColumns" :key="c.key"
              class="max-w-0 border-b border-outline-gray-1 bg-surface-base px-3 transition-colors group-hover/row:bg-surface-gray-1 group-focus/row:bg-surface-gray-2"
              :class="[dense ? 'py-1.5' : 'py-2.5', c.class, c.align === 'right' ? 'text-right tabular-nums' : '', stickyClass(c)]" :style="stickyStyle(c)">
              <slot :name="`cell-${c.key}`" :row="row" :value="row[c.key]">
                <CellValue :value="c.format ? c.format(row) : row[c.key]" :type="c.type || (c.align === 'right' ? 'number' : 'text')" :spd="c.spd || 6" :slot-title="c.slotTitle || null" />
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="filtered.length > limit" class="border-t border-outline-gray-1 p-3 text-center">
        <Button :label="`Show ${Math.min(200, filtered.length - limit)} more`" @click="limit += 200" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Button, Popover, Select, TextInput } from 'frappe-ui'
import CellValue from './CellValue.vue'

const props = defineProps({
  columns: { type: Array, required: true }, // [{key, label, width(rem), align, sticky, type, essential, format, class, sortable}]
  rows: { type: Array, default: () => [] },
  loading: Boolean,
  rowKey: { type: String, default: 'name' },
  searchKeys: { type: Array, default: () => [] },
  searchPlaceholder: { type: String, default: 'Search' },
  filters: { type: Array, default: () => [] }, // [{key, label, options, match?(row, value)}]
  tableKey: { type: String, default: '' }, // remembers column choice per table
  maxHeight: { type: String, default: 'calc(100vh - 260px)' },
})
const emit = defineEmits(['row-click'])

// ---- persisted preferences (per viewer, best effort)
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)) } catch { return null } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } },
}
const colKey = computed(() => (props.tableKey ? `tt-cols:${props.tableKey}` : null))
const hidden = ref(new Set((colKey.value && store.get(colKey.value)) || []))
const dense = ref(!!store.get('tt-dense'))
const setDense = (v) => { dense.value = v; store.set('tt-dense', v) }
const persist = () => colKey.value && store.set(colKey.value, [...hidden.value])

const hideable = computed(() => props.columns.filter((c) => !c.sticky))
const hasEssential = computed(() => props.columns.some((c) => c.essential))
const isVisible = (c) => c.sticky || !hidden.value.has(c.key)
const visibleColumns = computed(() => props.columns.filter(isVisible))
function toggle(c) {
  const s = new Set(hidden.value)
  s.has(c.key) ? s.delete(c.key) : s.add(c.key)
  hidden.value = s
  persist()
}
function setAll() {
  hidden.value = new Set()
  persist()
}
function setEssential() {
  hidden.value = new Set(props.columns.filter((c) => !c.sticky && !c.essential).map((c) => c.key))
  persist()
}
const tableWidth = computed(() => visibleColumns.value.reduce((n, c) => n + (c.width || 9), 0))

// ---- pinned (sticky) columns
const scrolled = ref(false)
const onScroll = (e) => (scrolled.value = e.target.scrollLeft > 0)
const stickyCols = computed(() => visibleColumns.value.filter((c) => c.sticky))
function stickyStyle(c, head = false) {
  if (!c.sticky) return head ? { zIndex: 1 } : {}
  let left = 0
  for (const s of stickyCols.value) {
    if (s.key === c.key) break
    left += s.width || 9
  }
  return { position: 'sticky', left: `${left}rem`, zIndex: head ? 3 : 2 }
}
function stickyClass(c) {
  const last = stickyCols.value[stickyCols.value.length - 1]
  return c.sticky && last?.key === c.key && scrolled.value ? 'tt-sticky-edge' : ''
}

// ---- search / filter / sort
const search = ref('')
const active = reactive({})
const sort = reactive({ key: null, dir: 1 })
const limit = ref(200)
const hasFilters = computed(() => Object.values(active).some((v) => v != null))
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  let out = props.rows.filter((r) => {
    for (const f of props.filters) {
      const v = active[f.key]
      if (v == null) continue
      if (f.match ? !f.match(r, v) : String(r[f.key] ?? '') !== String(v)) return false
    }
    return !q || props.searchKeys.some((k) => String(r[k] ?? '').toLowerCase().includes(q))
  })
  if (sort.key) {
    const k = sort.key
    const col = props.columns.find((c) => c.key === k)
    const val = (r) => (col?.format ? col.format(r) : r[k]) ?? ''
    out = [...out].sort((a, b) => {
      const x = val(a), y = val(b)
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * sort.dir
    })
  }
  return out
})
const visible = computed(() => filtered.value.slice(0, limit.value))
watch([search, () => ({ ...active })], () => (limit.value = 200))
function sortBy(k) {
  if (sort.key === k) sort.dir = -sort.dir
  else Object.assign(sort, { key: k, dir: 1 })
}
function clear() {
  search.value = ''
  for (const k of Object.keys(active)) active[k] = null
}
</script>
