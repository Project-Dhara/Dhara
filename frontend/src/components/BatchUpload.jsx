'use client'

import { useEffect, useRef, useState } from 'react'
import { ArrowRight, X } from 'lucide-react'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { withAuthHeaders } from '../lib/auth'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'

function FileList({ files, onRemove }) {
  if (files.length === 0) return null
  return (
    <ul className="flex list-none flex-col gap-1">
      {files.map((f, i) => (
        <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 text-[13px]">
          <span className="break-all">{f.name}</span>
          <button className="flex h-6 w-6 flex-none items-center justify-center rounded text-ink-soft hover:bg-cream hover:text-[#b91c1c]" onClick={() => onRemove(i)} title="Remove" aria-label="Remove file">
            <X className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </li>
      ))}
    </ul>
  )
}

export default function BatchUpload({
  onMatched,
  onError,
  initialDatasetFiles = [],
  metadataFiles: controlledMetadataFiles,
  onMetadataFilesChange,
  hideMetadataSection = false,
}) {
  const [datasetFiles, setDatasetFiles] = useState([])
  const [internalMetadataFiles, setInternalMetadataFiles] = useState([])
  const [stage, setStage] = useState('idle') // idle | extracting | matching | error
  const [error, setError] = useState('')
  // A single shared hidden input, routed by `pendingTarget`, sidesteps a
  // React/Chromium quirk where the second of two separate <input type=file>
  // elements on the page stops firing onChange after the first one is used.
  const fileInputRef = useRef()
  const pendingTarget = useRef(null) // 'dataset' | 'metadata'
  const metadataControlled = controlledMetadataFiles != null
  const metadataFiles = metadataControlled ? controlledMetadataFiles : internalMetadataFiles
  const setMetadataFiles = metadataControlled ? onMetadataFilesChange : setInternalMetadataFiles

  useEffect(() => {
    if (!initialDatasetFiles.length) return
    setDatasetFiles((prev) => {
      const next = [...prev]
      initialDatasetFiles.forEach((file) => {
        const exists = next.some((f) => f.name === file.name && f.size === file.size)
        if (!exists) next.push(file)
      })
      return next
    })
  }, [initialDatasetFiles])

  const excelOnly = (fileList) => Array.from(fileList).filter((f) => /\.(xlsx|xls)$/i.test(f.name))

  const openPicker = (target) => {
    pendingTarget.current = target
    fileInputRef.current.click()
  }

  const handleFilesChosen = (fileList) => {
    const files = excelOnly(fileList)
    if (pendingTarget.current === 'dataset') {
      setDatasetFiles((prev) => [...prev, ...files])
    } else if (pendingTarget.current === 'metadata' && setMetadataFiles) {
      setMetadataFiles((prev) => [...prev, ...files])
    }
  }

  const removeDataset = (i) => setDatasetFiles((prev) => prev.filter((_, idx) => idx !== i))
  const removeMetadata = (i) => setMetadataFiles((prev) => prev.filter((_, idx) => idx !== i))

  const busy = stage === 'extracting' || stage === 'matching'
  const canRun = datasetFiles.length > 0 && !busy

  const runMatch = async () => {
    setError('')
    setStage('extracting')
    try {
      const extractFd = new FormData()
      datasetFiles.forEach((f) => extractFd.append('files', f))
      const extractRes = await fetch('/api/catalogue/batch-extract', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: extractFd })))
      if (!extractRes.ok) {
        const err = await extractRes.json().catch(() => ({}))
        const detail = typeof err.detail === 'string'
          ? err.detail
          : Array.isArray(err.detail)
            ? err.detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
            : ''
        if (extractRes.status >= 500 && !detail) {
          throw new Error('Extraction timed out or the server closed the connection. Try again with a smaller workbook, or wait a moment and retry.')
        }
        throw new Error(detail || `Extraction failed (HTTP ${extractRes.status})`)
      }
      const extractData = await extractRes.json()

      setStage('matching')
      const matchFd = new FormData()
      matchFd.append('tables_json', JSON.stringify(extractData.tables || []))
      metadataFiles.forEach((f) => matchFd.append('metadata_files', f))
      // Sent so groups with no metadata-workbook match can be auto-filled
      // via Stage 4 LLM metadata generation server-side (see main.py's
      // _fill_empty_group_metadata) instead of staying blank.
      datasetFiles.forEach((f) => matchFd.append('dataset_files', f))
      const matchRes = await fetch('/api/catalogue/batch-match', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: matchFd })))
      if (!matchRes.ok) {
        const err = await matchRes.json().catch(() => ({}))
        const detail = typeof err.detail === 'string'
          ? err.detail
          : Array.isArray(err.detail)
            ? err.detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
            : ''
        throw new Error(detail || `Matching failed (HTTP ${matchRes.status})`)
      }
      const matchData = await matchRes.json()

      setStage('idle')
      onMatched({ ...matchData, metadataFiles, perFile: extractData.per_file })
    } catch (e) {
      const raw = e?.message || ''
      const message = raw === 'Failed to fetch'
        ? 'Could not reach the server to read this Excel file. Check that the backend is running, then try again.'
        : (raw || 'Could not read this Excel file')
      setError(message)
      setStage('error')
      onError?.(e)
    }
  }

  return (
    <div className="flex w-full flex-col gap-[18px]">
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xls"
        multiple
        style={{ display: 'none' }}
        onChange={(e) => { handleFilesChosen(e.target.files); e.target.value = '' }}
      />

      <div className={`grid w-full grid-cols-1 gap-5 ${hideMetadataSection ? '' : 'sm:grid-cols-2'}`}>
        <div className="flex min-w-0 flex-col overflow-hidden rounded-xl bg-teal shadow-card">
          <div className="flex h-[40px] items-center gap-2 border-b border-[#e6dcc8] bg-cream px-3.5">
            <span className="h-2 w-2 rounded-sm bg-green" />
            <span className="text-xs font-bold uppercase tracking-wide text-ink">Dataset files</span>
          </div>
          <div className="flex flex-col gap-2 p-3">
            <div
              className={`flex h-[84px] cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-white/25 bg-black/10 transition-colors hover:border-cream/70 hover:bg-black/[.14] ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
              onClick={() => !busy && openPicker('dataset')}
            >
              <div className="text-[15px] font-semibold text-cream">Add dataset files</div>
              <div className="text-[13px] text-cream/70">XLSX — drag and drop or browse</div>
            </div>
            {datasetFiles.length > 0 && (
              <div className="rounded-lg bg-cream/95 px-2.5 py-2 text-ink">
                <FileList files={datasetFiles} onRemove={removeDataset} />
              </div>
            )}
          </div>
        </div>

        {!hideMetadataSection && (
          <div className="flex min-w-0 flex-col overflow-hidden rounded-xl bg-teal shadow-card">
            <div className="flex h-[40px] items-center gap-2 border-b border-[#e6dcc8] bg-cream px-3.5">
              <span className="h-2 w-2 rounded-sm bg-yellow" />
              <span className="text-xs font-bold uppercase tracking-wide text-ink">Metadata files</span>
            </div>
            <div className="flex flex-col gap-2 p-3">
              <div
                className={`flex h-[84px] cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-white/25 bg-black/10 transition-colors hover:border-cream/70 hover:bg-black/[.14] ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
                onClick={() => !busy && openPicker('metadata')}
              >
                <div className="text-[15px] font-semibold text-cream">Add metadata files</div>
                <div className="text-[13px] text-cream/70">XLSX tag files</div>
              </div>
              {metadataFiles.length > 0 && (
                <div className="rounded-lg bg-cream/95 px-2.5 py-2 text-ink">
                  <FileList files={metadataFiles} onRemove={removeMetadata} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <div className="flex items-center gap-4">
        <Button disabled={!canRun} onClick={runMatch}>
          {busy && <span className="inline-block h-[13px] w-[13px] animate-spin rounded-full border-2 border-white/50 border-t-white" />}
          {stage === 'extracting' && 'Extracting & validating tables…'}
          {stage === 'matching' && 'Matching to metadata…'}
          {(stage === 'idle' || stage === 'error') && (
            <span className="inline-flex items-center gap-1.5">
              Preview files
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            </span>
          )}
        </Button>
        {!busy && <span className="text-xs text-ink-soft">{datasetFiles.length} dataset · {metadataFiles.length} metadata</span>}
      </div>

      {busy && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 text-[13px] font-medium text-ink">
              <span className="h-2 w-2 flex-none animate-pulse rounded-full bg-teal" />
              Extracting tables & validating Source Table ID / Title
            </div>
          </div>
        </div>
      )}
    </div>
  )
}