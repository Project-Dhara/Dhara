'use client'

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, X } from 'lucide-react'
import FileUpload from '../FileUpload'
import NmdsConceptFields from './NmdsConceptFields'
import Button from '../ui/Button'
import { nmdsFieldsToList } from '../../lib/nmdsConcepts'
import { NMDS_TOPICS } from '../../lib/nmdsConcepts'

// Per-metadata-group concept metadata. For NMDS, the open button lives near
// the group title (BatchReview); this panel owns the modal (upload + topics)
// and card footer actions (apply-to-all / save). For SDG (hideFieldEditor),
// upload stays on the card because fields are already on the sheet.
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
  onCloseModal,
  groupLabel,
  onSaveGroup,
  onApplyToAllChange,
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

  const uploadStatus = (file || appliedFrom || parsing) ? (
    <div className="flex flex-col gap-0.5">
      {!parsing && !parseError && !fileMismatch && file && (
        <div className="text-[11px] text-teal">{file.name} — fields auto-filled from this file</div>
      )}
      {!parsing && !parseError && !fileMismatch && !file && appliedFrom && (
        <div className="text-[11px] text-teal">
          {appliedFrom.fileName
            ? `${appliedFrom.fileName} — fields auto-filled`
            : 'Fields auto-filled'}
        </div>
      )}
      {parsing && file && (
        <div className="text-[11px] text-ink-soft">Reading concept metadata from {file.name}…</div>
      )}
      {parseError && file && (
        <div className="text-[11px] text-[#c0392b]">
          Couldn&apos;t auto-fill from {file.name}: {parseError}. You can still fill the fields in manually.
        </div>
      )}
      {!parsing && !parseError && fileMismatch && file && (
        <div className="text-[12px] font-medium text-[#8a4b0f]">
          <span className="inline-flex items-start gap-1.5">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-none" strokeWidth={2} aria-hidden />
            <span>
              Couldn&apos;t match {file.name} — check the file or fill fields manually.
            </span>
          </span>
        </div>
      )}
    </div>
  ) : null

  const applyToAllControl = canApplyToAll ? (
    <label className={`inline-flex select-none items-center gap-2 font-sans text-[13px] font-semibold ${filledCount === 0 ? 'cursor-default text-ink-muted' : 'cursor-pointer text-ink'}`}>
      <input
        type="checkbox"
        className="m-0 h-[15px] w-[15px] accent-teal"
        checked={!!appliedToAll}
        disabled={filledCount === 0}
        onChange={(e) => onApplyToAllChange?.(e.target.checked)}
      />
      <span>Apply to all groups</span>
    </label>
  ) : null

  const modal = !hideFieldEditor && modalOpen && typeof document !== 'undefined'
    ? createPortal(
      <div
        className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
        role="dialog"
        aria-modal="true"
        aria-labelledby="nmds-modal-title"
      >
        <div className="flex h-[min(720px,92vh)] w-full max-w-[860px] flex-col overflow-hidden rounded-[14px] bg-surface shadow-dhara">
          <div className="relative flex flex-shrink-0 items-start justify-between gap-4 border-b border-line bg-cream px-6 pb-3.5 pt-4">
            <div className="min-w-0 pr-2">
              <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-teal">{standardName} concept metadata</div>
              <div id="nmds-modal-title" className="truncate text-xl font-bold tracking-tight text-ink">{groupLabel}</div>
              {filledCount > 0 && (
                <div className="mt-1 text-[13px] text-ink-soft">
                  {filledCount} field{filledCount !== 1 ? 's' : ''} filled
                </div>
              )}
            </div>
            <button type="button" className="flex h-8 w-8 flex-none items-center justify-center rounded-md text-ink-soft hover:bg-cream hover:text-ink" onClick={onCloseModal} aria-label="Close">
              <X className="h-5 w-5" strokeWidth={1.75} />
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 pb-5 pt-3">
            <NmdsConceptFields
              fields={fields}
              onFieldChange={onFieldChange}
              onSave={onCloseModal}
              topics={topics}
              placeholders={placeholders}
              canApplyToAll={canApplyToAll}
              appliedToAll={appliedToAll}
              onApplyToAllChange={onApplyToAllChange}
              onFileSelected={onFileSelected}
              uploadStatus={uploadStatus}
              standardName={standardName}
            />
          </div>
        </div>
      </div>,
      document.body,
    )
    : null

  return (
    <div className="flex flex-col gap-2">
      {hideFieldEditor && (
        <>
          <div className="text-xs font-bold uppercase tracking-wide text-ink">Upload {standardName} concept metadata *</div>
          <FileUpload
            onUpload={onFileSelected}
            label={`Add ${standardName} concept metadata file`}
            hint="XLSX or CSV — prefills the fields above"
            selectedName={file?.name || prefilledHint}
            accept=".xlsx,.xls,.csv"
            extensionRegex={/\.(xlsx|xls|csv)$/i}
            compact
          />
          {uploadStatus}
          {applyToAllControl}
        </>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2.5">
        <Button size="sm" className="self-start" onClick={onSaveGroup}>
          Save
        </Button>
      </div>

      {modal}
    </div>
  )
}
