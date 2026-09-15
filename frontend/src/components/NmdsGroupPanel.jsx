'use client'

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, X } from 'lucide-react'
import FileUpload from './FileUpload'
import NmdsConceptFields from './NmdsConceptFields'
import Button from './ui/Button'
import { nmdsFieldsToList } from '../lib/nmdsConcepts'
import { NMDS_TOPICS } from '../lib/nmdsConcepts'

// Per-metadata-group concept metadata: upload box below each group's card.
// Uploading (or "View / edit fields") opens a modal with the topic-by-topic
// field editor. Supports NMDS or SDG via the standard* props.
// When hideFieldEditor is true (SDG sheet already shows the same fields),
// only upload / apply-to-all / save remain.
export default function NmdsGroupPanel({
  fields,
  onFieldChange,
  onFileSelected,
  file,
  appliedFrom,
  parsing,
  parseError,
  fileMismatch,
  modalOpen,
  onOpenModal,
  onCloseModal,
  groupLabel,
  onSaveGroup,
  onApplyToAll,
  canApplyToAll,
  appliedToAll,
  standardName = 'NMDS',
  topics = NMDS_TOPICS,
  placeholders = {},
  fieldsToList = nmdsFieldsToList,
  hideFieldEditor = false,
}) {
  const filledCount = fieldsToList(fields).length
  const prefilledHint = appliedFrom?.fileName || (appliedFrom ? 'Fields filled in' : null)

  useEffect(() => {
    if (!modalOpen || hideFieldEditor) return undefined
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [modalOpen, hideFieldEditor])

  const modal = !hideFieldEditor && modalOpen && typeof document !== 'undefined'
    ? createPortal(
      <div
        className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
        role="dialog"
        aria-modal="true"
        aria-labelledby="nmds-modal-title"
      >
        <div className="flex h-[min(680px,90vh)] w-full max-w-[860px] flex-col overflow-hidden rounded-[14px] bg-surface shadow-dhara">
          <div className="relative flex flex-shrink-0 items-start justify-between gap-4 border-b border-line bg-cream px-6 pb-3.5 pt-4">
            <div className="min-w-0">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-teal">{standardName} concept metadata</div>
              <div id="nmds-modal-title" className="truncate text-xl font-bold tracking-tight text-ink">{groupLabel}</div>
              {fileMismatch && !parsing && (
                <div className="mt-1.5 text-[13px] font-medium leading-snug text-[#8a4b0f]">
                  <span className="inline-flex items-start gap-1.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                    <span>
                      Couldn&apos;t match the uploaded file against the known {standardName} concepts — fields below are empty.
                      Kindly check the file or fill them in manually.
                    </span>
                  </span>
                </div>
              )}
              {parseError && (
                <div className="mt-1.5 text-[13px] leading-snug text-[#c0392b]">Couldn&apos;t auto-fill from the uploaded file: {parseError}.</div>
              )}
              {!fileMismatch && !parseError && (
                <div className="mt-1 text-[13px] leading-snug text-ink-soft">
                  {filledCount > 0 ? `${filledCount} field${filledCount !== 1 ? 's' : ''} filled in.` : 'Fields autosave — fill each topic, then continue.'}
                </div>
              )}
            </div>
            <button type="button" className="flex h-8 w-8 flex-none items-center justify-center rounded-md text-ink-soft hover:bg-cream hover:text-ink" onClick={onCloseModal} aria-label="Close">
              <X className="h-5 w-5" strokeWidth={1.75} />
            </button>
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 pb-5 pt-4">
            <NmdsConceptFields
              fields={fields}
              onFieldChange={onFieldChange}
              onSave={onCloseModal}
              topics={topics}
              placeholders={placeholders}
            />
          </div>
        </div>
      </div>,
      document.body,
    )
    : null

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-bold uppercase tracking-wide text-ink">Upload {standardName} concept metadata *</div>
      <FileUpload
        onUpload={onFileSelected}
        label={`Add ${standardName} concept metadata file`}
        hint={hideFieldEditor ? 'XLSX or CSV — prefills the fields above' : 'XLSX or CSV — prefills the topics below'}
        selectedName={file?.name || prefilledHint}
        accept=".xlsx,.xls,.csv"
        extensionRegex={/\.(xlsx|xls|csv)$/i}
        compact
      />
      {canApplyToAll && (
        <label className={`mt-2 inline-flex select-none items-center gap-2 font-sans text-[13px] font-semibold ${filledCount === 0 ? 'cursor-default text-ink-muted' : 'cursor-pointer text-ink'}`}>
          <input
            type="checkbox"
            className="m-0 h-[15px] w-[15px] accent-teal"
            checked={!!appliedToAll}
            disabled={filledCount === 0}
            onChange={(e) => {
              if (e.target.checked) onApplyToAll?.()
            }}
          />
          <span>Apply to all</span>
        </label>
      )}
      {(file || appliedFrom) && (
        <div className="mt-1.5 flex flex-col gap-0.5">
          {!parsing && !parseError && !fileMismatch && file && (
            <div className="mt-0.5 text-[11px] text-teal">
              {hideFieldEditor
                ? `${file.name} — fields filled in above`
                : `${file.name} — fields filled in, click below to review`}
            </div>
          )}
          {!parsing && !parseError && !fileMismatch && !file && appliedFrom && (
            <div className="mt-0.5 text-[11px] text-teal">
              {appliedFrom.fileName
                ? `${appliedFrom.fileName} — fields filled in${hideFieldEditor ? ' above' : ', click below to review'}`
                : `Fields filled in${hideFieldEditor ? ' above' : ', click below to review'}`}
            </div>
          )}
          {parsing && <div className="mt-0.5 text-[11px] text-ink-soft">Reading concept metadata from {file.name}…</div>}
          {parseError && (
            <div className="mt-0.5 text-[11px] text-[#c0392b]">
              Couldn&apos;t auto-fill from {file.name}: {parseError}. You can still fill the fields in manually.
            </div>
          )}
          {!parsing && !parseError && fileMismatch && (
            <div className="mt-1 text-[13.5px] font-medium text-[#8a4b0f]">
              <span className="inline-flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                <span>
                  Couldn&apos;t match {file.name} against the known {standardName} concepts — double-check you&apos;ve uploaded the
                  right file. You can still fill the fields in manually{hideFieldEditor ? ' above' : ' below'}.
                </span>
              </span>
            </div>
          )}
        </div>
      )}

      <div className={`flex items-center gap-2.5 ${hideFieldEditor ? 'justify-end' : 'justify-between'}`}>
        {!hideFieldEditor && (
          <button
            type="button"
            className="mt-2.5 self-start rounded-lg border border-line bg-surface px-3.5 py-2 font-sans text-[13px] font-semibold text-teal transition-colors hover:border-teal hover:bg-cream"
            onClick={onOpenModal}
          >
            View / edit {standardName} fields {filledCount > 0 && `(${filledCount} filled)`}
          </button>
        )}
        <Button size="sm" className="mt-2.5 self-start" onClick={onSaveGroup}>
          Save
        </Button>
      </div>

      {modal}
    </div>
  )
}
