<template>
  <PageHead title="Bulk upload">
    <Button icon-left="lucide-file-down" label="Download template" @click="download('timetable_app.api.data_io.download_template')" />
    <Button icon-left="lucide-download" label="Export current data" @click="download('timetable_app.api.data_io.export_inputs', { plan: plan.name })" />
  </PageHead>
  <div class="tt-page tt-narrow space-y-6">
    <PageIntro title="Bulk upload" icon="lucide-upload" description="Bring in a whole planning workbook at once. You can check it before anything is replaced." />
    <Alert v-if="!canEdit" theme="amber" title="Read only" description="Only the programme office can import data, and not while the plan is finalised." />
    <section class="rounded-xl border border-outline-gray-2 bg-surface-base p-5">
      <h2 class="font-medium text-ink-gray-8">1. Upload the planning workbook</h2>
      <p class="mt-1 text-sm text-ink-gray-5">
        An .xlsx file with the sheets <b>Programs, Terms, Categories, Rooms, Faculty, Meeting Slots</b> and <b>Sections</b> (the same format the command-line generator uses).
        If it also has a <b>Timetable</b> sheet, that timetable can be imported as a version.
      </p>
      <FileUploader class="mt-4" file-types=".xlsx" :validate-file="validate" @success="onUploaded">
        <template #default="{ openFileSelector, uploading, progress, error }">
          <div class="flex items-center gap-3">
            <Button :disabled="!canEdit" :loading="uploading" icon-left="lucide-upload" :label="uploading ? `Uploading ${progress}%` : file ? 'Choose another file' : 'Choose file'" @click="openFileSelector" />
            <span v-if="file" class="text-sm text-ink-gray-7">{{ file.file_name }}</span>
          </div>
          <ErrorMessage class="mt-2" :message="error" />
        </template>
      </FileUploader>
    </section>

    <section v-if="file" class="rounded-xl border border-outline-gray-2 bg-surface-base p-5">
      <h2 class="font-medium text-ink-gray-8">2. Check the contents</h2>
      <div v-if="preview.loading" class="flex items-center gap-2 py-6 text-sm text-ink-gray-5"><Spinner class="size-4" /> Reading workbook…</div>
      <ErrorMessage v-else-if="preview.error" :message="preview.error" />
      <div v-else-if="preview.data" class="mt-3 space-y-4">
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div v-for="(n, s) in preview.data.sheets" :key="s" class="rounded border border-outline-gray-2 p-2">
            <div class="text-xs text-ink-gray-5">{{ s }}</div>
            <div class="text-lg font-semibold tabular-nums" :class="preview.data.missing_sheets.includes(s) ? 'text-ink-red-7' : 'text-ink-gray-9'">
              {{ preview.data.missing_sheets.includes(s) ? 'missing' : n }}
            </div>
          </div>
        </div>
        <IssueList :issues="preview.data.issues" empty-text="The workbook looks good." />
      </div>
    </section>

    <section v-if="preview.data" class="rounded-xl border border-outline-gray-2 bg-surface-base p-5">
      <h2 class="font-medium text-ink-gray-8">3. Import</h2>
      <p class="mt-1 text-sm text-ink-gray-5">Importing <b>replaces</b> all programmes, terms, categories, rooms, faculty, meetings and sections in this plan. Existing timetable versions are kept.</p>
      <Checkbox v-if="preview.data.timetable_rows" v-model="withTimetable" class="mt-3"
        :label="`Also import the existing timetable (${preview.data.timetable_rows} sessions) as a version`"
        description="Useful to review it, check it for clashes, or use it as the starting point for the solver." />
      <div class="mt-4 flex items-center gap-3">
        <Button variant="solid" :loading="importing" :disabled="!canEdit" label="Replace plan data" @click="confirmImport" />
        <span v-if="preview.data.errors" class="text-sm text-ink-amber-7">The workbook has {{ preview.data.errors }} blocking problems; you can import and fix them in the app.</span>
      </div>
      <div v-if="result" class="mt-4 space-y-2 rounded bg-surface-gray-1 p-3 text-sm">
        <div class="font-medium text-ink-gray-8">Imported</div>
        <div class="flex flex-wrap gap-x-4 gap-y-1 text-ink-gray-7">
          <span v-for="(n, dt) in result.counts" :key="dt">{{ dt.replace('TT ', '') }}: <b>{{ n }}</b></span>
        </div>
        <div v-if="result.skipped.length">
          <div class="text-ink-amber-7">{{ result.skipped.length }} rows were skipped:</div>
          <ul class="max-h-40 list-disc overflow-y-auto pl-5 text-ink-gray-6"><li v-for="s in result.skipped" :key="s">{{ s }}</li></ul>
        </div>
        <div class="flex gap-2 pt-1">
          <Button variant="solid" label="Check readiness" :route="{ name: 'Generate', params: { plan: plan.name } }" />
          <Button v-if="result.version" label="Open imported timetable" :route="{ name: 'Review', params: { plan: plan.name, version: result.version } }" />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Alert, Button, Checkbox, ErrorMessage, FileUploader, Spinner, createResource, dialog, toast } from 'frappe-ui'
import IssueList from '@/components/IssueList.vue'
import PageHead from '@/components/PageHead.vue'
import PageIntro from '@/components/PageIntro.vue'
import { useEditing } from '@/composables/useEditing'
import { usePlan } from '@/composables/usePlan'
import { api, download } from '@/utils/api'

const plan = usePlan()
const { canEdit } = useEditing()
const file = ref(null)
const withTimetable = ref(true)
const importing = ref(false)
const result = ref(null)
const preview = createResource({ url: 'timetable_app.api.data_io.preview_workbook', onError: () => {} })
const validate = (f) => (!f.name.toLowerCase().endsWith('.xlsx') ? 'Choose an .xlsx file' : null)

function onUploaded(f) {
  file.value = f
  result.value = null
  preview.submit({ file_url: f.file_url, plan: plan.name }).catch(() => {})
}
function confirmImport() {
  dialog.confirm({
    title: 'Replace plan data?',
    message: 'All current setup data in this plan will be replaced by the workbook contents.',
    confirmLabel: 'Replace',
    onConfirm: doImport,
  })
}
async function doImport() {
  importing.value = true
  try {
    result.value = await api('timetable_app.api.data_io.import_workbook', { plan: plan.name, file_url: file.value.file_url, import_timetable: withTimetable.value ? 1 : 0 })
    toast.success('Workbook imported')
    plan.reload()
  } finally {
    importing.value = false
  }
}
</script>
