'use client'

import { useRef, useState } from 'react'
import { X } from 'lucide-react'
import Button from '../ui/Button'
import ErrorBanner from '../ui/ErrorBanner'

export function stepInfoFor(step) {
  return [
    null,
    {
      title: 'Select dataset and metadata files',
      purpose: 'Upload dataset files (PDF, XLSX, or SQL) and optional metadata tag workbooks for this release.',
      next: 'Next: preview the extracted tables.',
    },
    {
      title: 'Preview',
      purpose: 'Confirm the extracted tables look right, and resolve any Source Table ID / Title mismatches.',
      next: 'Next: group tables into datasets.',
    },
    {
      title: 'Grouping',
      purpose: 'Confirm which tables belong together — every table needs a group before you can add metadata.',
      next: 'Next: add metadata for each group.',
    },
    {
      title: 'Metadata',
      purpose: 'Add catalogue metadata — title, category, coverage — for each group.',
      next: 'Next: map columns to standard concepts and code lists.',
    },
    {
      title: 'Classification and harmonisation',
      purpose: 'Map columns to standard concepts and code lists.',
      next: 'Next: publish this release.',
    },
    {
      title: 'Publish this release',
      purpose: 'Register the API and MCP endpoints for this release.',
      next: null,
    },
  ][step]
}

export const BACK_LABELS = [
  '', 'Choose another method', 'Change files', 'Back to preview', 'Back to grouping', 'Back to metadata',
]

export function MetadataFileList({ files, onRemove }) {
  if (files.length === 0) return null
  return (
    <ul className="mt-3 flex w-full list-none flex-col gap-1.5 text-left">
      {files.map((f, i) => (
        <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 rounded-md bg-cream/95 px-2.5 py-1.5 text-[12.5px] text-ink">
          <span className="min-w-0 truncate">{f.name}</span>
          <button
            type="button"
            className="flex h-6 w-6 flex-none items-center justify-center rounded text-ink-soft hover:bg-white hover:text-[#b91c1c]"
            onClick={(e) => {
              e.stopPropagation()
              onRemove(i)
            }}
            title="Remove"
            aria-label="Remove file"
          >
            <X className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </li>
      ))}
    </ul>
  )
}

// Step 1: two equal cards — dataset (PDF / XLSX / SQL tabs) and metadata tag files.
export function UploadChoice({
  choice,
  onChoose,
  onDatasetFile,
  onPdfFile,
  pdfUploading,
  pdfError,
  onClearPdfError,
  metadataFiles,
  onMetadataFilesAdd,
  onMetadataFileRemove,
  sqlPanel,
}) {
  const datasetInputRef = useRef(null)
  const metadataInputRef = useRef(null)
  const [datasetDragging, setDatasetDragging] = useState(false)
  const [metadataDragging, setMetadataDragging] = useState(false)

  const routeDatasetFile = (file) => {
    if (!file || pdfUploading) return
    if (/\.pdf$/i.test(file.name)) {
      onPdfFile(file)
      return
    }
    if (/\.(xlsx|xls)$/i.test(file.name)) {
      onDatasetFile('xlsx', file)
      return
    }
  }

  const takeMetadataFiles = (fileList) => {
    const files = Array.from(fileList || []).filter((f) => /\.(xlsx|xls)$/i.test(f.name))
    if (files.length) onMetadataFilesAdd(files)
  }

  const fileTab = choice !== 'sql'
  const dropZoneClass = (dragging) =>
    `flex min-h-[168px] flex-1 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-5 py-6 text-center transition-colors ${
      dragging
        ? 'border-teal/40 bg-sage'
        : 'border-line bg-white hover:border-line hover:bg-mist/80'
    }`

  const datasetCardClass = 'dhara-surface flex min-h-[240px] w-full flex-col overflow-hidden rounded-card border border-teal/20 bg-white'
  const metadataCardClass = 'dhara-surface flex min-h-[240px] w-full flex-col overflow-hidden rounded-card border border-line bg-white'
  const selectorBarClass = 'border-b border-line bg-mist'
  const tabBase = 'dhara-tab relative px-3 text-[13px] font-semibold disabled:cursor-not-allowed disabled:opacity-60'
  const tabActive = 'dhara-tab-on'
  const tabIdle = 'dhara-tab-off'

  return (
    <div className="flex flex-col gap-4">
      <input
        ref={datasetInputRef}
        type="file"
        accept=".pdf,.xlsx,.xls"
        className="hidden"
        disabled={pdfUploading}
        onChange={(e) => {
          routeDatasetFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      <input
        ref={metadataInputRef}
        type="file"
        accept=".xlsx,.xls"
        multiple
        className="hidden"
        disabled={pdfUploading}
        onChange={(e) => {
          takeMetadataFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 sm:items-stretch">
        <div className={datasetCardClass}>
          <div
            className={`grid h-[45px] grid-cols-2 ${selectorBarClass}`}
            role="tablist"
            aria-label="Dataset source"
          >
            <button
              type="button"
              role="tab"
              aria-selected={fileTab}
              disabled={pdfUploading}
              className={`${tabBase} ${fileTab ? tabActive : tabIdle}`}
              onClick={() => choice === 'sql' && onChoose(null)}
            >
              File upload
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!fileTab}
              disabled={pdfUploading}
              className={`${tabBase} ${!fileTab ? tabActive : tabIdle}`}
              onClick={() => fileTab && onChoose('sql')}
            >
              Connect SQL database
            </button>
          </div>
          {fileTab ? (
            <div key="file-tab" className="dhara-tab-panel flex flex-1 flex-col p-3">
              <div
                role="button"
                tabIndex={0}
                onClick={() => !pdfUploading && datasetInputRef.current?.click()}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !pdfUploading && datasetInputRef.current?.click() } }}
                onDragOver={(e) => { e.preventDefault(); setDatasetDragging(true) }}
                onDragLeave={() => setDatasetDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDatasetDragging(false)
                  routeDatasetFile(e.dataTransfer.files?.[0])
                }}
                className={`${dropZoneClass(datasetDragging)} ${pdfUploading ? 'pointer-events-none opacity-60' : ''}`}
              >
                <div className="text-[15px] font-semibold tracking-tight text-ink">
                  {pdfUploading ? 'Uploading PDF…' : 'Upload dataset files'}
                </div>
                <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">
                  {pdfUploading
                    ? 'Starting extraction…'
                    : 'Click or drop PDF reports or XLSX workbooks — the matching pipeline runs automatically.'}
                </div>
              </div>
            </div>
          ) : (
            <div key="sql-tab" className="dhara-tab-panel flex flex-1 flex-col p-3">
              <div className="flex min-h-0 flex-1 flex-col rounded-lg bg-white p-4">
                {sqlPanel}
              </div>
            </div>
          )}
        </div>

        <div className={metadataCardClass}>
          <div className={`flex h-[45px] items-center justify-center px-3 ${selectorBarClass}`}>
            <span className="text-[13px] font-semibold text-ink-soft">Metadata (optional)</span>
          </div>
          <div className="flex flex-1 flex-col p-3">
            <div
              role="button"
              tabIndex={0}
              onClick={() => !pdfUploading && metadataInputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !pdfUploading && metadataInputRef.current?.click() } }}
              onDragOver={(e) => { e.preventDefault(); setMetadataDragging(true) }}
              onDragLeave={() => setMetadataDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setMetadataDragging(false)
                takeMetadataFiles(e.dataTransfer.files)
              }}
              className={`${dropZoneClass(metadataDragging)} ${pdfUploading ? 'pointer-events-none opacity-60' : ''}`}
            >
              <div className="text-[15px] font-semibold tracking-tight text-ink">Upload metadata tag files</div>
              <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">
                Optional XLSX metadata workbooks — matched against your dataset tables during grouping.
              </div>
              {metadataFiles.length > 0 && (
                <div className="w-full max-w-[280px]">
                  <MetadataFileList files={metadataFiles} onRemove={onMetadataFileRemove} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      {pdfError && (
        <div className="flex flex-col gap-2">
          <ErrorBanner>{pdfError}</ErrorBanner>
          <Button variant="secondary" size="sm" className="self-start" onClick={onClearPdfError}>Try again</Button>
        </div>
      )}
    </div>
  )
}

