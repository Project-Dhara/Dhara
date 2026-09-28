'use client'

import { useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
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
      title: 'Classification',
      purpose: 'Map columns to standard concepts and code lists.',
      next: 'Next: harmonise values across related tables.',
    },
    {
      title: 'Harmonisation',
      purpose: 'Verify clubbed values and set catalogue placement.',
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
  '',
  '',
  'Back to files',
  '',
  'Back to grouping',
  '',
  'Back to classification',
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

function DatasetFileList({ files, onRemove }) {
  if (files.length === 0) return null
  return (
    <ul className="flex list-none flex-col gap-1.5">
      {files.map((f, i) => (
        <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 rounded-md border border-line/70 bg-cream/95 px-2.5 py-1.5 text-[12.5px] text-ink">
          <span className="min-w-0 truncate">{f.name}</span>
          <button
            type="button"
            className="flex h-6 w-6 flex-none items-center justify-center rounded text-ink-soft hover:bg-white hover:text-[#b91c1c]"
            onClick={() => onRemove(i)}
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
  onDatasetFilesAdd,
  onDatasetFileRemove,
  datasetFiles = [],
  onPdfFile,
  pdfUploading,
  pdfError,
  onClearPdfError,
  metadataFiles,
  onMetadataFilesAdd,
  onMetadataFileRemove,
  sqlPanel,
  disabled = false,
}) {
  const datasetInputRef = useRef(null)
  const metadataInputRef = useRef(null)
  const [datasetDragging, setDatasetDragging] = useState(false)
  const [metadataDragging, setMetadataDragging] = useState(false)

  const hasDatasetFiles = datasetFiles.length > 0
  const uploadsBlocked = disabled || pdfUploading

  const routeDatasetFiles = (fileList) => {
    if (uploadsBlocked) return
    const files = Array.from(fileList || [])
    if (!files.length) return

    // Once XLSX workbooks are queued, only accept more XLSX — keep adding under this box.
    if (hasDatasetFiles) {
      const xlsx = files.filter((f) => /\.(xlsx|xls)$/i.test(f.name))
      if (xlsx.length) onDatasetFilesAdd?.(xlsx)
      return
    }

    const first = files[0]
    if (/\.pdf$/i.test(first.name)) {
      onPdfFile?.(first)
      return
    }
    const xlsx = files.filter((f) => /\.(xlsx|xls)$/i.test(f.name))
    if (xlsx.length === 1 && onDatasetFile) {
      onDatasetFile('xlsx', xlsx[0])
      return
    }
    if (xlsx.length) onDatasetFilesAdd?.(xlsx)
  }

  const takeMetadataFiles = (fileList) => {
    if (uploadsBlocked) return
    const files = Array.from(fileList || []).filter((f) => /\.(xlsx|xls)$/i.test(f.name))
    if (files.length) onMetadataFilesAdd?.(files)
  }

  const fileTab = choice !== 'sql'
  const dropZoneClass = (dragging) =>
    `flex min-h-[168px] flex-1 flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-5 py-6 text-center transition-colors ${
      uploadsBlocked
        ? 'cursor-not-allowed border-line bg-mist/60 opacity-70'
        : dragging
          ? 'cursor-pointer border-teal/40 bg-sage'
          : 'cursor-pointer border-line bg-white hover:border-teal/40 hover:bg-sage/70'
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
        accept={hasDatasetFiles ? '.xlsx,.xls' : '.pdf,.xlsx,.xls'}
        multiple={hasDatasetFiles}
        className="hidden"
        disabled={uploadsBlocked}
        onChange={(e) => {
          routeDatasetFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={metadataInputRef}
        type="file"
        accept=".xlsx,.xls"
        multiple
        className="hidden"
        disabled={uploadsBlocked}
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
              disabled={uploadsBlocked}
              className={`${tabBase} ${fileTab ? tabActive : tabIdle}`}
              onClick={() => {
                if (uploadsBlocked || choice !== 'sql') return
                onChoose?.(datasetFiles.length ? 'xlsx' : null)
              }}
            >
              File upload
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!fileTab}
              disabled={uploadsBlocked}
              className={`${tabBase} ${!fileTab ? tabActive : tabIdle}`}
              onClick={() => !uploadsBlocked && fileTab && onChoose?.('sql')}
            >
              Connect SQL database
            </button>
          </div>
          {fileTab ? (
            <div key="file-tab" className="dhara-tab-panel flex flex-1 flex-col gap-2 p-3">
              <div
                role="button"
                tabIndex={uploadsBlocked ? -1 : 0}
                onClick={() => !uploadsBlocked && datasetInputRef.current?.click()}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !uploadsBlocked && datasetInputRef.current?.click() } }}
                onDragOver={(e) => { if (uploadsBlocked) return; e.preventDefault(); setDatasetDragging(true) }}
                onDragLeave={() => setDatasetDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDatasetDragging(false)
                  routeDatasetFiles(e.dataTransfer.files)
                }}
                className={`${dropZoneClass(datasetDragging)} ${pdfUploading ? 'pointer-events-none opacity-60' : ''}`}
              >
                <Plus className="h-5 w-5 text-teal" strokeWidth={2} aria-hidden />
                {pdfUploading ? (
                  <>
                    <div className="text-[15px] font-semibold tracking-tight text-ink">Uploading PDF…</div>
                    <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">Starting extraction…</div>
                  </>
                ) : disabled ? (
                  <>
                    <div className="text-[15px] font-semibold tracking-tight text-ink">LLM key required</div>
                    <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">
                      Save an API key in Settings before uploading PDF, XLSX, or SQL datasets.
                    </div>
                  </>
                ) : hasDatasetFiles ? (
                  <div className="text-[15px] font-semibold tracking-tight text-ink">XLSX — drag and drop or browse</div>
                ) : (
                  <>
                    <div className="text-[15px] font-semibold tracking-tight text-ink">Upload dataset files</div>
                    <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">
                      Click or drop PDF reports or XLSX workbooks — the matching pipeline runs automatically.
                    </div>
                  </>
                )}
              </div>
              {hasDatasetFiles && (
                <DatasetFileList files={datasetFiles} onRemove={onDatasetFileRemove} />
              )}
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
              <Plus className="h-5 w-5 text-ink-soft" strokeWidth={2} aria-hidden />
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

