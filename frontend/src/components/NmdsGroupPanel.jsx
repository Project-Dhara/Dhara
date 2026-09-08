'use client'

import { AlertTriangle, X } from 'lucide-react'
import FileUpload from './FileUpload'
import NmdsConceptFields from './NmdsConceptFields'
import Button from './ui/Button'
import { nmdsFieldsToList } from '../lib/nmdsConcepts'

// Per-metadata-group NMDS concept metadata: the same upload box that used
// to sit at the top of the standalone NMDS step, now shown right below
// each group's card in the carousel. Uploading (or the "View / edit
// fields" link) opens a modal with the same topic-by-topic field editor —
// the parsing/mismatch logic and the field set are untouched, only where
// they're shown has changed.
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
}) {
  const filledCount = nmdsFieldsToList(fields).length
  const prefilledHint = appliedFrom?.fileName || (appliedFrom ? 'Fields filled in' : null)

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-bold uppercase tracking-wide text-ink">Upload NMDS concept metadata *</div>
      <FileUpload
        onUpload={onFileSelected}
        label="Add NMDS concept metadata file"
        hint="XLSX or CSV — prefills the topics below"
        selectedName={file?.name || prefilledHint}
        accept=".xlsx,.xls,.csv"
        extensionRegex={/\.(xlsx|xls|csv)$/i}
        compact
      />
      {canApplyToAll && (
        <label className={`mt-2 inline-flex select-none items-center gap-2 font-sans text-[13px] font-semibold ${filledCount === 0 ? 'cursor-default text-[#a49c8e]' : 'cursor-pointer text-ink'}`}>
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
            <div className="mt-0.5 text-[11px] text-teal">{file.name} — fields filled in, click below to review</div>
          )}
          {!parsing && !parseError && !fileMismatch && !file && appliedFrom && (
            <div className="mt-0.5 text-[11px] text-teal">
              {appliedFrom.fileName
                ? `${appliedFrom.fileName} — fields filled in, click below to review`
                : 'Fields filled in, click below to review'}
            </div>
          )}
          {parsing && <div className="mt-0.5 text-[11px] text-ink-soft">Reading concept metadata from {file.name}…</div>}
          {parseError && (
            <div className="mt-0.5 text-[11px] text-[#c0392b]">
              Couldn't auto-fill from {file.name}: {parseError}. You can still fill the fields in manually.
            </div>
          )}
          {!parsing && !parseError && fileMismatch && (
            <div className="mt-1 text-[13.5px] font-medium text-[#8a4b0f]">
              <span className="inline-flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                <span>
                  Couldn&apos;t match {file.name} against the known NMDS concepts — double-check you&apos;ve uploaded the
                  right file. You can still fill the fields in manually below.
                </span>
              </span>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-2.5">
        <button
          type="button"
          className="mt-2.5 self-start rounded-lg border border-line bg-surface px-3.5 py-2 font-sans text-[13px] font-semibold text-teal transition-colors hover:border-teal hover:bg-cream"
          onClick={onOpenModal}
        >
          View / edit NMDS fields {filledCount > 0 && `(${filledCount} filled)`}
        </button>
        <Button size="sm" className="mt-2.5 self-start" onClick={onSaveGroup}>
          Save
        </Button>
      </div>

      {modalOpen && (
        <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5" role="dialog" aria-modal="true" aria-labelledby="nmds-modal-title">
          <div className="flex max-h-[92vh] w-full max-w-[860px] flex-col overflow-hidden rounded-[14px] bg-surface shadow-dhara">
            <div className="relative flex flex-shrink-0 items-start justify-between gap-4 bg-cream px-6 pb-4 pt-5">
              <div>
                <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-teal">NMDS concept metadata</div>
                <div id="nmds-modal-title" className="text-2xl font-bold tracking-tight text-ink">{groupLabel}</div>
                {fileMismatch && !parsing && (
                  <div className="mt-1.5 text-[13.5px] font-medium leading-relaxed text-[#8a4b0f]">
                    <span className="inline-flex items-start gap-1.5">
                      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                      <span>
                        Couldn&apos;t match the uploaded file against the known NMDS concepts — fields below are empty.
                        Kindly check the file or fill them in manually.
                      </span>
                    </span>
                  </div>
                )}
                {parseError && (
                  <div className="mt-1.5 text-[13.5px] leading-relaxed text-[#c0392b]">Couldn't auto-fill from the uploaded file: {parseError}.</div>
                )}
                {!fileMismatch && !parseError && (
                  <div className="mt-1.5 text-[13.5px] leading-relaxed text-ink-soft">
                    {filledCount > 0 ? `${filledCount} field${filledCount !== 1 ? 's' : ''} filled in.` : 'The fields are autosaved, kindly fill in all the fields and proceed to next topic.'}
                  </div>
                )}
              </div>
              <button type="button" className="flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-cream hover:text-ink" onClick={onCloseModal} aria-label="Close">
                <X className="h-5 w-5" strokeWidth={1.75} />
              </button>
            </div>
            <div className="flex flex-1 flex-col gap-[18px] overflow-y-auto px-6 pb-6 pt-[18px]">
              <NmdsConceptFields fields={fields} onFieldChange={onFieldChange} onSave={onCloseModal} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}