<template>
  <Teleport to="body">
    <Transition enter-active-class="transition-opacity duration-200" leave-active-class="transition-opacity duration-150" enter-from-class="opacity-0" leave-to-class="opacity-0">
      <div v-if="open" class="fixed inset-0 z-40" style="background: rgba(15, 23, 42, 0.28)" aria-hidden="true" @click="close" />
    </Transition>
    <Transition enter-active-class="transition-transform duration-200 ease-out" leave-active-class="transition-transform duration-150 ease-in" enter-from-class="translate-x-full" leave-to-class="translate-x-full">
      <aside v-if="open" ref="panel" role="dialog" aria-modal="true" :aria-label="title"
        class="fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-surface-base"
        :style="{ maxWidth: width, boxShadow: '-12px 0 40px rgba(15, 23, 42, 0.18)' }">
        <header class="flex items-start gap-3 border-b border-outline-gray-2 px-6 py-4">
          <div class="min-w-0 flex-1">
            <h2 class="truncate text-lg font-semibold text-ink-gray-9">{{ title }}</h2>
            <p v-if="subtitle" class="mt-0.5 truncate text-sm text-ink-gray-5">{{ subtitle }}</p>
          </div>
          <slot name="header-actions" />
          <Button icon="lucide-x" label="Close" variant="ghost" @click="close" />
        </header>
        <div class="tt-scroll flex-1 overflow-y-auto px-6 py-5"><slot /></div>
        <footer v-if="$slots.footer" class="flex items-center gap-2 border-t border-outline-gray-2 bg-surface-gray-1 px-6 py-3"><slot name="footer" /></footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Button } from 'frappe-ui'

const open = defineModel('open', { type: Boolean, default: false })
defineProps({ title: { type: String, default: '' }, subtitle: String, width: { type: String, default: '44rem' } })
const panel = ref(null)
let lastFocus = null
const close = () => (open.value = false)

// Esc closes the panel wherever focus is, unless another dialog (e.g. a confirmation) is open on top of it
function onKey(e) {
  if (e.key !== 'Escape' || !open.value || e.defaultPrevented) return
  const dialogs = [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')]
  if (dialogs.length && dialogs[dialogs.length - 1] !== panel.value) return
  e.preventDefault()
  close()
}
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

watch(open, async (o) => {
  if (o) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
  if (o) {
    lastFocus = document.activeElement
    await nextTick()
    panel.value?.querySelector('input:not([disabled]), textarea:not([disabled]), button:not([aria-label="Close"])')?.focus()
  } else lastFocus?.focus?.()
})
</script>
