'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, X, ZoomIn, ZoomOut } from 'lucide-react'
import { withAuthHeaders } from '../../lib/auth'
import Button from '../ui/Button'
import { ExtractedTableHead } from './ExtractedTableGrid'

/** PDF page/table crop for side-by-side review comparison. */
export function PdfTableSnapshot({ jobId, tableId, maxHeightClass = 'max-h-[420px]', zoom = 1 }) {
  const [url, setUrl] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    let objectUrl = null
    setLoading(true)
    setError('')
    setUrl(null)
    fetch(`/api/pdf/jobs/${jobId}/tables/${encodeURIComponent(tableId)}/snapshot`, withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(typeof body.detail === 'string' ? body.detail : 'Snapshot unavailable')
        }
        return res.blob()
      })
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
        setLoading(false)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || 'Snapshot unavailable')
        setLoading(false)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [jobId, tableId])

  if (loading) {
    return (
      <div className="flex min-h-[160px] items-center justify-center gap-2 rounded-lg border border-dashed border-line bg-[#FFFCF6] text-[12.5px] text-ink-soft">
        <Loader2 className="h-4 w-4 animate-spin text-teal" aria-hidden />
        Loading PDF snapshot…
      </div>
    )
  }
  if (error || !url) {
    return (
      <div className="rounded-lg border border-dashed border-line bg-[#FFFCF6] px-3 py-4 text-[12.5px] leading-snug text-ink-soft">
        {error || 'No PDF snapshot available. Re-upload the PDF after this update to enable page comparison.'}
      </div>
    )
  }
  const z = Math.max(0.4, Math.min(3, Number(zoom) || 1))
  return (
    <div className="overflow-auto rounded-lg border border-line bg-white">
      <img
        src={url}
        alt="Source PDF table"
        className={`mx-auto block h-auto object-contain ${maxHeightClass === 'max-h-none' ? '' : maxHeightClass}`}
        style={{
          width: `${Math.round(z * 100)}%`,
          maxWidth: z > 1 ? 'none' : '100%',
        }}
      />
    </div>
  )
}


export function EditorZoomControls({ zoom, onChange, label }) {
  const pct = Math.round((zoom || 1) * 100)
  return (
    <div className="inline-flex items-center gap-0.5" title={`${label || 'Zoom'} · pinch or ⌘/Ctrl+scroll`}>
      <button
        type="button"
        className="rounded p-0.5 text-ink-soft hover:bg-sage hover:text-teal disabled:opacity-30"
        disabled={zoom <= 0.5}
        onClick={() => onChange(Math.max(0.5, Math.round((zoom - 0.1) * 10) / 10))}
        aria-label={`${label || 'Zoom'} out`}
      >
        <ZoomOut className="h-3.5 w-3.5" strokeWidth={2} />
      </button>
      <button
        type="button"
        className="min-w-[2.5rem] rounded px-1 py-0.5 text-[10px] font-bold tabular-nums text-ink-soft hover:bg-sage hover:text-teal"
        onClick={() => onChange(1)}
        title="Reset zoom"
      >
        {pct}%
      </button>
      <button
        type="button"
        className="rounded p-0.5 text-ink-soft hover:bg-sage hover:text-teal disabled:opacity-30"
        disabled={zoom >= 2.5}
        onClick={() => onChange(Math.min(2.5, Math.round((zoom + 0.1) * 10) / 10))}
        aria-label={`${label || 'Zoom'} in`}
      >
        <ZoomIn className="h-3.5 w-3.5" strokeWidth={2} />
      </button>
    </div>
  )
}


/** Read-only frozen extraction for Original tab. */
export function OriginalExtractionGrid({ columns, rows, maxRows = 8 }) {
  const cols = columns || []
  const preview = (rows || []).slice(0, maxRows)
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="w-full min-w-[480px] table-fixed border-collapse text-[12.5px]">
        <ExtractedTableHead columns={cols} />
        <tbody>
          {preview.map((row, r) => (
            <tr key={r}>
              {cols.map((_, c) => (
                <td key={c} className="max-w-0 border border-line px-2 py-1 break-words [overflow-wrap:anywhere] align-top text-ink">
                  {row?.[c] == null || row[c] === '' ? <span className="text-[#a49c8e]">—</span> : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {(rows || []).length > preview.length && (
        <div className="border-t border-line px-2.5 py-1.5 text-[11px] text-ink-soft">
          Showing {preview.length} of {rows.length} original rows
        </div>
      )}
    </div>
  )
}


/** Popup modal for PDF snapshot / original extraction reference. */
export function ReferencePopupModal({ jobId, tableId, originalSnapshot, initialTab = 'pdf', onClose }) {
  const [tab, setTab] = useState(initialTab)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])

  if (!mounted) return null
  return createPortal(
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center overflow-hidden bg-[rgba(16,64,63,0.55)] p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reference-popup-title"
      onClick={onClose}
    >
      <div
        className="flex max-h-[min(880px,92vh)] w-[min(1100px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[14px] bg-surface shadow-dhara"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative flex flex-shrink-0 items-center justify-between gap-3 border-b border-line bg-cream px-4 py-3.5 sm:px-5">
          <div className="min-w-0">
            <div id="reference-popup-title" className="text-[11px] font-bold uppercase tracking-wide text-teal">
              Reference
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {[
                { id: 'pdf', label: 'PDF snapshot' },
                { id: 'original', label: 'Original extraction' },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  className={`rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors ${
                    tab === t.id ? 'border-teal bg-teal text-cream' : 'border-line bg-white text-ink-soft hover:border-teal'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md text-ink-soft hover:bg-white hover:text-ink"
            onClick={onClose}
            aria-label="Close reference"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-5">
          {tab === 'pdf' ? (
            jobId && tableId ? (
              <PdfTableSnapshot jobId={jobId} tableId={tableId} maxHeightClass="max-h-[min(70vh,720px)]" />
            ) : (
              <div className="text-[13px] text-ink-soft">PDF snapshot unavailable</div>
            )
          ) : (
            <OriginalExtractionGrid
              columns={originalSnapshot?.columns}
              rows={originalSnapshot?.rows}
              maxRows={200}
            />
          )}
        </div>
        <div className="flex flex-shrink-0 justify-end border-t border-line bg-cream/60 px-4 py-3 sm:px-5">
          <Button variant="primary" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}


export function ReferenceComparePanel({ jobId, tableId, originalSnapshot }) {
  const [popupTab, setPopupTab] = useState(null)
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-[#FFFCF6] px-2.5 py-2">
        <span className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Reference</span>
        <button
          type="button"
          onClick={() => setPopupTab('pdf')}
          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-3 py-1.5 text-[12px] font-semibold text-teal shadow-[0_1px_2px_rgba(16,64,63,0.06)] transition-colors hover:border-teal hover:bg-sage"
        >
          PDF snapshot
        </button>
        <button
          type="button"
          onClick={() => setPopupTab('original')}
          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-3 py-1.5 text-[12px] font-semibold text-teal shadow-[0_1px_2px_rgba(16,64,63,0.06)] transition-colors hover:border-teal hover:bg-sage"
        >
          Original extraction
        </button>
      </div>
      {popupTab && (
        <ReferencePopupModal
          jobId={jobId}
          tableId={tableId}
          originalSnapshot={originalSnapshot}
          initialTab={popupTab}
          onClose={() => setPopupTab(null)}
        />
      )}
    </>
  )
}


