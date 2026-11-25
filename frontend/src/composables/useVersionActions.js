import { useRouter } from 'vue-router'
import { dialog, toast } from 'frappe-ui'
import { api } from '@/utils/api'
import { usePlan } from './usePlan'

export function useVersionActions(onChange) {
  const plan = usePlan()
  const router = useRouter()
  const done = (msg) => {
    toast.success(msg)
    plan.reload()
    onChange?.()
  }
  return {
    submit(v) {
      dialog.prompt({
        title: `Submit ${v.version_label} for approval`,
        fields: [{ name: 'comment', label: 'Note for the approver', type: 'textarea' }],
        confirmLabel: 'Submit',
        onConfirm: async ({ values }) => {
          await api('timetable_app.api.review.submit_version', { version: v.name, comment: values.comment || null }, { silent: true })
          done('Submitted for approval')
        },
      })
    },
    approve(v) {
      dialog.prompt({
        title: `Approve ${v.version_label}`,
        message: v.hard_issues ? `This version has ${v.hard_issues} hard issues. Explain why it is approved anyway.` : 'Approving finalises the plan and replaces any previously approved version.',
        fields: [{ name: 'comment', label: 'Comment', type: 'textarea', required: !!v.hard_issues }],
        confirmLabel: 'Approve',
        onConfirm: async ({ values }) => {
          await api('timetable_app.api.review.approve_version', { version: v.name, comment: values.comment || null }, { silent: true })
          done('Version approved')
        },
      })
    },
    requestChanges(v) {
      dialog.prompt({
        title: 'Request changes',
        fields: [{ name: 'comment', label: 'What needs to change?', type: 'textarea', required: true }],
        confirmLabel: 'Send back',
        onConfirm: async ({ values }) => {
          await api('timetable_app.api.review.request_changes', { version: v.name, comment: values.comment }, { silent: true })
          done('Sent back for changes')
        },
      })
    },
    copy(v) {
      dialog.prompt({
        title: 'Create an editable copy',
        fields: [{ name: 'label', label: 'Name', defaultValue: `${v.version_label} (copy)`, required: true }],
        confirmLabel: 'Create copy',
        onConfirm: async ({ values }) => {
          const name = await api('timetable_app.api.review.copy_version', { version: v.name, label: values.label }, { silent: true })
          done('Copy created')
          router.push({ name: 'Review', params: { plan: plan.name, version: name } })
        },
      })
    },
    rename(v) {
      dialog.prompt({
        title: 'Rename version',
        fields: [{ name: 'label', label: 'Name', defaultValue: v.version_label, required: true }, { name: 'notes', label: 'Notes', type: 'textarea', defaultValue: v.notes || '' }],
        confirmLabel: 'Save',
        onConfirm: async ({ values }) => {
          await api('timetable_app.api.review.update_version', { version: v.name, label: values.label, notes: values.notes }, { silent: true })
          done('Saved')
        },
      })
    },
    remove(v, after) {
      dialog.danger({
        title: `Delete ${v.version_label}?`,
        message: 'The timetable and its sessions are deleted permanently.',
        onConfirm: async () => {
          await api('frappe.client.delete', { doctype: 'TT Version', name: v.name }, { silent: true })
          done('Version deleted')
          after?.()
        },
      })
    },
    reopen() {
      dialog.confirm({
        title: 'Reopen the plan?',
        message: 'The approved version stays approved, but data can be edited and new versions generated again.',
        confirmLabel: 'Reopen',
        onConfirm: async () => {
          await api('timetable_app.api.review.reopen_plan', { plan: plan.name }, { silent: true })
          done('Plan reopened')
        },
      })
    },
  }
}
