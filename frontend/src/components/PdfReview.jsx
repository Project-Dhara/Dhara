'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useRouter } from 'next/navigation'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  Columns2,
  Columns3,
  Combine,
  Download,
  GripVertical,
  Lightbulb,
  Loader2,
  Minus,
  MousePointerClick,
  Pencil,
  Plus,
  Redo2,
  Rows3,
  Table2,
  Trash2,
  Undo2,
  Eye,
  ZoomIn,
  ZoomOut,
  X,
} from 'lucide-react'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { isGarbled } from '../lib/garbled'
import Badge from './ui/Badge'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'
import KydsSummaryCard from './KydsSummaryCard'
import PdfConsoleLayout from './PdfConsoleLayout'
import ProcessingStepper from './ProcessingStepper'

/** Nearest ancestor that actually scrolls (AppShell main pane), else the document. */
function getScrollParent(el) {
  let node = el?.parentElement
  while (node && node !== document.documentElement) {
    const { overflowY } = getComputedStyle(node)
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') {
      return node
    }
    node = node.parentElement
  }
  return document.scrollingElement || document.documentElement
}

function isDocumentScroller(el) {
  return !el
    || el === document.documentElement
    || el === document.body
    || el === document.scrollingElement
}

function ScrollToTopButton({ scrollRootRef }) {
  const [visible, setVisible] = useState(false)
  const [mounted, setMounted] = useState(false)
  const scrollElRef = useRef(null)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!mounted) return undefined

    let listening = null

    const readTop = (el) => {
      if (isDocumentScroller(el)) {
        return window.scrollY || document.documentElement.scrollTop || 0
      }
      return el.scrollTop || 0
    }

    const onScroll = () => {
      setVisible(readTop(scrollElRef.current) > 240)
    }

    const attach = () => {
      if (listening) {
        listening.removeEventListener('scroll', onScroll)
        listening = null
      }
      const scrollEl = getScrollParent(scrollRootRef?.current)
      scrollElRef.current = scrollEl
      listening = isDocumentScroller(scrollEl) ? window : scrollEl
      listening.addEventListener('scroll', onScroll, { passive: true })
      onScroll()
    }

    attach()
    // Re-bind after layout — scrollport / refs can resolve a tick late.
    const raf = window.requestAnimationFrame(attach)

    return () => {
      window.cancelAnimationFrame(raf)
      listening?.removeEventListener('scroll', onScroll)
    }
  }, [scrollRootRef, mounted])

  const scrollUp = () => {
    const el = scrollElRef.current
    if (isDocumentScroller(el)) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return
    }
    el.scrollTo({ top: 0, behavior: 'smooth' })
  }

  if (!mounted) return null

  // Portal to body so `fixed` stays on the viewport (page-enter animation
  // uses transform, which would otherwise trap position:fixed in the content).
  return createPortal(
    <button
      type="button"
      aria-label="Scroll to top"
      onClick={scrollUp}
      className={`fixed bottom-7 right-7 z-[200] flex h-11 w-11 items-center justify-center rounded-full border border-line bg-white text-teal shadow-[0_6px_20px_rgba(16,64,63,0.16)] transition-all duration-200 hover:border-teal hover:bg-sage ${
        visible ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0'
      }`}
    >
      <ArrowUp className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
    </button>,
    document.body,
  )
}

/**
 * Gradual accordion open/close for review table cards.
 * Keeps content mounted briefly on close so the collapse can animate.
 */
function TableExpandPanel({ open, children }) {
  const [rendered, setRendered] = useState(open)
  const [expanded, setExpanded] = useState(open)

  useEffect(() => {
    if (open) {
      setRendered(true)
      const id = window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => setExpanded(true))
      })
      return () => window.cancelAnimationFrame(id)
    }
    setExpanded(false)
    const t = window.setTimeout(() => setRendered(false), 420)
    return () => window.clearTimeout(t)
  }, [open])

  if (!rendered) return null

  return (
    <div
      className={`grid transition-[grid-template-rows] duration-[420ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${
        expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
      }`}
    >
      <div className="min-h-0 overflow-hidden">
        <div
          className={`origin-top transition-[opacity,transform] duration-[380ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${
            expanded ? 'translate-y-0 opacity-100' : '-translate-y-1 opacity-0'
          }`}
        >
          {children}
        </div>
      </div>
    </div>
  )
}

const CLASSIFICATION_LABELS = {
  domain: 'Domain', subject: 'Subject', entity: 'Entity', table_type: 'Table type',
  geography: 'Geography', time_period: 'Time period', frequency: 'Frequency', unit: 'Unit',
}

/** Canonical review-reason chips shown in the filter bar. Backend may still
 *  emit finer codes (column_alignment_mismatch, uncertain_semantic_role); those
 *  are folded into these labels so overlapping filters aren't duplicated. */
const REASON_LABELS = {
  garbled_extracted_value: 'Garbled/corrupted value',
  conflicting_extraction: 'Conflicting extraction',
  uncertain_extraction: 'Uncertain extraction',
  ambiguous_column: 'Ambiguous column',
  uncertain_concept: 'Uncertain concept',
}

/** Map backend-specific reasons onto the chip the reviewer actually filters by. */
const REASON_ALIASES = {
  column_alignment_mismatch: 'uncertain_extraction',
  uncertain_semantic_role: 'ambiguous_column',
}

function canonicalizeReviewReason(reason) {
  if (!reason) return reason
  return REASON_ALIASES[reason] || reason
}

const ROLE_OPTIONS = ['identifier', 'dimension', 'measure', 'attribute', 'unknown']

/** Top-level filter chips. Reason-specific chips (uncertain extraction, etc.)
 *  stay nested under "Review needed" and only appear once that filter is active. */
const PRIMARY_FILTERS = ['needs_review', 'no_review']
const REASON_FILTER_IDS = Object.keys(REASON_LABELS)

function looksLikeNumber(value) {
  if (value === null || value === undefined) return true
  const s = String(value).trim().replace(/,/g, '').replace(/%\s*$/, '')
  if (!s) return true
  // Integers, decimals, and percentages (e.g. 36, 0.3, 30.5, 12%)
  return /^-?\d+(\.\d+)?$/.test(s)
}

const NUMERIC_DATA_TYPES = new Set([
  'integer', 'int', 'decimal', 'float', 'double', 'number', 'numeric',
  'percentage', 'percent', 'pct',
])

/** Numeric columns (integers, decimals, percentages) stay read-only. */
function isNumericColumn(col, colIndex, rows) {
  const dt = String(col?.data_type || '').toLowerCase().trim()
  if (NUMERIC_DATA_TYPES.has(dt)) return true
  // Also lock when the column name clearly marks a share/rate metric.
  const name = String(col?.name || '').toLowerCase()
  if (/(^|[^a-z])(percent|percentage|pct|%)([^a-z]|$)/i.test(name)) return true
  if (dt && dt !== 'unknown') return false
  const vals = (rows || [])
    .map((row) => row?.[colIndex])
    .filter((v) => v !== null && v !== undefined && String(v).trim() !== '')
  if (vals.length === 0) return false
  return vals.every(looksLikeNumber)
}

function tableHasGarbledCells(table) {
  return (table.rows || []).some((row) => (row || []).some((v) => isGarbled(v)))
}

function collectReviewReasons(table) {
  const reasons = new Set()
  const add = (reason) => {
    const canonical = canonicalizeReviewReason(reason)
    if (canonical) reasons.add(canonical)
  }
  if (table.human_review_reason) add(table.human_review_reason)
  for (const field of Object.values(table.classification || {})) {
    if (field?.human_review_reason) add(field.human_review_reason)
  }
  for (const col of table.columns || []) {
    if (col.human_review_reason) add(col.human_review_reason)
  }
  if (tableHasGarbledCells(table)) add('garbled_extracted_value')
  if ((table.uncertain_cells || []).length > 0 && !reasons.has('conflicting_extraction')) {
    add('uncertain_extraction')
  }
  return reasons
}

// DEV-ONLY: semantic_status is 'classified' for any table that went through
// the OpenAI validation step (single-page, batched, or alignment-guard
// fallback), and 'not_classified' for the deterministic no-LLM path. Lets a
// developer isolate AI-classified output to spot-check reconstruction /
// classification quality without wading through the auto-accepted tables.
function isAiClassified(table) {
  return table.semantic_status === 'classified'
}

function matchesStatusFilter(table, filter, reviewed) {
  if (filter === 'all') return true
  if (filter === 'reviewed') return reviewed
  if (filter === 'needs_review') {
    if (reviewed) return false
    return Boolean(table.human_review_needed) || collectReviewReasons(table).size > 0 || tableHasGarbledCells(table)
  }
  if (filter === 'no_review') {
    return !table.human_review_needed && !tableHasGarbledCells(table) && collectReviewReasons(table).size === 0
  }
  if (filter === 'dev_ai_classified') return isAiClassified(table)
  if (filter === 'dev_auto_extracted') return !isAiClassified(table)
  return collectReviewReasons(table).has(canonicalizeReviewReason(filter))
}

function ReviewBadge({ needed, reason }) {
  if (!needed) return <Badge tone="ok">No review needed</Badge>
  const label = REASON_LABELS[canonicalizeReviewReason(reason)] || 'Needs review'
  return <Badge tone="warn">{label}</Badge>
}

function DeleteConfirmDialog({ count, onCancel, onConfirm, deleting }) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  if (!mounted) return null
  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="delete-tables-title"
      aria-describedby="delete-tables-body"
      onClick={onCancel}
    >
      <div
        className="flex w-full max-w-[440px] flex-col gap-3.5 rounded-xl border border-line bg-white p-5 shadow-[0_16px_40px_rgba(16,64,63,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="delete-tables-title" className="text-[16px] font-bold text-ink">
          Delete {count === 1 ? 'this table' : `${count} tables`}?
        </div>
        <p id="delete-tables-body" className="text-[13px] leading-snug text-ink-soft">
          {count === 1
            ? 'This table will be removed from the review list. You can’t undo this without re-uploading the PDF.'
            : `These ${count} tables will be removed from the review list. You can’t undo this without re-uploading the PDF.`}
        </p>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={deleting}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            loading={deleting}
            className="!bg-[#c45c4a] hover:!bg-[#a84a3b]"
            onClick={onConfirm}
          >
            Delete
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** Normalize column names for cross-page merge eligibility. */
function tableHeaderKey(table) {
  return (table?.columns || [])
    .map((c) => String(c?.name ?? c ?? '').trim().toLowerCase().replace(/\s+/g, ' '))
    .join('|')
}

function MergeConfirmDialog({ count, onCancel, onConfirm, merging }) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  if (!mounted) return null
  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="merge-tables-title"
      aria-describedby="merge-tables-body"
      onClick={onCancel}
    >
      <div
        className="flex w-full max-w-[440px] flex-col gap-3.5 rounded-xl border border-line bg-white p-5 shadow-[0_16px_40px_rgba(16,64,63,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="merge-tables-title" className="text-[16px] font-bold text-ink">
          Merge {count} tables?
        </div>
        <p id="merge-tables-body" className="text-[13px] leading-snug text-ink-soft">
          Rows will be stacked in page order into the earliest table. The other
          {count === 2 ? ' table' : ` ${count - 1} tables`} will be removed from the list.
          Only tables with the same column headers can be merged.
        </p>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={merging}>Cancel</Button>
          <Button variant="primary" size="sm" loading={merging} onClick={onConfirm}>
            Merge
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function CollapsibleSection({ label, open, onToggle, hint, children }) {
  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="group flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-cream/80"
      >
        <span
          className={`flex h-5 w-5 flex-none items-center justify-center rounded-full border border-line bg-white text-ink-soft transition-all duration-300 ease-out group-hover:border-teal group-hover:text-teal ${open ? 'rotate-180 bg-sage/40' : 'rotate-0'}`}
          aria-hidden
        >
          <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
        </span>
        <span className="text-[11px] font-bold uppercase tracking-wide text-ink-soft group-hover:text-ink">{label}</span>
        {hint ? (
          <span className="text-[11px] font-semibold normal-case tracking-normal text-ink-soft/70">{hint}</span>
        ) : null}
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-300 ease-in-out"
        style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      >
        <div className="min-h-0 overflow-hidden">
          <div
            className={`pt-2 transition-[opacity,transform] duration-300 ease-in-out ${
              open ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1.5 opacity-0'
            }`}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}

/** Ensure every row has exactly `ncols` cells (LLM often drops Direction). */
function padRowsToColumns(rows, ncols) {
  return (rows || []).map((row) => {
    const next = Array.isArray(row) ? row.slice(0, ncols) : []
    while (next.length < ncols) next.push(null)
    return next
  })
}

function cloneColumns(columns) {
  return (columns || []).map((c) => ({
    ...c,
    header_path: Array.isArray(c?.header_path) ? [...c.header_path] : c?.header_path,
  }))
}

function columnDraftFromTable(columns) {
  return (columns || []).map((c) => ({
    name: c.name || '',
    header_group: c.header_group || '',
    header_path: Array.isArray(c.header_path) ? [...c.header_path] : null,
    role: c.role || 'unknown',
    concept: c.concept || '',
    description: c.description || '',
    data_type: c.data_type || 'unknown',
    human_review_needed: Boolean(c.human_review_needed),
    human_review_reason: c.human_review_reason || null,
    input_type: c.input_type,
    input_options: c.input_options,
    unit: c.unit,
    category: c.category,
  }))
}

function applyNameToColumnMeta(col, name) {
  const next = { ...col, name }
  const path = Array.isArray(col.header_path) && col.header_path.length
    ? [...col.header_path]
    : (col.header_group ? [col.header_group, name] : [name])
  if (path.length) path[path.length - 1] = name
  next.header_path = path
  if (path.length >= 2) next.header_group = path[path.length - 2]
  else if (!col.header_group) next.header_group = null
  return next
}

function reshapeRows(rows, mapIndex) {
  return (rows || []).map((row) => {
    const src = Array.isArray(row) ? row : []
    return mapIndex.map((old) => (old == null ? null : (src[old] ?? null)))
  })
}

/** PDF page/table crop for side-by-side review comparison. */
function PdfTableSnapshot({ jobId, tableId, maxHeightClass = 'max-h-[420px]', zoom = 1 }) {
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

function EditorZoomControls({ zoom, onChange, label }) {
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

/** Clamp editor pane zoom (50%–250%). */
function clampEditorZoom(z) {
  return Math.min(2.5, Math.max(0.5, Math.round(Number(z) * 100) / 100))
}

/**
 * Trackpad pinch (ctrl+wheel on Chrome/macOS) or ⌘/Ctrl+scroll → zoom.
 * Must use a non-passive listener so preventDefault can block browser page zoom.
 */
function bindPaneWheelZoom(el, setZoom) {
  if (!el) return () => {}
  const onWheel = (e) => {
    if (!(e.ctrlKey || e.metaKey)) return
    e.preventDefault()
    e.stopPropagation()
    const factor = Math.exp(-e.deltaY * 0.008)
    setZoom((z) => clampEditorZoom((Number(z) || 1) * factor))
  }
  el.addEventListener('wheel', onWheel, { passive: false })
  return () => el.removeEventListener('wheel', onWheel)
}

/** Read-only frozen extraction for Original tab. */
function OriginalExtractionGrid({ columns, rows, maxRows = 8 }) {
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
function ReferencePopupModal({ jobId, tableId, originalSnapshot, initialTab = 'pdf', onClose }) {
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

function ReferenceComparePanel({ jobId, tableId, originalSnapshot }) {
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

function columnHeaderGroup(col) {
  const g = col?.header_group
  if (g == null) return null
  const s = String(g).trim()
  if (!s) return null
  // Full-width table captions must never render as a parent header row.
  if (/^table\s*[:.\-–—]?\s*\S/i.test(s)) return null
  if (/^(?:statement|annex(?:ure)?)\s*[:.\-–—]?\s*\S/i.test(s)) return null
  return s
}

/** Full top→leaf header path for a column (supports 1..N levels). */
function columnHeaderPath(col) {
  const raw = col?.header_path
  if (Array.isArray(raw) && raw.length > 0) {
    const path = raw.map((p) => String(p ?? '').trim()).filter(Boolean)
    if (path.length) {
      // Drop banner-like roots that shouldn't appear as header rows.
      const filtered = path.filter((p, idx) => {
        if (idx === path.length - 1) return true
        if (/^table\s*[:.\-–—]?\s*\S/i.test(p)) return false
        if (/^(?:statement|annex(?:ure)?)\s*[:.\-–—]?\s*\S/i.test(p)) return false
        return true
      })
      return filtered.length ? filtered : [String(col?.name || '')]
    }
  }
  const name = String(col?.name || '')
  const group = columnHeaderGroup(col)
  if (group && group.toLowerCase() !== name.toLowerCase()) return [group, name]
  return name ? [name] : ['']
}

/**
 * Place a column path into a depth-tall grid.
 * Shorter paths get extra rowspan on the top label (stub columns span all levels).
 */
function placeHeaderPath(path, depth) {
  const cells = Array.from({ length: depth }, () => null)
  if (!path.length) return cells
  const extra = Math.max(0, depth - path.length)
  let row = 0
  path.forEach((label, i) => {
    const rowSpan = i === 0 ? 1 + extra : 1
    const prefix = path.slice(0, i + 1).join('\0')
    cells[row] = { label, rowSpan, prefix }
    for (let k = 1; k < rowSpan; k += 1) cells[row + k] = { covered: true }
    row += rowSpan
  })
  return cells
}

/**
 * Build N header rows with colspan/rowspan for arbitrary header depth.
 * Returns { depth, rows } where rows[r] is an array of visible segments.
 */
function buildMultiLevelHeaderRows(columns) {
  const cols = columns || []
  const paths = cols.map((c) => columnHeaderPath(c))
  const depth = Math.max(1, ...paths.map((p) => p.length))
  const grid = paths.map((p) => placeHeaderPath(p, depth))

  const rows = []
  for (let r = 0; r < depth; r += 1) {
    const segs = []
    let c = 0
    while (c < cols.length) {
      const cell = grid[c][r]
      if (!cell || cell.covered) {
        c += 1
        continue
      }
      let colSpan = 1
      while (
        c + colSpan < cols.length
        && grid[c + colSpan][r]
        && !grid[c + colSpan][r].covered
        && grid[c + colSpan][r].prefix === cell.prefix
        && grid[c + colSpan][r].rowSpan === cell.rowSpan
      ) {
        colSpan += 1
      }
      segs.push({
        key: `h-${r}-${c}`,
        label: cell.label,
        colSpan,
        rowSpan: cell.rowSpan,
        start: c,
        isLeaf: r + cell.rowSpan === depth,
      })
      c += colSpan
    }
    rows.push(segs)
  }
  return { depth, rows }
}

/**
 * Editor header layout: same rowspan rules as the review preview.
 * Ungrouped columns span the full header height — no empty "Group…" slots.
 * Parent group cells appear only when a column actually has group labels
 * (or the user adds/assigns a group via the toolbar).
 */
function buildEditorHeaderRows(columns) {
  const cols = columns || []
  const paths = cols.map((c) => columnHeaderPath(c))
  const depth = Math.max(1, ...paths.map((p) => p.length))
  const grid = paths.map((p) => placeHeaderPath(p, depth))

  const rows = []
  for (let r = 0; r < depth; r += 1) {
    const segs = []
    let c = 0
    while (c < cols.length) {
      const cell = grid[c][r]
      if (!cell || cell.covered) {
        c += 1
        continue
      }
      let colSpan = 1
      while (
        c + colSpan < cols.length
        && grid[c + colSpan][r]
        && !grid[c + colSpan][r].covered
        && grid[c + colSpan][r].prefix === cell.prefix
        && grid[c + colSpan][r].rowSpan === cell.rowSpan
      ) {
        colSpan += 1
      }
      segs.push({
        key: `eh-${r}-${c}`,
        label: cell.label,
        colSpan,
        rowSpan: cell.rowSpan,
        start: c,
        isLeaf: r + cell.rowSpan === depth,
        empty: false,
      })
      c += colSpan
    }
    rows.push(segs)
  }
  return { depth, rows }
}

function ExtractedTableHead({ columns, lockedCols = [], sticky = false, showIndex = false }) {
  const { depth, rows } = buildMultiLevelHeaderRows(columns)
  const rowRefs = useRef([])
  // Sticky `top` must match each row's real offset or the leaf row hangs over the body.
  const [stickyTops, setStickyTops] = useState(() => Array.from({ length: Math.max(depth, 1) }, () => 0))
  const headerSig = `${depth}:${(columns || []).map((c) => columnHeaderPath(c).join('\u0001')).join('\u0002')}`

  useLayoutEffect(() => {
    if (!sticky) return undefined
    const measure = () => {
      const baseEl = rowRefs.current[0]
      if (!baseEl) return
      const base = baseEl.getBoundingClientRect().top
      const tops = rows.map((_, i) => {
        const el = rowRefs.current[i]
        if (!el) return 0
        // Prefer row box; fall back to first cell if rowspan collapses tr height to 0.
        let top = Math.round(el.getBoundingClientRect().top - base)
        if (i > 0 && top <= 0) {
          const th = el.querySelector('th')
          if (th) top = Math.round(th.getBoundingClientRect().top - base)
        }
        return Math.max(0, top)
      })
      setStickyTops((prev) => (
        prev.length === tops.length && prev.every((v, i) => v === tops[i]) ? prev : tops
      ))
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    rowRefs.current.forEach((el) => { if (el) ro?.observe(el) })
    window.addEventListener('resize', measure)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [sticky, headerSig, rows])

  // Don't stick multi-level headers until offsets are known — fixed guesses overlap row 1.
  const stickyOn = sticky && (
    depth <= 1 || stickyTops.length >= depth && stickyTops.every((t, i) => i === 0 || t > 0)
  )

  const thFor = (seg, isIndex = false) => {
    const isGroup = !isIndex && depth > 1 && !seg.isLeaf
    if (stickyOn) {
      return [
        // One teal for every header level — groups used to be teal-deep.
        'sticky max-w-0 px-1 pt-0.5 pb-1 align-top font-sans text-[10px] font-medium leading-snug tracking-wide text-cream bg-teal',
        // Same teal rule between levels as between columns.
        'border-x border-b border-teal-deep/40',
        isGroup ? 'text-center font-semibold' : 'text-left',
        isIndex ? 'text-center' : '',
      ].filter(Boolean).join(' ')
    }
    if (sticky) {
      // Pre-measure: same chrome, not sticky yet (avoids body overlap).
      return [
        'max-w-0 px-1 pt-0.5 pb-1 align-top font-sans text-[10px] font-medium leading-snug tracking-wide text-cream bg-teal',
        'border-x border-b border-teal-deep/40',
        isGroup ? 'text-center font-semibold' : 'text-left',
        isIndex ? 'text-center' : '',
      ].filter(Boolean).join(' ')
    }
    return [
      'max-w-0 px-2.5 py-1.5 align-top font-sans text-[11.5px] uppercase tracking-wide text-cream bg-teal',
      'border-x border-b border-teal-deep/35',
      isGroup ? 'text-center font-semibold' : 'text-left font-medium',
      isIndex || seg.colSpan > 1 || seg.rowSpan > 1 ? 'text-center' : '',
    ].filter(Boolean).join(' ')
  }

  return (
    <thead className="bg-teal">
      {rows.map((segs, r) => (
        <tr
          key={`hr-${r}`}
          ref={(el) => { rowRefs.current[r] = el }}
          className="bg-teal"
        >
          {showIndex && r === 0 ? (
            <th
              className={thFor({ isLeaf: true, colSpan: 1, rowSpan: depth }, true)}
              rowSpan={depth}
              style={stickyOn ? { top: stickyTops[0] ?? 0, zIndex: 2 } : undefined}
            >
              #
            </th>
          ) : null}
          {segs.map((seg) => {
            const showLocked = seg.isLeaf && lockedCols[seg.start]
            return (
              <th
                key={seg.key}
                colSpan={seg.colSpan > 1 ? seg.colSpan : undefined}
                rowSpan={seg.rowSpan > 1 ? seg.rowSpan : undefined}
                className={thFor(seg)}
                style={stickyOn ? { top: stickyTops[r] ?? 0, zIndex: 2 + r } : undefined}
                title={showLocked ? `${seg.label} — read-only` : seg.label}
              >
                <span className="block min-w-0 whitespace-normal break-words [overflow-wrap:anywhere] hyphens-auto leading-snug">
                  {seg.label}
                  {showLocked ? (
                    <span className={`font-semibold normal-case tracking-normal text-cream/70 ${(sticky || stickyOn) ? 'mt-0.5 block' : 'ml-1'}`}>
                      {(sticky || stickyOn) ? 'locked' : '· locked'}
                    </span>
                  ) : null}
                </span>
              </th>
            )
          })}
        </tr>
      ))}
    </thead>
  )
}

function isEmptyMergeCell(value) {
  if (value === null || value === undefined) return true
  const s = String(value).trim()
  if (!s) return true
  return s === '—' || s === '–' || s === '-' || s === '−' || s === '‒'
}

function isNumericishCell(value) {
  if (value === null || value === undefined) return false
  const s = String(value).replace(/,/g, '').replace(/%/g, '').replace(/\*/g, '').trim()
  if (!s || isEmptyMergeCell(s)) return false
  return /^-?\d+(\.\d+)?$/.test(s)
}

/** Label / stub columns where PDF rowspan is common (not measure columns). */
function isBodyLabelColumn(colIdx, columns, rows) {
  const name = String(columns?.[colIdx]?.name || '').toLowerCase()
  if (
    /^(sl\.?\s*no\.?|s\.?\s*no\.?|sno|item|name|indicator|state|district|disease|particulars|description|category|sector|occupation|education|sex)$/i.test(
      name,
    )
    || name.includes('name of')
    || name.includes('local body')
    || name.includes('disease')
    || name.includes('district')
    || name === 'sex'
  ) {
    return true
  }
  const vals = (rows || [])
    .map((row) => (Array.isArray(row) ? row[colIdx] : null))
    .filter((v) => !isEmptyMergeCell(v))
  if (vals.length < 1) return false
  const numeric = vals.filter((v) => isNumericishCell(v)).length
  // Mostly non-numeric values → treat as a label column eligible for rowspan.
  return numeric <= vals.length * 0.35
}

function isSummaryLabel(value) {
  if (isEmptyMergeCell(value)) return false
  const s = String(value).trim().toLowerCase()
  // Exact ALL/TOTAL, or "Total (…)" / "ALL (…)" — not "All ages" / "All India".
  if (/^(all|total|overall|aggregate)$/.test(s)) return true
  if (/^grand\s*total$/.test(s)) return true
  if (/^(all|total)\s*[\(:]/.test(s)) return true
  return false
}

/**
 * Reconstruct body cell merges from empty cells under label columns and
 * sparse measure columns (pymupdf leaves rowspan/colspan continuations empty).
 *
 * Returns spans[r][c] = { rowSpan, colSpan } or null when covered by a prior merge.
 *
 * Vertical spans stop when:
 *  - a label column to the left introduces a new value, or
 *  - a sibling group label changes (e.g. Item "Others" → "ALL"), or
 *  - a table-footer summary row (last row with TOTAL/ALL in Sex etc.) would
 *    otherwise absorb blank Sl. No. / District cells from the group above.
 * Measure-column rowspans (e.g. shared population) only stop at the next
 * non-empty cell — they intentionally span different stub labels.
 */
function buildBodyCellSpans(rows, columns) {
  const nrows = (rows || []).length
  const ncols = (columns || []).length
  const spans = Array.from({ length: nrows }, () => Array.from({ length: ncols }, () => ({ rowSpan: 1, colSpan: 1 })))
  if (!nrows || !ncols) return spans

  const labelCols = []
  for (let c = 0; c < ncols; c += 1) {
    if (isBodyLabelColumn(c, columns, rows)) labelCols.push(c)
  }
  if (!labelCols.length) return spans

  const labelSet = new Set(labelCols)

  // Sparse identity cols (Sl. No. / Name with rowspan empties).
  const sparseIdentityCols = []
  // Dense high-cardinality labels (Item lists) — only break on summary transitions.
  const denseSummaryBreakCols = []
  for (const c of labelCols) {
    const colName = String(columns?.[c]?.name || '').toLowerCase()
    if (/^(sex|gender)$/.test(colName)) continue

    let empty = 0
    const nonEmpty = []
    for (let r = 0; r < nrows; r += 1) {
      const v = rows[r]?.[c]
      if (isEmptyMergeCell(v)) empty += 1
      else nonEmpty.push(String(v).trim().toLowerCase())
    }
    if (empty >= 1 && empty >= nrows * 0.12 && empty < nrows) {
      sparseIdentityCols.push(c)
      continue
    }
    if (nonEmpty.length >= 2) {
      const unique = new Set(nonEmpty)
      if (unique.size >= Math.max(3, Math.ceil(nonEmpty.length * 0.75))) {
        denseSummaryBreakCols.push(c)
      }
    }
  }

  const covered = Array.from({ length: nrows }, () => Array(ncols).fill(false))

  const leftBoundaryAt = (rowIdx, colIdx) => {
    for (const lc of labelCols) {
      if (lc >= colIdx) break
      if (!isEmptyMergeCell(rows[rowIdx]?.[lc])) return true
    }
    return false
  }

  const rowHasSummaryLabel = (rowIdx) => (
    labelCols.some((lc) => isSummaryLabel(rows[rowIdx]?.[lc]))
  )

  const siblingLabelBreakAt = (startRow, rowIdx, colIdx) => {
    // Sparse siblings: any new value ends the span (Name under DCB → Total block).
    for (const lc of sparseIdentityCols) {
      if (lc === colIdx) continue
      const startV = rows[startRow]?.[lc]
      const v = rows[rowIdx]?.[lc]
      if (isEmptyMergeCell(v)) continue
      if (isEmptyMergeCell(startV)) return true
      if (String(startV).trim().toLowerCase() !== String(v).trim().toLowerCase()) return true
    }

    // Dense Item-like cols: only break on summary transitions (Others → ALL),
    // not on normal list changes (South → South West) that would kill Sl. No. rowspan.
    for (const lc of denseSummaryBreakCols) {
      if (lc === colIdx) continue
      const startV = rows[startRow]?.[lc]
      const v = rows[rowIdx]?.[lc]
      if (isEmptyMergeCell(v)) continue
      if (isEmptyMergeCell(startV)) {
        if (isSummaryLabel(v)) return true
        continue
      }
      if (String(startV).trim().toLowerCase() !== String(v).trim().toLowerCase()) {
        if (isSummaryLabel(v) || isSummaryLabel(startV)) return true
      }
    }

    // Footer / grand-total row: blank identity cells must stay unmerged.
    if (rowHasSummaryLabel(rowIdx) && rowIdx === nrows - 1) return true

    return false
  }

  const measureCols = []
  for (let c = 0; c < ncols; c += 1) {
    if (!labelSet.has(c)) measureCols.push(c)
  }

  const isSectionBannerRow = (rowIdx) => {
    if (!measureCols.length) return false
    const measuresEmpty = measureCols.every((c) => isEmptyMergeCell(rows[rowIdx]?.[c]))
    if (!measuresEmpty) return false
    return labelCols.some((c) => {
      const v = rows[rowIdx]?.[c]
      return !isEmptyMergeCell(v) && !isNumericishCell(v)
    })
  }

  // Left → right so horizontal merges (Total across Sl.No + Name) claim cells first.
  for (const c of labelCols) {
    let r = 0
    while (r < nrows) {
      if (covered[r][c]) {
        r += 1
        continue
      }
      if (isEmptyMergeCell(rows[r]?.[c])) {
        spans[r][c] = { rowSpan: 1, colSpan: 1 }
        r += 1
        continue
      }
      let rowSpan = 1
      while (r + rowSpan < nrows && isEmptyMergeCell(rows[r + rowSpan]?.[c])) {
        if (leftBoundaryAt(r + rowSpan, c)) break
        if (siblingLabelBreakAt(r, r + rowSpan, c)) break
        rowSpan += 1
      }
      let colSpan = 1
      // Extend across adjacent empty label cells for the same vertical run (e.g. Total).
      while (labelSet.has(c + colSpan)) {
        let ok = true
        for (let dr = 0; dr < rowSpan; dr += 1) {
          const rr = r + dr
          const cc = c + colSpan
          if (covered[rr][cc] || !isEmptyMergeCell(rows[rr]?.[cc])) {
            ok = false
            break
          }
          if (leftBoundaryAt(rr, c)) {
            ok = false
            break
          }
        }
        if (!ok) break
        colSpan += 1
      }
      // Section banners (Delhi / All India / District wise…) colspan into empty measure cols.
      if (rowSpan === 1 && isSectionBannerRow(r)) {
        while (c + colSpan < ncols && measureCols.includes(c + colSpan)) {
          if (covered[r][c + colSpan] || !isEmptyMergeCell(rows[r]?.[c + colSpan])) break
          colSpan += 1
        }
      }
      spans[r][c] = { rowSpan, colSpan }
      for (let dr = 0; dr < rowSpan; dr += 1) {
        for (let dc = 0; dc < colSpan; dc += 1) {
          if (dr === 0 && dc === 0) continue
          covered[r + dr][c + dc] = true
          spans[r + dr][c + dc] = null
        }
      }
      r += rowSpan
    }
  }

  // Sparse measure columns (e.g. population merged across several local bodies).
  // Do not apply left-label boundary breaks — the merge intentionally spans
  // different stub values (MCD / NDMC / DCB under one population cell).
  for (let c = 0; c < ncols; c += 1) {
    if (labelSet.has(c)) continue
    let empty = 0
    for (let r = 0; r < nrows; r += 1) {
      if (isEmptyMergeCell(rows[r]?.[c])) empty += 1
    }
    if (!(empty >= 1 && empty >= nrows * 0.12 && empty < nrows)) continue

    let r = 0
    while (r < nrows) {
      if (covered[r][c]) {
        r += 1
        continue
      }
      if (isEmptyMergeCell(rows[r]?.[c])) {
        spans[r][c] = { rowSpan: 1, colSpan: 1 }
        r += 1
        continue
      }
      let rowSpan = 1
      while (r + rowSpan < nrows && isEmptyMergeCell(rows[r + rowSpan]?.[c])) {
        rowSpan += 1
      }
      if (rowSpan === 1) {
        r += 1
        continue
      }
      spans[r][c] = { rowSpan, colSpan: 1 }
      for (let dr = 1; dr < rowSpan; dr += 1) {
        covered[r + dr][c] = true
        spans[r + dr][c] = null
      }
      r += rowSpan
    }
  }

  for (let r = 0; r < nrows; r += 1) {
    for (let c = 0; c < ncols; c += 1) {
      if (covered[r][c]) spans[r][c] = null
    }
  }
  return spans
}

function isUsableTableTitle(title, columns) {
  const t = String(title || '').trim()
  if (!t || t.length < 4) return false
  // Truncated PDF wrap leftovers like "Direc-"
  if (/[–—-]$/.test(t)) return false
  // Joined header rows — not a real table title
  if (t.includes(' · ') || (t.match(/\|/g) || []).length >= 2) return false
  const colNames = (columns || [])
    .map((c) => String(c?.name ?? c ?? '').trim().toLowerCase())
    .filter(Boolean)
  const low = t.toLowerCase()
  const stem = low.replace(/[–—-]+$/g, '')
  for (const c of colNames) {
    if (low === c) return false
    if (stem.length <= 16 && (c.startsWith(stem) || c.includes(stem))) return false
  }
  return true
}

function displayTitle(table) {
  const t = (table?.title || '').trim()
  if (isUsableTableTitle(t, table?.columns)) return t
  return null
}

function titleForEdit(table) {
  return displayTitle(table) || ''
}

/** Direction / Trend columns store up|down|same; show arrow symbols in the UI. */
const DIRECTION_SYMBOLS = {
  up: { symbol: '↑', label: 'Up', Icon: ArrowUp, className: 'text-[#2f7a3e]' },
  down: { symbol: '↓', label: 'Down', Icon: ArrowDown, className: 'text-[#c45c4a]' },
  same: { symbol: '–', label: 'Same', Icon: Minus, className: 'text-[#8a8478]' },
}

function isDirectionLikeColumn(col) {
  const blob = `${col?.name || ''} ${col?.concept || ''}`.toLowerCase()
  return ['direction', 'trend', 'change'].some((k) => blob.includes(k))
}

function directionDisplay(value) {
  if (value == null || value === '') return null
  const key = String(value).trim().toLowerCase()
  if (DIRECTION_SYMBOLS[key]) return DIRECTION_SYMBOLS[key]
  // Already a symbol from an older extract
  if (key === '↑' || key === '▲' || key === '⬆') return DIRECTION_SYMBOLS.up
  if (key === '↓' || key === '▼' || key === '⬇') return DIRECTION_SYMBOLS.down
  if (key === '–' || key === '—' || key === '−' || key === '‒') return DIRECTION_SYMBOLS.same
  return null
}

function DirectionGlyph({ dir, className = '' }) {
  if (!dir?.Icon) return null
  const Icon = dir.Icon
  return (
    <Icon
      className={`h-4 w-4 ${dir.className} ${className}`}
      strokeWidth={2.25}
      aria-hidden
    />
  )
}

function directionSelectOptions(inputOptions) {
  const base = Array.isArray(inputOptions) && inputOptions.length > 0
    ? inputOptions.map((o) => String(o))
    : ['up', 'down', 'same']
  const seen = new Set()
  const opts = []
  for (const raw of [...base, 'up', 'down', 'same']) {
    const key = raw.trim().toLowerCase()
    if (!DIRECTION_SYMBOLS[key] || seen.has(key)) continue
    seen.add(key)
    opts.push(key)
  }
  return opts
}

/** Spreadsheet cell textarea that grows to show all wrapped text. */
function AutoGrowTextarea({
  value,
  onChange,
  className,
  style,
  placeholder,
  title,
  readOnly = false,
}) {
  const ref = useRef(null)

  const syncHeight = () => {
    const el = ref.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.max(el.scrollHeight, 22)}px`
  }

  useLayoutEffect(() => {
    syncHeight()
  }, [value])

  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => syncHeight()) : null
    ro?.observe(el)
    // Parent width changes (column resize / zoom) also need a remeasure.
    const parent = el.parentElement
    if (parent) ro?.observe(parent)
    window.addEventListener('resize', syncHeight)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', syncHeight)
    }
  }, [])

  return (
    <textarea
      ref={ref}
      rows={1}
      readOnly={readOnly}
      className={`${className} overflow-hidden outline-none ring-0 focus:outline-none focus:ring-0 ${readOnly ? 'cursor-default caret-transparent' : ''}`}
      style={style}
      value={value}
      placeholder={placeholder}
      title={title}
      onChange={(e) => {
        if (readOnly) return
        onChange(e.target.value)
        // Grow immediately on keystroke before React commits the new value height.
        requestAnimationFrame(syncHeight)
      }}
      onInput={syncHeight}
    />
  )
}

/** Spreadsheet-style cell for extracted PDF rows (preview + full-table modal). */
function ExtractedDataCell({
  value,
  sourceValue,
  col,
  locked,
  onChange,
  fitWidth = false,
}) {
  const flagged = isGarbled(sourceValue) || (value == null && col?.input_type === 'dropdown')
  const editable = !locked
  const directionCol = isDirectionLikeColumn(col)
  const dir = directionDisplay(value)
  const dropdownOptions =
    editable && col?.input_type === 'dropdown' && Array.isArray(col.input_options) && col.input_options.length > 0
      ? col.input_options
      : null
  const controlWidth = fitWidth ? 'w-full min-w-0 max-w-full' : 'w-full min-w-[4.5rem]'
  const fitStyle = fitWidth ? { minWidth: 0, width: '100%', maxWidth: '100%' } : undefined

  if (editable && (dropdownOptions || directionCol)) {
    const opts = directionCol ? directionSelectOptions(dropdownOptions || col?.input_options) : dropdownOptions
    return (
      <select
        className={`${controlWidth} box-border rounded-none border-0 bg-transparent px-1 py-0.5 text-[12.5px] outline-none ring-0 focus:outline-none focus:ring-0 ${flagged ? 'bg-[#fff8e1]' : ''} ${dir?.className || ''}`}
        style={fitStyle}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        title={dir ? dir.label : undefined}
        aria-label={col?.name || 'Direction'}
      >
        <option value="">{directionCol ? '' : '—'}</option>
        {opts.map((opt) => {
          const d = directionDisplay(opt)
          return (
            <option key={opt} value={opt} title={d?.label || opt}>
              {d ? d.symbol : opt}
            </option>
          )
        })}
      </select>
    )
  }

  if (editable && !directionCol) {
    const text = value ?? ''
    return (
      <AutoGrowTextarea
        value={text}
        onChange={onChange}
        className={`${controlWidth} box-border resize-none appearance-none rounded-none border-0 bg-transparent px-1.5 py-1 text-[12.5px] leading-snug [overflow-wrap:anywhere] break-words whitespace-pre-wrap shadow-none outline-none focus-visible:outline-none ${flagged ? 'bg-[#fff8e1]' : ''}`}
        style={fitStyle}
      />
    )
  }

  if (directionCol || dir) {
    if (!dir) {
      return <span className="inline-block min-h-[1em]" aria-hidden="true" />
    }
    return (
      <span className="inline-flex items-center justify-center" title={dir.label} aria-label={dir.label}>
        <DirectionGlyph dir={dir} />
      </span>
    )
  }

  const display = value === null || value === undefined || value === '' ? null : String(value)
  return (
    <span
      className={`block min-w-0 whitespace-normal break-words [overflow-wrap:anywhere] leading-snug ${display == null ? 'italic text-[#a49c8e]' : 'text-ink'}`}
      title={display || ''}
    >
      {display == null ? '—' : display}
    </span>
  )
}


function spansFromExplicitMerges(nrows, ncols, merges) {
  const spans = Array.from({ length: nrows }, () => Array.from({ length: ncols }, () => ({ rowSpan: 1, colSpan: 1 })))
  const covered = Array.from({ length: nrows }, () => Array.from({ length: ncols }, () => false))
  for (const m of merges || []) {
    const r = m.r
    const c = m.c
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    if (r < 0 || c < 0 || r >= nrows || c >= ncols) continue
    if (covered[r][c]) continue
    spans[r][c] = { rowSpan: rs, colSpan: cs }
    for (let dr = 0; dr < rs; dr += 1) {
      for (let dc = 0; dc < cs; dc += 1) {
        const rr = r + dr
        const cc = c + dc
        if (rr >= nrows || cc >= ncols) continue
        if (dr || dc) {
          covered[rr][cc] = true
          spans[rr][cc] = null
        }
      }
    }
  }
  return spans
}

/** Collect multi-cell spans as explicit merge records. */
function mergesFromSpans(spans) {
  const out = []
  for (let r = 0; r < (spans || []).length; r += 1) {
    for (let c = 0; c < (spans[r] || []).length; c += 1) {
      const s = spans[r][c]
      if (!s) continue
      if ((s.rowSpan || 1) > 1 || (s.colSpan || 1) > 1) {
        out.push({ r, c, rowSpan: s.rowSpan || 1, colSpan: s.colSpan || 1 })
      }
    }
  }
  return out
}

/**
 * Explicit merges (non-empty list, or locked empty after Unmerge) win.
 * Otherwise auto-infer rowspans from empty cells under labels / measures.
 */
function resolveEditorBodySpans(rows, columns, explicitMerges, mergesExplicit = false) {
  const nrows = (rows || []).length
  const ncols = (columns || []).length
  if (mergesExplicit || (explicitMerges || []).length > 0) {
    return spansFromExplicitMerges(nrows, ncols, explicitMerges || [])
  }
  return buildBodyCellSpans(rows, columns)
}

function findMergeCovering(merges, r, c) {
  return (merges || []).find((m) => {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    return r >= m.r && r < m.r + rs && c >= m.c && c < m.c + cs
  }) || null
}

/** Find the origin cell of a visible body span covering (r, c). */
function findBodySpanOrigin(spans, r, c) {
  const direct = spans?.[r]?.[c]
  if (direct) return { r, c, span: direct }
  for (let rr = 0; rr <= r; rr += 1) {
    for (let cc = 0; cc <= c; cc += 1) {
      const s = spans?.[rr]?.[cc]
      if (!s) continue
      const rs = Math.max(1, s.rowSpan || 1)
      const cs = Math.max(1, s.colSpan || 1)
      if (r >= rr && r < rr + rs && c >= cc && c < cc + cs) {
        return { r: rr, c: cc, span: s }
      }
    }
  }
  return null
}

/**
 * Materialize auto-inferred spans if needed, then drop the merge covering (r, c).
 * Always returns an explicit merge list so Unmerge sticks (even when empty).
 */
function unmergeAt(rows, columns, cellMerges, mergesExplicit, r, c) {
  const spans = resolveEditorBodySpans(rows, columns, cellMerges, mergesExplicit)
  const origin = findBodySpanOrigin(spans, r, c)
  if (!origin || ((origin.span.rowSpan || 1) <= 1 && (origin.span.colSpan || 1) <= 1)) {
    return null
  }
  let base = mergesExplicit || (cellMerges || []).length > 0
    ? (cellMerges || []).map((m) => ({ ...m }))
    : mergesFromSpans(spans)
  base = base.filter((m) => {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    const coversOrigin = origin.r >= m.r && origin.r < m.r + rs && origin.c >= m.c && origin.c < m.c + cs
    return !coversOrigin
  })
  return {
    cellMerges: base,
    mergesExplicit: true,
    flash: {
      axis: 'cells',
      from: {
        r0: origin.r,
        r1: origin.r + Math.max(1, origin.span.rowSpan || 1) - 1,
        c0: origin.c,
        c1: origin.c + Math.max(1, origin.span.colSpan || 1) - 1,
      },
      to: { r0: origin.r, r1: origin.r, c0: origin.c, c1: origin.c },
    },
  }
}

/** Snapshot whatever merges are currently visible (explicit or auto-inferred). */
function materializeCellMerges(rows, columns, cellMerges, mergesExplicit) {
  if (mergesExplicit || (cellMerges || []).length > 0) {
    return (cellMerges || []).map((m) => ({
      r: m.r,
      c: m.c,
      rowSpan: Math.max(1, Number(m.rowSpan) || 1),
      colSpan: Math.max(1, Number(m.colSpan) || 1),
    }))
  }
  return mergesFromSpans(resolveEditorBodySpans(rows, columns, cellMerges, false))
}

/**
 * Before deleting row `idx`, copy merge-origin values into the next row of the
 * span so rowspan content (e.g. Sl. No. "A") is not discarded with the origin.
 */
function promoteMergeValuesBeforeRowDelete(rows, merges, idx) {
  const next = (rows || []).map((row) => (Array.isArray(row) ? [...row] : row))
  for (const m of merges || []) {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    if (m.r !== idx || rs <= 1) continue
    const dest = idx + 1
    if (!next[dest]) continue
    for (let dc = 0; dc < cs; dc += 1) {
      const c = m.c + dc
      if (c < 0 || c >= next[dest].length) continue
      if (isEmptyMergeCell(next[dest][c])) {
        next[dest][c] = next[idx]?.[c] ?? null
      }
    }
  }
  return next
}

/**
 * Remap explicit merges after removing row `idx`.
 * Deleting a merge origin keeps the remaining span (value already promoted).
 */
function adjustMergesAfterRowDelete(merges, idx) {
  return (merges || [])
    .map((m) => {
      const rs = Math.max(1, Number(m.rowSpan) || 1)
      const cs = Math.max(1, Number(m.colSpan) || 1)
      const end = m.r + rs - 1
      if (end < idx) return { r: m.r, c: m.c, rowSpan: rs, colSpan: cs }
      if (m.r > idx) return { r: m.r - 1, c: m.c, rowSpan: rs, colSpan: cs }
      if (m.r === idx) {
        if (rs <= 1) return null
        // After deleting the origin row, the rest of the block starts at `idx`.
        return { r: idx, c: m.c, rowSpan: rs - 1, colSpan: cs }
      }
      // idx is inside the span below the origin.
      return { r: m.r, c: m.c, rowSpan: rs - 1, colSpan: cs }
    })
    .filter(Boolean)
    .filter((m) => m.rowSpan > 1 || m.colSpan > 1)
}

function adjustMergesAfterRowInsert(merges, idx) {
  return (merges || []).map((m) => {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    if (m.r >= idx) return { r: m.r + 1, c: m.c, rowSpan: rs, colSpan: cs }
    const end = m.r + rs - 1
    if (idx > m.r && idx <= end) return { r: m.r, c: m.c, rowSpan: rs + 1, colSpan: cs }
    return { r: m.r, c: m.c, rowSpan: rs, colSpan: cs }
  }).filter((m) => m.rowSpan > 1 || m.colSpan > 1)
}

function selectionRect(sel) {
  if (!sel) return null
  return {
    r0: Math.min(sel.r0, sel.r1),
    r1: Math.max(sel.r0, sel.r1),
    c0: Math.min(sel.c0, sel.c1),
    c1: Math.max(sel.c0, sel.c1),
  }
}

function setHeaderPathLevel(columns, start, colSpan, levelIdx, label) {
  const text = String(label || '').trim()
  const depth = Math.max(1, ...(columns || []).map((c) => columnHeaderPath(c).length))
  return (columns || []).map((col, i) => {
    if (i < start || i >= start + colSpan) return col
    const current = columnHeaderPath(col)
    const leaf = current[current.length - 1] || col.name || `Column ${i + 1}`
    // Flat pad so short paths expose editable ancestor slots above the leaf.
    const padded = Array.from({ length: depth }, () => '')
    const offset = Math.max(0, depth - current.length)
    current.forEach((p, j) => { padded[offset + j] = p })
    padded[Math.min(levelIdx, depth - 1)] = text
    // Drop leading empty ancestors; keep leaf.
    let startIdx = 0
    while (startIdx < depth - 1 && !String(padded[startIdx] || '').trim()) startIdx += 1
    const path = padded.slice(startIdx).map((p, idx, arr) => {
      const s = String(p || '').trim()
      if (s) return s
      return idx === arr.length - 1 ? leaf : `Level ${idx + 1}`
    })
    const name = path[path.length - 1] || leaf
    const header_group = path.length >= 2 ? path[path.length - 2] : null
    return {
      ...col,
      name,
      header_group,
      header_path: path,
    }
  })
}

/** Unique immediate parent group labels across columns (for the group picker). */
function listExistingHeaderGroups(columns) {
  const seen = new Set()
  const out = []
  for (const col of columns || []) {
    const path = columnHeaderPath(col)
    if (path.length < 2) continue
    const g = path[path.length - 2]
    if (!g || seen.has(g)) continue
    seen.add(g)
    out.push(g)
  }
  return out
}

/** Parent path (everything above the leaf) for a column. */
function columnParentPath(col) {
  const path = columnHeaderPath(col)
  return path.length >= 2 ? path.slice(0, -1) : []
}

/** Apply a parent path (above the leaf) to one column. */
function withParentPath(col, parents) {
  const leaf = col?.name || columnHeaderPath(col).slice(-1)[0] || 'Column'
  const clean = (parents || []).map((p) => String(p || '').trim()).filter(Boolean)
  if (!clean.length) {
    return { ...col, name: leaf, header_group: null, header_path: [leaf] }
  }
  return {
    ...col,
    name: leaf,
    header_group: clean[clean.length - 1],
    header_path: [...clean, leaf],
  }
}

/**
 * Reorder a contiguous column range [from, from+count) so it lands before
 * insertAt in the original index space (insertAt may equal n to append).
 */
function reorderColumnRange(columns, rows, cellMerges, from, count, insertAt) {
  const n = (columns || []).length
  if (count < 1 || from < 0 || from + count > n) {
    return { columns, rows, cellMerges }
  }
  let dest = Math.max(0, Math.min(insertAt, n))
  if (dest >= from && dest <= from + count) {
    return { columns, rows, cellMerges }
  }
  const cols = [...columns]
  const moved = cols.splice(from, count)
  if (dest > from) dest -= count
  cols.splice(dest, 0, ...moved)

  const order = []
  for (let i = 0; i < n; i += 1) {
    if (i >= from && i < from + count) continue
    order.push(i)
  }
  const movedIdx = Array.from({ length: count }, (_, i) => from + i)
  order.splice(dest, 0, ...movedIdx)
  const remap = (c) => {
    const idx = order.indexOf(c)
    return idx >= 0 ? idx : c
  }
  const nextMerges = (cellMerges || []).map((m) => ({
    ...m,
    c: remap(m.c),
  }))
  return {
    columns: cols,
    rows: reshapeRows(rows, order),
    cellMerges: nextMerges,
  }
}

/** Move contiguous rows [from, from+count) so they land before insertAt. */
function reorderRowRange(rows, cellMerges, from, count, insertAt) {
  const n = (rows || []).length
  if (count < 1 || from < 0 || from + count > n) {
    return { rows, cellMerges }
  }
  let dest = Math.max(0, Math.min(insertAt, n))
  if (dest >= from && dest <= from + count) {
    return { rows, cellMerges }
  }
  const nextRows = [...rows]
  const moved = nextRows.splice(from, count)
  if (dest > from) dest -= count
  nextRows.splice(dest, 0, ...moved)

  const order = []
  for (let i = 0; i < n; i += 1) {
    if (i >= from && i < from + count) continue
    order.push(i)
  }
  const movedIdx = Array.from({ length: count }, (_, i) => from + i)
  order.splice(dest, 0, ...movedIdx)
  const remap = (r) => {
    const idx = order.indexOf(r)
    return idx >= 0 ? idx : r
  }
  const nextMerges = (cellMerges || []).map((m) => ({
    ...m,
    r: remap(m.r),
  }))
  return { rows: nextRows, cellMerges: nextMerges }
}

/** Snapshot of editable table structure for one-step undo/redo. */
function cloneEditorStructure(draft) {
  return {
    columns: cloneColumns(draft.columns || []),
    rows: (draft.rows || []).map((row) => (Array.isArray(row) ? [...row] : row)),
    cellMerges: Array.isArray(draft.cellMerges)
      ? draft.cellMerges.map((m) => ({ ...m }))
      : [],
    mergesExplicit: Boolean(draft.mergesExplicit),
  }
}

function invertActionFlash(flash) {
  if (!flash) return null
  return {
    ...flash,
    from: flash.to ? { ...flash.to } : null,
    to: flash.from ? { ...flash.from } : null,
  }
}

/** Where a moved block lands after reorderColumnRange / reorderRowRange. */
function movedBlockFlash(axis, from, count, insertAt) {
  if (count < 1) return null
  const end = from + count - 1
  if (insertAt >= from && insertAt <= from + count) return null
  let newStart = from
  if (insertAt <= from) newStart = insertAt
  else if (insertAt > end) newStart = insertAt - count
  else return null
  return {
    axis,
    from: { start: from, end },
    to: { start: newStart, end: newStart + count - 1 },
  }
}

function flashCovers(flashPart, index) {
  if (!flashPart) return false
  return index >= flashPart.start && index <= flashPart.end
}

/** Labeled tool cluster for the table editor (beginner-friendly grouping). */
function EditorToolSection({ icon: Icon, title, hint, children, accent = 'teal' }) {
  const accents = {
    teal: 'border-teal/25 bg-[#F3F8F7]',
    amber: 'border-[#e6d4a0] bg-[#FFF9EB]',
    rose: 'border-[#e8c4bc] bg-[#FFF6F4]',
  }
  return (
    <div className={`rounded-xl border px-3 py-2.5 ${accents[accent] || accents.teal}`}>
      <div className="mb-2 flex items-start gap-2">
        <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-white/80 text-teal shadow-sm">
          <Icon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="text-[12px] font-bold tracking-tight text-ink">{title}</div>
          {hint ? <div className="text-[11px] leading-snug text-ink-soft">{hint}</div> : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  )
}

function EditorToolBtn({
  children,
  onClick,
  disabled,
  danger = false,
  title,
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        danger
          ? 'border-[#e8c4bc] bg-white text-[#b54a3a] hover:bg-[#fde8e4]'
          : 'border-line bg-white text-ink hover:border-teal hover:bg-sage/60'
      }`}
    >
      {children}
    </button>
  )
}

const TABLE_EDIT_CHANNEL = 'dhara-pdf-table-edit'

function notifyTableEdited(jobId, tableId, edits) {
  try {
    const bc = new BroadcastChannel(TABLE_EDIT_CHANNEL)
    bc.postMessage({ type: 'table-edited', jobId, tableId, edits })
    bc.close()
  } catch {
    /* BroadcastChannel unavailable */
  }
  try {
    localStorage.setItem(
      TABLE_EDIT_CHANNEL,
      JSON.stringify({ jobId, tableId, edits, t: Date.now() }),
    )
  } catch {
    /* ignore */
  }
}

/** Close the editor tab, or fall back to the review page if the browser blocks window.close(). */
function closeEditorWindow(jobId) {
  if (typeof window === 'undefined') return
  const reviewUrl = `/console/review/${encodeURIComponent(jobId || '')}`
  try {
    window.close()
  } catch {
    /* ignore */
  }
  // noopener / user-opened tabs often ignore window.close(); leave the editor.
  window.setTimeout(() => {
    if (!window.closed) {
      window.location.assign(reviewUrl)
    }
  }, 150)
}

/**
 * Full spreadsheet editor: edit cells/headers, resize columns,
 * drag-drop reorder, add/delete/merge groups and columns, merge/unmerge cells.
 * variant="modal" (default) portals a dialog; variant="page" fills the window.
 */
function TableEditModal({
  table,
  jobId,
  rows,
  columns,
  sourceRows,
  originalSnapshot,
  cellMerges,
  mergesExplicit = false,
  variant = 'modal',
  onChangeCell,
  onRenameColumn,
  onChangeGroup,
  onJoinNeighborGroup,
  onSetHeaderPathLevel,
  onInsertColumn,
  onDeleteColumn,
  onMoveColumn,
  onMoveColumnRange,
  onInsertRow,
  onDeleteRow,
  onMoveRowRange,
  onMergeCells,
  onUnmergeCells,
  onAddHeaderGroup,
  onMergeHeaderGroups,
  onDeleteHeaderGroup,
  onDeleteColumns,
  actionFlash = null,
  canUndo = false,
  canRedo = false,
  undoCount = 0,
  redoCount = 0,
  onUndo,
  onRedo,
  onClose,
  onDone,
  doneLabel = 'Done editing',
  footerHint = 'Edits stay in this draft until you click Save on the table card.',
}) {
  const columnCount = (columns || []).length
  const [mounted, setMounted] = useState(false)
  const [colWidths, setColWidths] = useState(() => {
    const n = Math.max((columns || []).length, 1)
    return Array.from({ length: n }, () => Math.max(72, Math.floor(900 / n)))
  })
  const [sel, setSel] = useState(null)
  const [hdrSel, setHdrSel] = useState(null) // { start, end, levelIdx }
  const [dropHint, setDropHint] = useState(null) // { index, mode }
  const [comparePdf, setComparePdf] = useState(false)
  const [showCompareTip, setShowCompareTip] = useState(variant === 'page')
  const [interactionMode, setInteractionMode] = useState('edit') // 'edit' | 'view'
  const canEdit = interactionMode === 'edit'
  const [splitPct, setSplitPct] = useState(42)
  const [pdfZoom, setPdfZoom] = useState(1)
  const [tableZoom, setTableZoom] = useState(1)
  const resizeRef = useRef(null)
  const splitDragRef = useRef(null)
  const workspaceRef = useRef(null)
  const pdfPaneRef = useRef(null)
  const tablePaneRef = useRef(null)
  const dndRef = useRef(null)
  const headerMeta = buildEditorHeaderRows(columns)
  const existingGroups = listExistingHeaderGroups(columns)
  const bodySpans = resolveEditorBodySpans(rows, columns, cellMerges, mergesExplicit)
  const rect = selectionRect(sel)

  useEffect(() => {
    setColWidths((prev) => {
      const n = Math.max((columns || []).length, 1)
      if (prev.length === n) return prev
      if (prev.length < n) {
        return [...prev, ...Array.from({ length: n - prev.length }, () => 100)]
      }
      return prev.slice(0, n)
    })
  }, [columns?.length])

  useEffect(() => {
    setMounted(true)
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
      const mod = e.metaKey || e.ctrlKey
      if (!mod) return
      if (!canEdit) return
      const key = e.key.toLowerCase()
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault()
        if (canUndo) onUndo?.()
        return
      }
      if (key === 'y' || (key === 'z' && e.shiftKey)) {
        e.preventDefault()
        if (canRedo) onRedo?.()
      }
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    if (variant === 'modal') document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      if (variant === 'modal') document.body.style.overflow = prev
    }
  }, [onClose, canUndo, canRedo, onUndo, onRedo, variant, canEdit])

  useEffect(() => {
    if (!showCompareTip) return undefined
    const t = window.setTimeout(() => setShowCompareTip(false), 8000)
    return () => window.clearTimeout(t)
  }, [showCompareTip])

  useEffect(() => {
    const onMove = (e) => {
      const d = resizeRef.current
      if (!d) return
      const dx = e.clientX - d.startX
      const next = Math.max(56, d.startW + dx)
      setColWidths((ws) => ws.map((w, i) => (i === d.idx ? next : w)))
    }
    const onUp = () => { resizeRef.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      const drag = splitDragRef.current
      if (!drag) return
      const el = workspaceRef.current
      if (!el) return
      const box = el.getBoundingClientRect()
      if (drag.axis === 'x') {
        const pct = ((e.clientX - box.left) / Math.max(1, box.width)) * 100
        setSplitPct(Math.min(75, Math.max(22, pct)))
      } else {
        const pct = ((e.clientY - box.top) / Math.max(1, box.height)) * 100
        setSplitPct(Math.min(70, Math.max(20, pct)))
      }
    }
    const onUp = () => {
      if (!splitDragRef.current) return
      splitDragRef.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  useEffect(() => {
    const cleanPdf = bindPaneWheelZoom(pdfPaneRef.current, setPdfZoom)
    const cleanTable = bindPaneWheelZoom(tablePaneRef.current, setTableZoom)
    return () => {
      cleanPdf()
      cleanTable()
    }
  }, [comparePdf, mounted])

  if (!mounted) return null

  const startResize = (idx, e) => {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = { idx, startX: e.clientX, startW: colWidths[idx] || 100 }
  }

  const selectCell = (r, c, extend) => {
    setHdrSel(null)
    setSel((prev) => {
      if (extend && prev) return { ...prev, r1: r, c1: c }
      return { r0: r, c0: c, r1: r, c1: c }
    })
  }

  const selectHeaderRange = (start, end, levelIdx, extend) => {
    setSel(null)
    setHdrSel((prev) => {
      if (extend && prev) {
        return {
          start: Math.min(prev.start, start, end),
          end: Math.max(prev.end, start, end),
          levelIdx: prev.levelIdx,
        }
      }
      return { start, end, levelIdx }
    })
  }

  const canMerge = Boolean(rect && (rect.r1 > rect.r0 || rect.c1 > rect.c0))
  const spanAtSelection = rect ? findBodySpanOrigin(bodySpans, rect.r0, rect.c0) : null
  const canUnmerge = Boolean(
    rect
    && (
      findMergeCovering(cellMerges, rect.r0, rect.c0)
      || (
        spanAtSelection
        && ((spanAtSelection.span.rowSpan || 1) > 1 || (spanAtSelection.span.colSpan || 1) > 1)
      )
    )
  )
  const selectedColStart = hdrSel
    ? hdrSel.start
    : (rect ? Math.min(rect.c0, rect.c1) : null)
  const selectedColEnd = hdrSel
    ? hdrSel.end
    : (rect ? Math.max(rect.c0, rect.c1) : null)
  const hasColSelection = selectedColStart != null && selectedColEnd != null
  const canMergeGroups = hasColSelection && selectedColEnd > selectedColStart
  const canDeleteGroup = Boolean(hdrSel && hdrSel.levelIdx < headerMeta.depth - 1)
  const canDeleteColumns = hasColSelection && columnCount > 1
    && (selectedColEnd - selectedColStart + 1) < columnCount

  const clearDnd = () => {
    dndRef.current = null
    setDropHint(null)
  }

  const beginDrag = (kind, start, end, e) => {
    if (!canEdit) {
      e.preventDefault()
      return
    }
    dndRef.current = { kind, start, end }
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', `${kind}:${start}-${end}`)
    try {
      e.dataTransfer.setDragImage(e.currentTarget.closest('th') || e.currentTarget, 12, 12)
    } catch {
      /* ignore */
    }
  }

  const edgeForEvent = (e, el) => {
    const box = el.getBoundingClientRect()
    const x = e.clientX - box.left
    if (x < box.width * 0.28) return 'before'
    if (x > box.width * 0.72) return 'after'
    return 'into'
  }

  const onHeaderDragOver = (e, start, end, isGroup) => {
    e.preventDefault()
    if (dndRef.current?.kind === 'row') return
    e.dataTransfer.dropEffect = 'move'
    const src = dndRef.current
    if (!src || (src.kind !== 'column' && src.kind !== 'group')) return
    const mode = isGroup ? edgeForEvent(e, e.currentTarget) : (
      e.clientX - e.currentTarget.getBoundingClientRect().left
        < e.currentTarget.getBoundingClientRect().width / 2 ? 'before' : 'after'
    )
    if (src.start === start && src.end === end && mode === 'into') {
      setDropHint(null)
      return
    }
    setDropHint({ type: 'col', index: start, end, mode, isGroup: Boolean(isGroup) })
  }

  const onRowDragOver = (e, r) => {
    e.preventDefault()
    if (dndRef.current?.kind !== 'row') return
    e.dataTransfer.dropEffect = 'move'
    const box = e.currentTarget.getBoundingClientRect()
    const mode = e.clientY - box.top < box.height / 2 ? 'before' : 'after'
    const src = dndRef.current
    if (src && r >= src.start && r <= src.end) {
      setDropHint(null)
      return
    }
    setDropHint({ type: 'row', index: r, mode })
  }

  const applyDrop = (targetStart, targetEnd, isGroup) => {
    const src = dndRef.current
    const hint = dropHint
    clearDnd()
    if (!src || src.kind === 'row') return
    const mode = hint?.mode || 'after'
    const count = src.end - src.start + 1

    if (mode === 'into' && isGroup) {
      const sample = columns[targetStart]
      const parents = columnParentPath(sample)
      const label = parents.slice(-1)[0] || columns[targetStart]?.header_group || 'Group'
      // Already inside this span — just adopt the group label.
      if (src.start >= targetStart && src.end <= targetEnd) {
        onMergeHeaderGroups?.(src.start, src.end, label)
        return
      }
      let insertAt
      if (src.start > targetEnd) insertAt = targetStart
      else insertAt = targetEnd + 1
      let newStart = src.start
      if (insertAt <= src.start) newStart = insertAt
      else if (insertAt > src.end) newStart = insertAt - count
      else return
      onMoveColumnRange?.(src.start, count, insertAt)
      onMergeHeaderGroups?.(newStart, newStart + count - 1, label)
      return
    }

    const insertAt = mode === 'before' ? targetStart : targetEnd + 1
    onMoveColumnRange?.(src.start, count, insertAt)
  }

  const applyRowDrop = (targetRow) => {
    const src = dndRef.current
    const hint = dropHint
    clearDnd()
    if (!src || src.kind !== 'row') return
    const mode = hint?.type === 'row' ? hint.mode : 'after'
    const count = src.end - src.start + 1
    const insertAt = mode === 'before' ? targetRow : targetRow + 1
    onMoveRowRange?.(src.start, count, insertAt)
  }

  const tableWidth = colWidths.reduce((a, b) => a + b, 72)

  const dropClass = (start) => {
    if (!dropHint || dropHint.type !== 'col' || dropHint.index !== start) return ''
    if (dropHint.mode === 'before') return 'shadow-[inset_3px_0_0_0_#F5C518]'
    if (dropHint.mode === 'after') return 'shadow-[inset_-3px_0_0_0_#F5C518]'
    if (dropHint.mode === 'into') return 'ring-2 ring-inset ring-yellow bg-teal-deep/40'
    return ''
  }

  const rowDropClass = (r) => {
    if (!dropHint || dropHint.type !== 'row' || dropHint.index !== r) return ''
    if (dropHint.mode === 'before') return 'shadow-[inset_0_3px_0_0_#F5C518]'
    if (dropHint.mode === 'after') return 'shadow-[inset_0_-3px_0_0_#F5C518]'
    return ''
  }

  const hdrSelected = (start, end) => (
    hdrSel
    && start >= hdrSel.start
    && end <= hdrSel.end
  )

  const colFlashClass = (c) => {
    if (!actionFlash || actionFlash.axis !== 'cols') return ''
    if (flashCovers(actionFlash.to, c)) return 'bg-[#d4edda]/90 ring-2 ring-inset ring-[#2f9e44]'
    if (flashCovers(actionFlash.from, c)) return 'bg-[#f8d7da]/90 ring-2 ring-inset ring-[#c92a2a]'
    return ''
  }

  const rowFlashClass = (r) => {
    if (!actionFlash || actionFlash.axis !== 'rows') return ''
    if (flashCovers(actionFlash.to, r)) return 'bg-[#d4edda]/70 ring-2 ring-inset ring-[#2f9e44]'
    if (flashCovers(actionFlash.from, r)) return 'bg-[#f8d7da]/70 ring-2 ring-inset ring-[#c92a2a]'
    return ''
  }

  const cellFlashClass = (r, c) => {
    if (!actionFlash || actionFlash.axis !== 'cells') return ''
    const inFrom = actionFlash.from
      && r >= actionFlash.from.r0 && r <= actionFlash.from.r1
      && c >= actionFlash.from.c0 && c <= actionFlash.from.c1
    const inTo = actionFlash.to
      && r >= actionFlash.to.r0 && r <= actionFlash.to.r1
      && c >= actionFlash.to.c0 && c <= actionFlash.to.c1
    if (inTo) return 'bg-[#d4edda]/80 ring-2 ring-inset ring-[#2f9e44]'
    if (inFrom) return 'bg-[#f8d7da]/80 ring-2 ring-inset ring-[#c92a2a]'
    return ''
  }

  const flashLegend = actionFlash ? (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-soft">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-[#f8d7da] ring-1 ring-[#c92a2a]" aria-hidden />
        Previous place
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-[#d4edda] ring-1 ring-[#2f9e44]" aria-hidden />
        New place
      </span>
    </div>
  ) : null

  // Selection chrome (blue) — kept distinct from green/red action-flash highlights.
  const cellSelectedClass = 'border-[#2b6cb0] bg-[#d6eaf8]'
  const hdrSelectedClass = 'ring-2 ring-inset ring-[#2b6cb0] bg-[#d6eaf8]'

  const selectionLabel = (() => {
    if (hdrSel) {
      const n = hdrSel.end - hdrSel.start + 1
      const kind = hdrSel.levelIdx < headerMeta.depth - 1 ? 'header group' : 'column'
      return n === 1
        ? `Selected 1 ${kind}`
        : `Selected ${n} columns (headers)`
    }
    if (rect) {
      const rowsN = Math.abs(rect.r1 - rect.r0) + 1
      const colsN = Math.abs(rect.c1 - rect.c0) + 1
      if (rowsN === 1 && colsN === 1) return `Selected cell · row ${rect.r0 + 1}, column ${rect.c0 + 1}`
      return `Selected ${rowsN}×${colsN} cells · Shift+click to extend`
    }
    return 'Tip: click a header to select columns · Shift+click cells to select a range'
  })()

  const shell = (
      <div
        className={`flex flex-col overflow-hidden bg-surface ${
          variant === 'page'
            ? 'h-full min-h-0 w-full'
            : 'h-[min(900px,96vh)] w-[min(1360px,calc(100vw-1.5rem))] rounded-[16px] shadow-dhara'
        }`}
        onClick={variant === 'modal' ? (e) => e.stopPropagation() : undefined}
      >
        {/* Compact title bar */}
        <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-line bg-cream px-3 py-2 sm:px-4">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="min-w-0 flex-1">
              <div id="table-edit-title" className={`truncate text-[15px] font-bold tracking-tight sm:text-base ${displayTitle(table) ? 'text-ink' : 'italic text-ink-soft'}`}>
                {displayTitle(table) || 'No title — review'}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-soft">
                <span>Page {table.page}</span>
                <span>·</span>
                <span>{rows.length}×{columnCount}</span>
                {flashLegend}
              </div>
            </div>
            <div
              className="inline-flex flex-shrink-0 rounded-md border border-line bg-white p-0.5"
              role="group"
              aria-label="Interaction mode"
            >
              <button
                type="button"
                onClick={() => setInteractionMode('view')}
                className={`inline-flex items-center gap-1 rounded px-2.5 py-1 text-[12px] font-semibold transition-colors ${
                  interactionMode === 'view'
                    ? 'bg-teal text-cream'
                    : 'text-ink-soft hover:bg-sage/60 hover:text-teal'
                }`}
                title="View only — editing tools disabled"
                aria-pressed={interactionMode === 'view'}
              >
                <Eye className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                View
              </button>
              <button
                type="button"
                onClick={() => setInteractionMode('edit')}
                className={`inline-flex items-center gap-1 rounded px-2.5 py-1 text-[12px] font-semibold transition-colors ${
                  interactionMode === 'edit'
                    ? 'bg-teal text-cream'
                    : 'text-ink-soft hover:bg-sage/60 hover:text-teal'
                }`}
                title="Edit table structure and cells"
                aria-pressed={interactionMode === 'edit'}
              >
                <Pencil className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                Edit
              </button>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="relative">
          <button
            type="button"
                onClick={() => {
                  setComparePdf((v) => !v)
                  setShowCompareTip(false)
                }}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-semibold transition-all ${
                  showCompareTip
                    ? 'relative z-10 border-teal bg-sage text-teal ring-2 ring-teal ring-offset-2 ring-offset-cream animate-pulse'
                    : comparePdf
                      ? 'border-teal bg-sage text-teal'
                      : 'border-line bg-white text-ink-soft hover:border-teal hover:text-teal'
                }`}
                title="Show PDF snapshot beside the editable table"
                aria-describedby={showCompareTip ? 'compare-pdf-tip' : undefined}
              >
                <Columns2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                Compare PDF
              </button>
              {showCompareTip ? (
                <div
                  id="compare-pdf-tip"
                  role="status"
                  className="absolute right-0 top-[calc(100%+0.5rem)] z-20 w-[min(280px,calc(100vw-2rem))] rounded-lg border border-teal/30 bg-white px-3 py-2.5 text-left shadow-dhara"
                >
                  <p className="text-[12px] leading-snug text-ink">
                    Want to check extraction against the source? Turn on{' '}
                    <span className="font-semibold text-teal">Compare PDF</span> anytime.
                  </p>
                  <button
                    type="button"
                    className="mt-1.5 text-[11px] font-semibold text-teal hover:underline"
                    onClick={() => setShowCompareTip(false)}
                  >
                    Got it
                  </button>
                </div>
              ) : null}
            </div>
            <button
              type="button"
              className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md text-ink-soft hover:bg-white hover:text-ink"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
          </div>
        </div>

        {/* Excel-style ribbon */}
        <div className={`flex flex-shrink-0 flex-wrap items-center gap-1 border-b border-line bg-[#F7F2E8] px-2 py-1.5 sm:px-3 ${!canEdit ? 'opacity-55' : ''}`}>
          <EditorToolBtn disabled={!canEdit || !canUndo} title={!canEdit ? 'Switch to Edit to undo' : canUndo ? `Undo (${undoCount})` : 'Nothing to undo'} onClick={() => onUndo?.()}>
            <Undo2 className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Undo
          </EditorToolBtn>
          <EditorToolBtn disabled={!canEdit || !canRedo} title={!canEdit ? 'Switch to Edit to redo' : canRedo ? `Redo (${redoCount})` : 'Nothing to redo'} onClick={() => onRedo?.()}>
            <Redo2 className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Redo
          </EditorToolBtn>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <EditorToolBtn disabled={!canEdit} onClick={() => onInsertColumn(columnCount)} title={!canEdit ? 'Switch to Edit to add columns' : 'Add column'}>
            <Plus className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Col
          </EditorToolBtn>
          <EditorToolBtn disabled={!canEdit} onClick={() => onInsertRow(rows.length)} title={!canEdit ? 'Switch to Edit to add rows' : 'Add row'}>
            <Plus className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Row
          </EditorToolBtn>
          <EditorToolBtn
            danger
            disabled={!canEdit || !canDeleteColumns}
            title={!canEdit ? 'Switch to Edit to delete columns' : canDeleteColumns ? 'Delete selected columns' : 'Select column headers first'}
            onClick={() => {
              if (!canEdit || !hasColSelection) return
              onDeleteColumns?.(selectedColStart, selectedColEnd)
              setHdrSel(null)
              setSel(null)
            }}
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
            Del col
          </EditorToolBtn>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <EditorToolBtn
            disabled={!canEdit}
            title={!canEdit ? 'Switch to Edit to manage groups' : hasColSelection ? 'Wrap selection in a group' : 'Add grouped column'}
            onClick={() => {
              if (!canEdit) return
              if (hasColSelection) onAddHeaderGroup?.(selectedColStart, selectedColEnd, 'New group')
              else onAddHeaderGroup?.(columnCount, columnCount, 'New group')
            }}
          >
            <Plus className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Group
          </EditorToolBtn>
          <EditorToolBtn
            disabled={!canEdit || !canMergeGroups}
            title={!canEdit ? 'Switch to Edit to merge groups' : canMergeGroups ? 'Merge selected into one group' : 'Select 2+ columns'}
            onClick={() => {
              if (!canEdit || !hasColSelection) return
              const sample = columns[selectedColStart]
              const label = columnParentPath(sample).slice(-1)[0] || existingGroups[0] || 'Group'
              onMergeHeaderGroups?.(selectedColStart, selectedColEnd, label)
            }}
          >
            <Combine className="h-3.5 w-3.5 text-teal" strokeWidth={2} />
            Merge grp
          </EditorToolBtn>
          <EditorToolBtn
            danger
            disabled={!canEdit || !canDeleteGroup}
            title={!canEdit ? 'Switch to Edit to ungroup' : canDeleteGroup ? 'Remove group label' : 'Select a group header'}
            onClick={() => {
              if (!canEdit || !hdrSel) return
              onDeleteHeaderGroup?.(hdrSel.start, hdrSel.end - hdrSel.start + 1, hdrSel.levelIdx)
              setHdrSel(null)
            }}
          >
            Ungroup
          </EditorToolBtn>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <EditorToolBtn
            disabled={!canEdit || !canMerge}
            title={!canEdit ? 'Switch to Edit to merge cells' : canMerge ? 'Merge selected cells' : 'Shift+click cells first'}
            onClick={() => {
              if (!canEdit || !rect) return
              onMergeCells(rect)
              setSel(null)
            }}
          >
            <Combine className="h-3.5 w-3.5 text-teal" strokeWidth={2} />
            Merge
          </EditorToolBtn>
          <EditorToolBtn
            disabled={!canEdit || !canUnmerge}
            title={!canEdit ? 'Switch to Edit to unmerge' : canUnmerge ? 'Unmerge cell' : 'Select a merged cell'}
            onClick={() => {
              if (!canEdit || !rect) return
              const origin = spanAtSelection || findBodySpanOrigin(bodySpans, rect.r0, rect.c0)
              onUnmergeCells(origin?.r ?? rect.r0, origin?.c ?? rect.c0)
              setSel(null)
            }}
          >
            Unmerge
          </EditorToolBtn>
          {hasColSelection && selectedColStart === selectedColEnd ? (
            <>
              <span className="mx-1 h-5 w-px bg-line" aria-hidden />
              <select
                disabled={!canEdit}
                className="max-w-[160px] rounded-md border border-line bg-white px-2 py-1 text-[11px] font-semibold text-ink outline-none focus:border-teal disabled:cursor-not-allowed disabled:opacity-40"
                value={columnParentPath(columns[selectedColStart]).slice(-1)[0] || ''}
                title={!canEdit ? 'Switch to Edit to assign groups' : 'Assign selected column to a group'}
                onChange={(e) => onChangeGroup(selectedColStart, e.target.value)}
              >
                <option value="">No group</option>
                {existingGroups.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </>
          ) : null}
          <span className="ml-auto hidden max-w-[280px] truncate text-[11px] text-ink-soft sm:inline" title={selectionLabel}>
            {!canEdit ? 'View mode · Compare and zoom still work' : selectionLabel}
          </span>
        </div>

        {/* Main workspace: optional PDF | resizable split | sheet */}
        <div
          ref={workspaceRef}
          className={`flex min-h-0 flex-1 ${comparePdf ? 'flex-col lg:flex-row' : 'flex-col'}`}
        >
          {comparePdf ? (
            <>
              <div
                className="flex min-h-0 min-w-0 flex-col border-line bg-[#FFFCF6] max-lg:border-b"
                style={{
                  flexBasis: `${splitPct}%`,
                  flexGrow: 0,
                  flexShrink: 0,
                }}
              >
                <div className="flex flex-shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-1.5">
                  <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">PDF source</div>
                  <div className="flex items-center gap-2">
                    <EditorZoomControls zoom={pdfZoom} onChange={setPdfZoom} label="PDF zoom" />
                    <span className="text-[11px] text-ink-soft">Page {table.page}</span>
                  </div>
                </div>
                <div ref={pdfPaneRef} className="min-h-0 flex-1 overflow-auto p-2">
                  <PdfTableSnapshot
                    jobId={jobId}
                    tableId={table.table_id}
                    maxHeightClass="max-h-none"
                    zoom={pdfZoom}
                  />
                </div>
              </div>

              {/* Drag handle: horizontal on desktop, vertical on stacked mobile */}
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize comparison panes"
                title="Drag to resize"
                className="group relative z-[5] hidden h-full w-1.5 flex-shrink-0 cursor-col-resize bg-line hover:bg-teal lg:block"
                onMouseDown={(e) => {
                  e.preventDefault()
                  splitDragRef.current = { axis: 'x' }
                  document.body.style.cursor = 'col-resize'
                  document.body.style.userSelect = 'none'
                }}
              >
                <div className="pointer-events-none absolute inset-y-0 -left-1 -right-1" />
                <div className="pointer-events-none absolute left-1/2 top-1/2 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-teal/40 opacity-0 group-hover:opacity-100" />
              </div>
              <div
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize comparison panes"
                title="Drag to resize"
                className="group relative z-[5] h-1.5 w-full flex-shrink-0 cursor-row-resize bg-line hover:bg-teal lg:hidden"
                onMouseDown={(e) => {
                  e.preventDefault()
                  splitDragRef.current = { axis: 'y' }
                  document.body.style.cursor = 'row-resize'
                  document.body.style.userSelect = 'none'
                }}
              />
            </>
          ) : null}

          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex flex-shrink-0 items-center justify-between gap-2 border-b border-line bg-white px-3 py-1.5">
              <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">
                {comparePdf ? 'Extracted table (editable)' : 'Worksheet'}
              </div>
              <div className="flex items-center gap-2">
                <EditorZoomControls zoom={tableZoom} onChange={setTableZoom} label="Table zoom" />
                <button
                  type="button"
                  disabled={!canEdit}
                  className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-teal hover:bg-sage disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() => onInsertRow(rows.length)}
                >
                  + Row
                </button>
                <button
                  type="button"
                  disabled={!canEdit}
                  className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-teal hover:bg-sage disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() => onInsertColumn(columnCount)}
                >
                  + Col
                </button>
              </div>
            </div>
            <div ref={tablePaneRef} className="min-h-0 flex-1 overflow-auto bg-white" onDragEnd={clearDnd}>
              <div style={{ zoom: tableZoom }}>
              <table className="border-collapse text-[12px]" style={{ tableLayout: 'fixed', width: tableWidth }}>
              <colgroup>
                  <col style={{ width: 40 }} />
                {colWidths.map((w, i) => (
                    <col key={i} style={{ width: w }} />
                ))}
                  <col style={{ width: 32 }} />
              </colgroup>
                <thead>
                  {headerMeta.rows.map((segs, hr) => (
                    <tr key={`hdr-${hr}`} className="bg-[#E8F0EF]">
                      {hr === 0 ? (
                        <th
                          rowSpan={headerMeta.depth}
                          className="sticky left-0 z-[3] border border-[#c5d4d2] bg-[#D5E4E2] px-0.5 py-0.5 text-center text-[10px] font-semibold text-ink-soft"
                        >
                          #
                        </th>
                      ) : null}
                      {segs.map((seg) => {
                        const isLeaf = seg.isLeaf
                        const segEnd = seg.start + seg.colSpan - 1
                        const isGroup = !isLeaf
                        return (
                          <th
                            key={seg.key}
                            colSpan={seg.colSpan > 1 ? seg.colSpan : undefined}
                            rowSpan={seg.rowSpan > 1 ? seg.rowSpan : undefined}
                            onDragOver={(e) => onHeaderDragOver(e, seg.start, segEnd, isGroup || seg.colSpan > 1)}
                            onDragLeave={() => setDropHint((h) => (h && h.index === seg.start ? null : h))}
                            onDrop={(e) => {
                              e.preventDefault()
                              applyDrop(seg.start, segEnd, isGroup || seg.colSpan > 1)
                            }}
                            onClick={(e) => {
                              if (e.target.closest('textarea,select,button,input')) return
                              selectHeaderRange(seg.start, segEnd, hr, e.shiftKey)
                            }}
                            className={`group relative border border-[#c5d4d2] px-0.5 py-0.5 align-top font-medium text-ink ${seg.colSpan > 1 || !isLeaf ? 'text-center' : 'text-left'} ${dropClass(seg.start)} ${hdrSelected(seg.start, segEnd) ? hdrSelectedClass : 'bg-[#E8F0EF]'} ${(() => {
                              let red = false
                              let green = false
                              for (let c = seg.start; c <= segEnd; c += 1) {
                                if (actionFlash?.axis === 'cols' && flashCovers(actionFlash.to, c)) green = true
                                if (actionFlash?.axis === 'cols' && flashCovers(actionFlash.from, c)) red = true
                              }
                              if (green) return 'ring-2 ring-inset ring-[#2f9e44] bg-[#d4edda]'
                              if (red) return 'ring-2 ring-inset ring-[#c92a2a] bg-[#f8d7da]'
                              return ''
                            })()}`}
                          >
                            {isLeaf ? (
                              <div className="flex min-w-0 items-start gap-0.5">
                                <button
                                  type="button"
                                  draggable={canEdit}
                                  disabled={!canEdit}
                                  onDragStart={(e) => beginDrag('column', seg.start, segEnd, e)}
                                  onDragEnd={clearDnd}
                                  className="mt-0.5 flex-shrink-0 cursor-grab rounded p-0.5 text-ink-soft opacity-40 hover:bg-white/80 hover:opacity-100 active:cursor-grabbing group-hover:opacity-100 disabled:cursor-default disabled:opacity-20"
                                  title={canEdit ? 'Drag to reorder' : 'Switch to Edit to reorder'}
                                  aria-label="Drag column"
                                >
                                  <GripVertical className="h-3 w-3" strokeWidth={2} />
                                </button>
                                <AutoGrowTextarea
                                  readOnly={!canEdit}
                                  className="w-full min-w-0 border-0 bg-transparent px-0.5 py-0.5 text-[11px] font-semibold leading-snug text-ink outline-none [overflow-wrap:anywhere] break-words whitespace-pre-wrap focus:bg-white focus:ring-1 focus:ring-teal"
                                  value={columns[seg.start]?.name || ''}
                                  placeholder="Column"
                                  onChange={(next) => onRenameColumn(seg.start, next)}
                                />
                                <button
                                  type="button"
                                  className="mt-0.5 flex-shrink-0 rounded p-0.5 text-[#c45c4a] opacity-0 hover:bg-[#fde8e4] group-hover:opacity-100 disabled:opacity-0"
                                  disabled={!canEdit || columnCount <= 1}
                                  onClick={() => onDeleteColumn(seg.start)}
                                  title={canEdit ? 'Delete column' : 'Switch to Edit to delete'}
                                  aria-label="Delete column"
                                >
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              </div>
                            ) : (
                              <div className="flex min-w-0 items-start justify-center gap-0.5">
                                {!seg.empty ? (
                                  <button
                                    type="button"
                                    draggable={canEdit}
                                    disabled={!canEdit}
                                    onDragStart={(e) => beginDrag('group', seg.start, segEnd, e)}
                                    onDragEnd={clearDnd}
                                    className="mt-0.5 flex-shrink-0 cursor-grab rounded p-0.5 text-ink-soft opacity-40 hover:opacity-100 active:cursor-grabbing group-hover:opacity-100 disabled:cursor-default disabled:opacity-20"
                                    title={canEdit ? 'Drag group' : 'Switch to Edit to reorder'}
                                    aria-label="Drag group"
                                  >
                                    <GripVertical className="h-3 w-3" strokeWidth={2} />
                                  </button>
                                ) : null}
                                <AutoGrowTextarea
                                  readOnly={!canEdit}
                                  className="w-full min-w-0 border-0 bg-transparent px-0.5 py-0.5 text-center text-[10px] font-bold uppercase leading-snug tracking-wide text-ink outline-none [overflow-wrap:anywhere] break-words whitespace-pre-wrap placeholder:font-medium placeholder:normal-case placeholder:tracking-normal placeholder:text-ink-soft focus:bg-white focus:ring-1 focus:ring-teal"
                                  value={seg.label || ''}
                                  placeholder={seg.empty ? 'Group…' : 'Group'}
                                  title={seg.empty ? 'Type a group name' : `Group spanning ${seg.colSpan} cols`}
                                  onChange={(next) => onSetHeaderPathLevel(seg.start, seg.colSpan, hr, next)}
                                />
                              </div>
                            )}
                            {isLeaf && canEdit ? (
                              <span
                                role="separator"
                                aria-orientation="vertical"
                                aria-label="Resize column"
                                onMouseDown={(e) => startResize(seg.start, e)}
                                className="absolute right-0 top-0 z-[4] h-full w-1 cursor-col-resize hover:bg-teal/50"
                              />
                            ) : null}
                          </th>
                        )
                      })}
                      {hr === 0 ? (
                        <th
                          rowSpan={headerMeta.depth}
                          className="border border-[#c5d4d2] bg-[#D5E4E2] px-0.5 py-0.5"
                        >
                          {' '}
                        </th>
                      ) : null}
                    </tr>
                  ))}
                </thead>
              <tbody>
                  {(rows || []).map((row, r) => (
                  <tr
                    key={r}
                      className={`group/row ${r % 2 === 0 ? 'bg-white' : 'bg-[#FAFBFA]'} hover:bg-[#F0F6F5] ${rowDropClass(r)} ${rowFlashClass(r)}`}
                      onDragOver={(e) => onRowDragOver(e, r)}
                      onDrop={(e) => {
                        e.preventDefault()
                        applyRowDrop(r)
                      }}
                    >
                      <td className="sticky left-0 z-[1] border border-[#d8e0de] bg-inherit px-0 py-0 text-center text-[10px] tabular-nums text-ink-soft">
                        <div className="flex items-center justify-center gap-0">
                          <button
                            type="button"
                            draggable={canEdit}
                            disabled={!canEdit}
                            onDragStart={(e) => beginDrag('row', r, r, e)}
                            onDragEnd={clearDnd}
                            className="cursor-grab rounded p-0.5 text-ink-soft opacity-30 hover:opacity-100 active:cursor-grabbing group-hover/row:opacity-70 disabled:cursor-default disabled:opacity-15"
                            title={canEdit ? 'Drag row' : 'Switch to Edit to reorder'}
                            aria-label={`Drag row ${r + 1}`}
                          >
                            <GripVertical className="h-3 w-3" strokeWidth={2} />
                          </button>
                          <span className="pr-0.5">{r + 1}</span>
                        </div>
                      </td>
                    {Array.from({ length: columnCount }, (_, c) => {
                        const span = bodySpans[r]?.[c]
                      if (span == null) return null
                        const selected = Boolean(
                          rect
                          && r >= rect.r0 && r <= rect.r1
                          && c >= rect.c0 && c <= rect.c1
                        )
                      const merged = span.rowSpan > 1 || span.colSpan > 1
                      return (
                        <td
                          key={c}
                          rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                          colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                            onClick={(e) => selectCell(r, c, e.shiftKey)}
                            className={`max-w-0 cursor-cell border px-0 py-0 align-top break-words [overflow-wrap:anywhere] ${
                              selected ? cellSelectedClass : 'border-[#d8e0de]'
                            } ${merged ? '' : ''} ${colFlashClass(c)} ${cellFlashClass(r, c)}`}
                        >
                          <ExtractedDataCell
                            value={row[c] ?? null}
                              sourceValue={sourceRows?.[r]?.[c]}
                            col={columns[c]}
                              locked={!canEdit}
                            fitWidth
                            onChange={(next) => onChangeCell(r, c, next)}
                          />
                        </td>
                      )
                    })}
                      <td className="border border-[#d8e0de] px-0 py-0 text-center">
                        <button
                          type="button"
                          className="rounded p-0.5 text-[#c45c4a] opacity-40 hover:bg-[#fde8e4] hover:opacity-100 disabled:opacity-20 group-hover/row:opacity-70"
                          disabled={!canEdit || (rows || []).length <= 1}
                          onClick={() => onDeleteRow(r)}
                          title={canEdit ? 'Delete row' : 'Switch to Edit to delete'}
                          aria-label={`Delete row ${r + 1}`}
                        >
                          <Trash2 className="h-3 w-3" strokeWidth={2} />
                        </button>
                      </td>
                  </tr>
                ))}
              </tbody>
            </table>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-shrink-0 items-center justify-between gap-2 border-t border-line bg-cream/70 px-3 py-2 sm:px-4">
          <div className="text-[11px] text-ink-soft sm:text-[12px]">{footerHint}</div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {variant === 'page' ? 'Close' : 'Cancel'}
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={doneLabel?.includes('Saving')}
              onClick={async () => {
                await onDone?.()
                if (variant === 'modal') onClose?.()
              }}
            >
              {doneLabel}
          </Button>
        </div>
      </div>
      </div>
  )

  if (variant === 'page') {
    return (
      <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-surface" role="main" aria-labelledby="table-edit-title">
        {shell}
      </div>
    )
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center overflow-hidden bg-[rgba(16,64,63,0.52)] p-3 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="table-edit-title"
      onClick={onClose}
    >
      {shell}
    </div>,
    document.body,
  )
}

/** Table title on the collapsed preview card (edit in the expanded detail). */
function TableTitleDisplay({ table, className = '' }) {
  const title = displayTitle(table)
  if (title) {
    return (
      <div className={`min-w-0 truncate text-[14px] font-semibold leading-snug text-ink ${className}`}>
        {title}
      </div>
    )
  }
  return (
    <div className={`min-w-0 truncate text-[14px] font-semibold italic leading-snug text-ink-soft ${className}`}>
      No title — review
    </div>
  )
}

// One table's classification/column fields, editable where flagged for
// human review -- plus extracted-data cells for non-numeric columns
// (garbled/corrupted values stay highlighted). Numeric columns
// (integer / decimal / percentage) stay read-only. Column structure
// (rename / reorder / add / delete) is editable with PDF + original snapshots.
function TableDetail({ table, jobId, onSave, onTitleLive, onTitleCommit, editorOnly = false }) {
  const classificationNeedsReview = Object.values(table.classification || {}).some((f) => f?.human_review_needed)
  const columnsNeedReview = (table.columns || []).some((c) => c.human_review_needed)
  const showSemanticSections = table.semantic_status === 'classified'

  const [originalSnapshot] = useState(() => ({
    columns: cloneColumns(table.columns || []),
    rows: padRowsToColumns(table.rows || [], (table.columns || []).length),
  }))

  const [draft, setDraft] = useState(() => ({
    title: titleForEdit(table),
    classification: Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [k, f?.value ?? ''])
    ),
    columns: columnDraftFromTable(table.columns || []),
    rows: padRowsToColumns(table.rows || [], (table.columns || []).length),
    cellMerges: Array.isArray(table.cell_merges) ? table.cell_merges.map((m) => ({ ...m })) : [],
    mergesExplicit: Boolean(table.cell_merges_explicit)
      || (Array.isArray(table.cell_merges) && table.cell_merges.length > 0),
  }))
  const [saved, setSaved] = useState(false)
  const [classificationOpen, setClassificationOpen] = useState(classificationNeedsReview)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [savingEditor, setSavingEditor] = useState(false)
  // Full undo/redo history of editor structure changes (+ last-action red/green flash)
  const [actionFlash, setActionFlash] = useState(null)
  const [undoStack, setUndoStack] = useState([]) // [{ structure, flash }, ...] oldest → newest
  const [redoStack, setRedoStack] = useState([])
  const draftRef = useRef(draft)
  const actionFlashRef = useRef(null)
  const undoStackRef = useRef([])
  const redoStackRef = useRef([])
  draftRef.current = draft
  actionFlashRef.current = actionFlash
  undoStackRef.current = undoStack
  redoStackRef.current = redoStack

  const columnCount = (draft.columns || []).length
  const displayColumns = draft.columns

  useEffect(() => {
    setDraft((prev) => ({ ...prev, title: titleForEdit(table) }))
  }, [table.title])

  // Keep local draft in sync when the table is updated from the full-page editor tab.
  useEffect(() => {
    if (editorOnly) return undefined
    setDraft((prev) => ({
      ...prev,
      columns: columnDraftFromTable(table.columns || []),
      rows: padRowsToColumns(table.rows || [], (table.columns || []).length),
      cellMerges: Array.isArray(table.cell_merges) ? table.cell_merges.map((m) => ({ ...m })) : [],
      mergesExplicit: Boolean(table.cell_merges_explicit)
        || (Array.isArray(table.cell_merges) && table.cell_merges.length > 0),
    }))
  }, [editorOnly, table.table_id, table.columns, table.rows, table.cell_merges, table.cell_merges_explicit])

  const openFullPageEditor = () => {
    const url = `/console/review/${encodeURIComponent(jobId)}/edit/${encodeURIComponent(table.table_id)}`
    // Keep opener so the tab can close itself after Save & close.
    window.open(url, '_blank')
  }

  const markDirty = () => setSaved(false)

  const HISTORY_LIMIT = 100

  const applyEditorChange = (updater, flash = null) => {
    markDirty()
    const prev = draftRef.current
    const next = typeof updater === 'function' ? updater(prev) : updater
    if (next === prev) return
    const nextUndo = [
      ...undoStackRef.current,
      { structure: cloneEditorStructure(prev), flash },
    ].slice(-HISTORY_LIMIT)
    undoStackRef.current = nextUndo
    redoStackRef.current = []
    setUndoStack(nextUndo)
    setRedoStack([])
    draftRef.current = next
    setDraft(next)
    actionFlashRef.current = flash
    setActionFlash(flash)
  }

  const undoEditorChange = () => {
    const stack = undoStackRef.current
    if (!stack.length) return
    markDirty()
    const entry = stack[stack.length - 1]
    const current = draftRef.current
    const restored = {
      ...current,
      columns: entry.structure.columns,
      rows: entry.structure.rows,
      cellMerges: entry.structure.cellMerges,
      mergesExplicit: Boolean(entry.structure.mergesExplicit),
    }
    const undoneFlash = actionFlashRef.current
    const nextUndo = stack.slice(0, -1)
    const nextRedo = [
      ...redoStackRef.current,
      { structure: cloneEditorStructure(current), flash: undoneFlash },
    ].slice(-HISTORY_LIMIT)
    undoStackRef.current = nextUndo
    redoStackRef.current = nextRedo
    setUndoStack(nextUndo)
    setRedoStack(nextRedo)
    draftRef.current = restored
    setDraft(restored)
    const nextFlash = invertActionFlash(undoneFlash) || invertActionFlash(entry.flash)
    actionFlashRef.current = nextFlash
    setActionFlash(nextFlash)
  }

  const redoEditorChange = () => {
    const stack = redoStackRef.current
    if (!stack.length) return
    markDirty()
    const entry = stack[stack.length - 1]
    const current = draftRef.current
    const restored = {
      ...current,
      columns: entry.structure.columns,
      rows: entry.structure.rows,
      cellMerges: entry.structure.cellMerges,
      mergesExplicit: Boolean(entry.structure.mergesExplicit),
    }
    const nextRedo = stack.slice(0, -1)
    const nextUndo = [
      ...undoStackRef.current,
      { structure: cloneEditorStructure(current), flash: entry.flash },
    ].slice(-HISTORY_LIMIT)
    undoStackRef.current = nextUndo
    redoStackRef.current = nextRedo
    setUndoStack(nextUndo)
    setRedoStack(nextRedo)
    draftRef.current = restored
    setDraft(restored)
    actionFlashRef.current = entry.flash
    setActionFlash(entry.flash)
  }

  const setField = (key, value) => {
    markDirty()
    setDraft((prev) => ({ ...prev, classification: { ...prev.classification, [key]: value } }))
  }
  const setColumn = (idx, key, value) => {
    markDirty()
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => (i === idx ? { ...c, [key]: value } : c)),
    }))
  }
  const setCell = (rowIdx, colIdx, value) => {
    markDirty()
    setDraft((prev) => {
      const ncols = prev.columns.length
      return {
      ...prev,
      rows: prev.rows.map((row, r) => {
        if (r !== rowIdx) return row
          const next = padRowsToColumns([row], ncols)[0]
        next[colIdx] = value
        return next
      }),
      }
    })
  }

  const renameColumn = (idx, name) => {
    markDirty()
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => (i === idx ? applyNameToColumnMeta(c, name) : c)),
    }))
  }
  const changeGroup = (idx, group) => {
    applyEditorChange((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => {
        if (i !== idx) return c
        const header_group = group || null
        const leaf = c.name || columnHeaderPath(c).slice(-1)[0] || 'Column'
        const header_path = header_group ? [header_group, leaf] : [leaf]
        return { ...c, header_group, header_path }
      }),
    }), { axis: 'cols', from: null, to: { start: idx, end: idx } })
  }
  const joinNeighborGroup = (idx, dir) => {
    applyEditorChange((prev) => {
      const n = idx + dir
      if (n < 0 || n >= prev.columns.length) return prev
      const parents = columnParentPath(prev.columns[n])
      if (!parents.length) return prev
      return {
        ...prev,
        columns: prev.columns.map((c, i) => {
          if (i !== idx) return c
          const leaf = c.name || columnHeaderPath(c).slice(-1)[0] || 'Column'
          const header_path = [...parents, leaf]
          return {
            ...c,
            header_path,
            header_group: parents[parents.length - 1] || null,
          }
        }),
      }
    }, { axis: 'cols', from: { start: idx + dir, end: idx + dir }, to: { start: idx, end: idx } })
  }
  const applyHeaderPathLevel = (start, colSpan, levelIdx, label) => {
    markDirty()
    setDraft((prev) => ({
      ...prev,
      columns: setHeaderPathLevel(prev.columns, start, colSpan, levelIdx, label),
    }))
  }
  const mergeCells = (rect) => {
    const { r0, r1, c0, c1 } = rect
    applyEditorChange((prev) => {
      const rowSpan = r1 - r0 + 1
      const colSpan = c1 - c0 + 1
      if (rowSpan <= 1 && colSpan <= 1) return prev
      // First manual merge: lock in any auto-inferred spans so they don't disappear.
      let nextMerges = prev.mergesExplicit || (prev.cellMerges || []).length > 0
        ? (prev.cellMerges || []).map((m) => ({ ...m }))
        : mergesFromSpans(resolveEditorBodySpans(prev.rows, prev.columns, prev.cellMerges, false))
      nextMerges = nextMerges.filter((m) => {
        const mrs = Math.max(1, Number(m.rowSpan) || 1)
        const mcs = Math.max(1, Number(m.colSpan) || 1)
        const overlap = !(m.r + mrs - 1 < r0 || m.r > r1 || m.c + mcs - 1 < c0 || m.c > c1)
        return !overlap
      })
      nextMerges.push({ r: r0, c: c0, rowSpan, colSpan })
      const rows = prev.rows.map((row, r) => {
        if (r < r0 || r > r1) return row
        const next = [...row]
        for (let c = c0; c <= c1; c += 1) {
          if (r === r0 && c === c0) continue
          next[c] = null
        }
        return next
      })
      return { ...prev, rows, cellMerges: nextMerges, mergesExplicit: true }
    }, {
      axis: 'cells',
      from: { r0, r1, c0, c1 },
      to: { r0, r1, c0, c1 },
    })
  }
  const unmergeCells = (r, c) => {
    const preview = unmergeAt(
      draftRef.current.rows,
      draftRef.current.columns,
      draftRef.current.cellMerges,
      draftRef.current.mergesExplicit,
      r,
      c,
    )
    if (!preview) return
    applyEditorChange((prev) => {
      const result = unmergeAt(prev.rows, prev.columns, prev.cellMerges, prev.mergesExplicit, r, c)
      if (!result) return prev
      return {
        ...prev,
        cellMerges: result.cellMerges,
        mergesExplicit: result.mergesExplicit,
      }
    }, preview.flash)
  }
  const moveColumn = (from, to) => {
    if (to < 0 || to >= columnCount || from === to) return
    const insertAt = to > from ? to + 1 : to
    applyEditorChange((prev) => {
      const next = reorderColumnRange(prev.columns, prev.rows, prev.cellMerges, from, 1, insertAt)
      if (next.columns === prev.columns) return prev
      return { ...prev, ...next }
    }, movedBlockFlash('cols', from, 1, insertAt))
  }
  const moveColumnRange = (from, count, insertAt) => {
    if (count < 1) return
    applyEditorChange((prev) => {
      const next = reorderColumnRange(prev.columns, prev.rows, prev.cellMerges, from, count, insertAt)
      if (next.columns === prev.columns) return prev
      return { ...prev, ...next }
    }, movedBlockFlash('cols', from, count, insertAt))
  }
  const mergeHeaderGroups = (start, end, label) => {
    const text = String(label || '').trim() || 'Group'
    applyEditorChange((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => {
        if (i < start || i > end) return c
        return withParentPath(c, [text])
      }),
    }), { axis: 'cols', from: null, to: { start, end } })
  }
  const deleteHeaderGroup = (start, colSpan, levelIdx) => {
    applyEditorChange((prev) => {
      const end = start + Math.max(1, colSpan) - 1
      const depth = Math.max(1, ...prev.columns.map((c) => columnHeaderPath(c).length))
      return {
        ...prev,
        columns: prev.columns.map((col, i) => {
          if (i < start || i > end) return col
          const current = columnHeaderPath(col)
          const leaf = current[current.length - 1] || col.name || `Column ${i + 1}`
          const padded = Array.from({ length: depth }, () => '')
          const offset = Math.max(0, depth - current.length)
          current.forEach((p, j) => { padded[offset + j] = p })
          const idx = Math.min(levelIdx, depth - 2)
          if (idx < 0) return withParentPath(col, [])
          padded[idx] = ''
          let startIdx = 0
          while (startIdx < depth - 1 && !String(padded[startIdx] || '').trim()) startIdx += 1
          const path = padded.slice(startIdx).map((p, pi, arr) => {
            const s = String(p || '').trim()
            if (s) return s
            return pi === arr.length - 1 ? leaf : null
          }).filter((p) => p != null)
          const parents = path.slice(0, -1)
          return withParentPath({ ...col, name: path[path.length - 1] || leaf }, parents)
        }),
      }
    }, { axis: 'cols', from: { start, end: start + Math.max(1, colSpan) - 1 }, to: null })
  }
  const addHeaderGroup = (start, end, label) => {
    const text = String(label || '').trim() || 'New group'
    applyEditorChange((prev) => {
      if (start >= prev.columns.length || end < start) {
        const name = `Column ${prev.columns.length + 1}`
        const newCol = {
          name,
          header_group: text,
          header_path: [text, name],
          role: 'unknown',
          concept: '',
          description: '',
          data_type: 'unknown',
          human_review_needed: false,
          human_review_reason: null,
        }
        const cols = [...prev.columns, newCol]
        const order = prev.columns.map((_, i) => i)
        order.push(null)
        return {
          ...prev,
          columns: cols,
          rows: reshapeRows(prev.rows, order),
        }
      }
      return {
        ...prev,
        columns: prev.columns.map((c, i) => {
          if (i < start || i > end) return c
          return withParentPath(c, [text])
        }),
      }
    }, {
      axis: 'cols',
      from: null,
      to: start >= (draftRef.current.columns?.length || 0) || end < start
        ? { start: draftRef.current.columns?.length || 0, end: draftRef.current.columns?.length || 0 }
        : { start, end },
    })
  }
  const deleteColumns = (start, end) => {
    applyEditorChange((prev) => {
      const lo = Math.min(start, end)
      const hi = Math.max(start, end)
      if (hi - lo + 1 >= prev.columns.length) return prev
      const cols = prev.columns.filter((_, i) => i < lo || i > hi)
      const order = prev.columns.map((_, i) => i).filter((i) => i < lo || i > hi)
      const removed = hi - lo + 1
      const cellMerges = (prev.cellMerges || [])
        .map((m) => {
          const mEnd = m.c + Math.max(1, m.colSpan || 1) - 1
          if (mEnd < lo) return m
          if (m.c > hi) return { ...m, c: m.c - removed }
          return null
        })
        .filter(Boolean)
      return { ...prev, columns: cols, rows: reshapeRows(prev.rows, order), cellMerges }
    }, { axis: 'cols', from: { start: Math.min(start, end), end: Math.max(start, end) }, to: null })
  }
  const deleteColumn = (idx) => {
    deleteColumns(idx, idx)
  }
  const insertColumn = (atIdx, inheritFromIdx = null) => {
    applyEditorChange((prev) => {
      const idx = Math.max(0, Math.min(atIdx, prev.columns.length))
      const name = `Column ${prev.columns.length + 1}`
      let newCol = {
        name,
        header_group: null,
        header_path: [name],
        role: 'unknown',
        concept: '',
        description: '',
        data_type: 'unknown',
        human_review_needed: false,
        human_review_reason: null,
      }
      const inheritIdx = inheritFromIdx == null
        ? null
        : Math.max(0, Math.min(inheritFromIdx, prev.columns.length - 1))
      if (inheritIdx != null && prev.columns[inheritIdx]) {
        newCol = withParentPath(newCol, columnParentPath(prev.columns[inheritIdx]))
      }
      const cols = [...prev.columns]
      cols.splice(idx, 0, newCol)
      const order = []
      for (let i = 0; i < prev.columns.length; i++) {
        if (i === idx) order.push(null)
        order.push(i)
      }
      if (idx >= prev.columns.length) order.push(null)
      const cellMerges = (prev.cellMerges || []).map((m) => {
        if (m.c >= idx) return { ...m, c: m.c + 1 }
        const end = m.c + Math.max(1, m.colSpan || 1) - 1
        if (idx > m.c && idx <= end) return { ...m, colSpan: (m.colSpan || 1) + 1 }
        return m
      })
      return { ...prev, columns: cols, rows: reshapeRows(prev.rows, order), cellMerges }
    }, {
      axis: 'cols',
      from: null,
      to: { start: Math.max(0, Math.min(atIdx, draftRef.current.columns?.length || 0)), end: Math.max(0, Math.min(atIdx, draftRef.current.columns?.length || 0)) },
    })
  }
  const insertRow = (atIdx) => {
    applyEditorChange((prev) => {
      const idx = Math.max(0, Math.min(atIdx, prev.rows.length))
      const empty = Array.from({ length: prev.columns.length }, () => null)
      const merges = materializeCellMerges(prev.rows, prev.columns, prev.cellMerges, prev.mergesExplicit)
      const rows = [...prev.rows]
      rows.splice(idx, 0, empty)
      // Clear cells that fall inside an expanded vertical merge so rowspan stays clean.
      const cellMerges = adjustMergesAfterRowInsert(merges, idx)
      for (const m of cellMerges) {
        const rs = Math.max(1, Number(m.rowSpan) || 1)
        const cs = Math.max(1, Number(m.colSpan) || 1)
        if (!(idx > m.r && idx < m.r + rs)) continue
        const row = rows[idx]
        if (!row) continue
        for (let dc = 0; dc < cs; dc += 1) {
          const c = m.c + dc
          if (c >= 0 && c < row.length) row[c] = null
        }
      }
      return { ...prev, rows, cellMerges, mergesExplicit: true }
    }, {
      axis: 'rows',
      from: null,
      to: { start: Math.max(0, Math.min(atIdx, draftRef.current.rows?.length || 0)), end: Math.max(0, Math.min(atIdx, draftRef.current.rows?.length || 0)) },
    })
  }
  const deleteRow = (idx) => {
    applyEditorChange((prev) => {
      if (prev.rows.length <= 1) return prev
      const merges = materializeCellMerges(prev.rows, prev.columns, prev.cellMerges, prev.mergesExplicit)
      const promoted = promoteMergeValuesBeforeRowDelete(prev.rows, merges, idx)
      const rows = promoted.filter((_, i) => i !== idx)
      const cellMerges = adjustMergesAfterRowDelete(merges, idx)
      return { ...prev, rows, cellMerges, mergesExplicit: true }
    }, { axis: 'rows', from: { start: idx, end: idx }, to: null })
  }
  const moveRowRange = (from, count, insertAt) => {
    if (count < 1) return
    applyEditorChange((prev) => {
      const next = reorderRowRange(prev.rows, prev.cellMerges, from, count, insertAt)
      if (next.rows === prev.rows) return prev
      return { ...prev, ...next }
    }, movedBlockFlash('rows', from, count, insertAt))
  }

  const previewRows = draft.rows || []
  const previewCap = 5
  const previewLimit = Math.min(previewCap, previewRows.length)
  const visiblePreviewRows = previewRows.slice(0, previewLimit)
  // Card shows only the first rows; clip explicit merges so rowspan/colspan stay in-bounds.
  const previewMerges = draft.mergesExplicit || (draft.cellMerges || []).length > 0
    ? (draft.cellMerges || [])
      .map((m) => {
        const r = Number(m.r) || 0
        const c = Number(m.c) || 0
        if (r >= previewLimit) return null
        const rowSpan = Math.min(Math.max(1, Number(m.rowSpan) || 1), previewLimit - r)
        const colSpan = Math.max(1, Number(m.colSpan) || 1)
        if (rowSpan <= 1 && colSpan <= 1) return null
        return { r, c, rowSpan, colSpan }
      })
      .filter(Boolean)
    : []
  const previewCellSpans = resolveEditorBodySpans(
    visiblePreviewRows,
    displayColumns,
    previewMerges,
    Boolean(draft.mergesExplicit),
  )
  const hiddenCount = Math.max(0, previewRows.length - previewLimit)
  const garbledCellCount = (draft.rows || []).flat().filter((v) => isGarbled(v)).length
  const anyCellGarbled = garbledCellCount > 0
  const lockedCols = displayColumns.map((col, i) => isNumericColumn(col, i, previewRows))
  const sourceRowsAligned = padRowsToColumns(
    (originalSnapshot.rows || []).map((row) => row),
    columnCount,
  )

  const baselineCols = columnDraftFromTable(originalSnapshot.columns)
  const rowsDirty = JSON.stringify(draft.rows) !== JSON.stringify(
    padRowsToColumns(originalSnapshot.rows || [], baselineCols.length),
  )
  const colStructureSig = (cols) => JSON.stringify(
    (cols || []).map((c) => ({
      name: c.name || '',
      header_group: c.header_group || '',
      header_path: Array.isArray(c.header_path) ? c.header_path : null,
      role: c.role,
      concept: c.concept || '',
      description: c.description || '',
    })),
  )
  const colsDirty = colStructureSig(draft.columns) !== colStructureSig(baselineCols)
  // Also dirty vs currently saved table (after prior save in session).
  const vsTableColsDirty = colStructureSig(draft.columns) !== colStructureSig(table.columns || [])
  const vsTableRowsDirty = JSON.stringify(draft.rows) !== JSON.stringify(
    padRowsToColumns(table.rows || [], (table.columns || []).length),
  )
  const titleDirty = (draft.title || '').trim() !== titleForEdit(table)
  const structureDirty = colsDirty || vsTableColsDirty || rowsDirty || vsTableRowsDirty
    || JSON.stringify(draft.cellMerges || []) !== JSON.stringify(table.cell_merges || [])
    || Boolean(draft.mergesExplicit) !== Boolean(
      table.cell_merges_explicit || (Array.isArray(table.cell_merges) && table.cell_merges.length > 0)
    )
  const canSave = (table.human_review_needed || structureDirty || titleDirty) && !saved

  const handleSave = () => {
    const classification = Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [
        k,
        { value: draft.classification[k], human_review_needed: false, human_review_reason: null },
      ])
    )
    const columns = draft.columns.map((c) => ({
      ...c,
      name: (c.name || '').trim() || 'Column',
      header_group: c.header_group || null,
      header_path: Array.isArray(c.header_path) && c.header_path.length
        ? c.header_path
        : (c.header_group ? [c.header_group, c.name] : [c.name]),
      human_review_needed: false,
      human_review_reason: null,
    }))
    const title = draft.title.trim() || null
    onSave({
      title,
      classification,
      columns,
      rows: padRowsToColumns(draft.rows, columns.length),
      cell_merges: draft.cellMerges || [],
      cell_merges_explicit: Boolean(draft.mergesExplicit),
      human_review_needed: false,
      human_review_reason: null,
      bbox: table.bbox || null,
    })
    setSaved(true)
  }

  const buildEditorPayload = () => {
    const columns = draft.columns.map((c) => ({
      ...c,
      name: (c.name || '').trim() || 'Column',
      header_group: c.header_group || null,
      header_path: Array.isArray(c.header_path) && c.header_path.length
        ? c.header_path
        : (c.header_group ? [c.header_group, c.name] : [c.name]),
      human_review_needed: false,
      human_review_reason: null,
    }))
    return {
      title: (draft.title || '').trim() || table.title || null,
      columns,
      rows: padRowsToColumns(draft.rows, columns.length),
      cell_merges: draft.cellMerges || [],
      cell_merges_explicit: Boolean(draft.mergesExplicit),
      human_review_needed: false,
      human_review_reason: null,
      bbox: table.bbox || null,
      classification: table.classification || {},
    }
  }

  const persistEditorAndClose = async () => {
    const edits = buildEditorPayload()
    setSavingEditor(true)
    try {
      await onSave?.(edits)
      notifyTableEdited(jobId, table.table_id, edits)
      closeEditorWindow(jobId)
    } catch (e) {
      window.alert(e?.message || 'Could not save table edits')
    } finally {
      setSavingEditor(false)
    }
  }

  const modalTable = { ...table, columns: displayColumns }
  const editorProps = {
    table: modalTable,
    jobId,
    rows: previewRows,
    columns: displayColumns,
    sourceRows: sourceRowsAligned,
    originalSnapshot,
    cellMerges: draft.cellMerges || [],
    mergesExplicit: Boolean(draft.mergesExplicit),
    onChangeCell: setCell,
    onRenameColumn: renameColumn,
    onChangeGroup: changeGroup,
    onJoinNeighborGroup: joinNeighborGroup,
    onSetHeaderPathLevel: applyHeaderPathLevel,
    onInsertColumn: insertColumn,
    onDeleteColumn: deleteColumn,
    onMoveColumn: moveColumn,
    onMoveColumnRange: moveColumnRange,
    onInsertRow: insertRow,
    onDeleteRow: deleteRow,
    onMoveRowRange: moveRowRange,
    onMergeCells: mergeCells,
    onUnmergeCells: unmergeCells,
    onAddHeaderGroup: addHeaderGroup,
    onMergeHeaderGroups: mergeHeaderGroups,
    onDeleteHeaderGroup: deleteHeaderGroup,
    onDeleteColumns: deleteColumns,
    actionFlash,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    undoCount: undoStack.length,
    redoCount: redoStack.length,
    onUndo: undoEditorChange,
    onRedo: redoEditorChange,
  }

  if (editorOnly) {
  return (
      <TableEditModal
        {...editorProps}
        variant="page"
        doneLabel={savingEditor ? 'Saving…' : 'Save & close'}
        footerHint="Saves to the review job, then closes this tab. The review page updates automatically."
        onClose={() => closeEditorWindow(jobId)}
        onDone={persistEditorAndClose}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line px-3.5 pb-3.5 pt-3">
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-teal">Table title</span>
        <input
          type="text"
          className="rounded-md border border-line bg-white px-2.5 py-1.5 text-[13.5px] font-semibold text-ink outline-none focus:border-teal"
          value={draft.title}
          placeholder="Add a table title"
          onChange={(e) => {
            const nextTitle = e.target.value
            markDirty()
            setDraft((prev) => ({ ...prev, title: nextTitle }))
            onTitleLive?.(nextTitle.trim() || null)
          }}
          onBlur={() => {
            onTitleCommit?.(draft.title.trim() || null)
          }}
        />
      </label>

      {table.description && <p className="text-[13px] text-ink-soft">{table.description}</p>}

      {jobId && table.table_id && (
        <ReferenceComparePanel
          jobId={jobId}
          tableId={table.table_id}
          originalSnapshot={originalSnapshot}
        />
      )}

      {showSemanticSections && (
      <CollapsibleSection
        label="Classification"
        open={classificationOpen}
        onToggle={() => setClassificationOpen((v) => !v)}
        hint={classificationNeedsReview ? '· needs review' : undefined}
      >
        <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2">
          {Object.entries(CLASSIFICATION_LABELS).map(([key, label]) => {
            const field = table.classification?.[key] || {}
            return (
              <div key={key} className={`flex flex-col gap-1 rounded-md p-2 ${field.human_review_needed ? 'border border-yellow bg-[#fff8e1]' : 'bg-outer-bg'}`}>
                <div className="text-[11px] font-bold uppercase text-ink-soft">{label}</div>
                {field.human_review_needed ? (
                  <input
                    className="rounded border border-yellow px-1.5 py-1 text-[13px]"
                    value={draft.classification[key] ?? ''}
                    onChange={(e) => setField(key, e.target.value)}
                  />
                ) : (
                  <div className="text-[13px] text-ink">{field.value ?? <em className="text-[#a49c8e]">—</em>}</div>
                )}
                {field.human_review_needed && <ReviewBadge needed reason={field.human_review_reason} />}
              </div>
            )
          })}
        </div>
      </CollapsibleSection>
      )}

      {showSemanticSections && (
      <CollapsibleSection
        label="Column semantics"
        open={columnsOpen}
        onToggle={() => setColumnsOpen((v) => !v)}
        hint={columnsNeedReview ? '· needs review' : `· ${columnCount} column${columnCount === 1 ? '' : 's'}`}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[600px] border-collapse text-[13px]">
            <thead>
              <tr>
                {['Name', 'Role', 'Concept', 'Description', 'Data type', 'Review'].map((h) => (
                  <th key={h} className="border border-teal/50 bg-teal px-2.5 py-1.5 text-left text-[11.5px] uppercase text-cream">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayColumns.map((c, i) => (
                <tr key={i} className={c.human_review_needed ? 'bg-[#fff8e1]' : ''}>
                  <td className="border border-line px-2.5 py-1.5">{c.name}</td>
                  <td className="border border-line px-2.5 py-1.5">
                    <select className="w-full rounded border border-line px-1 py-0.5" value={c.role || 'unknown'} onChange={(e) => setColumn(i, 'role', e.target.value)}>
                        {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                  </td>
                  <td className="border border-line px-2.5 py-1.5">
                    <input className="w-full rounded border border-line px-1 py-0.5" value={c.concept || ''} onChange={(e) => setColumn(i, 'concept', e.target.value)} />
                  </td>
                  <td className="border border-line px-2.5 py-1.5">
                    <input className="w-full rounded border border-line px-1 py-0.5" value={c.description || ''} onChange={(e) => setColumn(i, 'description', e.target.value)} />
                  </td>
                  <td className="border border-line px-2.5 py-1.5">{c.data_type || '—'}</td>
                  <td className="border border-line px-2.5 py-1.5">{c.human_review_needed ? <ReviewBadge needed reason={c.human_review_reason} /> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
      )}

      {table.uncertain_cells?.length > 0 && (
        <>
          <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Extraction uncertainties</div>
          <ul className="list-disc pl-5 text-[13px] text-ink">
            {table.uncertain_cells.map((note, i) => <li key={i}>{note}</li>)}
          </ul>
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="text-[11px] font-bold uppercase tracking-wide text-green">
          Extracted data ({previewRows.length} rows · {columnCount} columns
          {anyCellGarbled ? ` — ${garbledCellCount} cell(s) need review` : ''})
        </div>
        <Button type="button" variant="primary" size="sm" onClick={openFullPageEditor}>
          <Pencil className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden />
          View/Edit table
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] table-fixed border-collapse text-[13px]">
          <ExtractedTableHead columns={displayColumns} lockedCols={lockedCols} />
          <tbody>
            {visiblePreviewRows.map((row, r) => (
              <tr key={r}>
                {Array.from({ length: columnCount }, (_, c) => {
                  const span = previewCellSpans[r]?.[c]
                  if (span == null) return null
                  const v = row[c] ?? null
                  const col = displayColumns[c]
                  const merged = span.rowSpan > 1 || span.colSpan > 1
                  return (
                    <td
                      key={c}
                      rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                      colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                      className={`max-w-0 break-words [overflow-wrap:anywhere] border border-line px-2.5 py-1.5 align-top ${merged ? 'align-middle' : ''}`}
                    >
                      <ExtractedDataCell
                        value={v}
                        sourceValue={sourceRowsAligned[r]?.[c]}
                        col={col}
                        locked
                        fitWidth
                        onChange={() => {}}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {hiddenCount > 0 && (
          <div className="mt-2 text-center text-[12px] text-ink-soft">
            +{hiddenCount} more rows — open Edit table (new tab) to see and change all rows
          </div>
        )}
      </div>

      {canSave && (
        <Button variant="primary" className="self-start" onClick={handleSave}>
          {table.human_review_needed ? 'Save review & mark resolved' : 'Save changes'}
        </Button>
      )}
      {saved && (
        <div className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#3d7a3d]">
          <Check className="h-4 w-4" strokeWidth={2.25} aria-hidden />
          Saved — changes kept for this table.
        </div>
      )}
    </div>
  )
}

export function PdfTableEditorPage({ jobId, tableId }) {
  const [table, setTable] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetch(`/api/pdf/jobs/${encodeURIComponent(jobId)}/result`, withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || 'Could not load table')
        }
        return res.json()
      })
      .then((data) => {
        if (cancelled) return
        const found = (data.tables || []).find((t) => String(t.table_id) === String(tableId))
        if (!found) throw new Error(`Table ${tableId} was not found in this job`)
        setTable(found)
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || 'Could not load table')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [jobId, tableId])

  const saveEdits = async (edits) => {
    const res = await fetch(`/api/pdf/jobs/${encodeURIComponent(jobId)}/tables/${encodeURIComponent(tableId)}`, withAuthHeaders({
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(edits),
    }))
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || 'Could not save table edits')
    }
  }

  if (loading) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-cream text-[14px] text-ink-soft">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-teal" strokeWidth={2} />
        Opening table editor…
      </div>
    )
  }

  if (error || !table) {
    return (
      <div className="flex h-[100dvh] flex-col items-center justify-center gap-3 bg-cream px-6 text-center">
        <div className="text-[15px] font-semibold text-ink">{error || 'Table not found'}</div>
        <Button variant="secondary" size="sm" onClick={() => closeEditorWindow(jobId)}>Close tab</Button>
      </div>
    )
  }

  return (
    <TableDetail
      table={table}
      jobId={jobId}
      editorOnly
      onSave={saveEdits}
    />
  )
}

export default function PdfReview({ jobId, filename, onDone }) {
  const [tables, setTables] = useState(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [reviewedIds, setReviewedIds] = useState(() => new Set())
  const [statusFilter, setStatusFilter] = useState('all')
  const [tablePage, setTablePage] = useState(0)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  // null | 'delete' | 'download' | 'merge' — same checkbox UI, different confirm action
  const [selectMode, setSelectMode] = useState(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState(null)
  const [pendingMergeIds, setPendingMergeIds] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [merging, setMerging] = useState(false)
  const [continuing, setContinuing] = useState(false)
  // 'persist' | 'group' — drives the Continue placeholder stepper
  const [continuePhase, setContinuePhase] = useState('persist')
  const [downloadingZip, setDownloadingZip] = useState(false)
  const [downloadingId, setDownloadingId] = useState(null)
  const rootRef = useRef(null)
  const router = useRouter()

  const triggerBlobDownload = async (url, fallbackName, init = {}) => {
    const res = await fetch(url, withAuthHeaders(init))
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Download failed')
    }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const match = /filename="?([^";]+)"?/i.exec(cd)
    const name = match?.[1] || fallbackName
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(objectUrl)
  }

  const downloadZip = async (tableIds = null) => {
    setDownloadingZip(true)
    setError('')
    try {
      const fallback = `${(filename || 'tables').replace(/\.[^.]+$/, '')}_tables.zip`
      if (tableIds?.length) {
        await triggerBlobDownload(
          `/api/pdf/jobs/${jobId}/tables/download-zip`,
          fallback,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ table_ids: tableIds }),
          },
        )
      } else {
        await triggerBlobDownload(`/api/pdf/jobs/${jobId}/tables/download-zip`, fallback)
      }
      if (selectMode === 'download') exitSelectMode()
    } catch (e) {
      setError(e.message || 'Could not download ZIP')
    } finally {
      setDownloadingZip(false)
    }
  }

  const downloadOneTable = async (tableId, title) => {
    setDownloadingId(tableId)
    setError('')
    try {
      const safe = (title || `table_${tableId}`).replace(/[/\\?%*:|"<>]/g, '_').slice(0, 80)
      await triggerBlobDownload(
        `/api/pdf/jobs/${jobId}/tables/${encodeURIComponent(tableId)}/download`,
        `${safe}.xlsx`,
      )
    } catch (e) {
      setError(e.message || 'Could not download table')
    } finally {
      setDownloadingId(null)
    }
  }

  const continueToGrouping = async () => {
    setContinuing(true)
    setContinuePhase('persist')
    setError('')
    // Advance the stepper while the single persist+propose request runs.
    const phaseTimer = setTimeout(() => setContinuePhase('group'), 900)
    try {
      // Drop stale grouping UI from a previous Continue so the new propose wins.
      try {
        sessionStorage.removeItem(`dhara_pdf_pipeline_v1_${jobId}`)
      } catch {
        /* best-effort */
      }
      const res = await fetch(
        `/api/pdf/jobs/${jobId}/persist-approved`,
        withLlmKeyHeaders(withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Preview state is source of truth for titles / reviews at Continue.
          body: JSON.stringify({
            tables: (tables || []).map((t) => ({
              table_id: t.table_id,
              title: t.title ?? null,
              rows: t.rows,
              columns: t.columns,
              classification: t.classification,
              human_review_needed: t.human_review_needed,
              human_review_reason: t.human_review_reason,
              semantic_status: t.semantic_status,
            })),
          }),
        })),
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save tables for grouping')
      }
      clearTimeout(phaseTimer)
      setContinuePhase('group')
      router.push(`/console/grouping/${jobId}`)
    } catch (e) {
      clearTimeout(phaseTimer)
      setError(e.message || 'Could not continue to grouping')
      setContinuing(false)
      setContinuePhase('persist')
    }
  }

  useEffect(() => {
    let cancelled = false
    fetch(`/api/pdf/jobs/${jobId}/result`, withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          let detail = ''
          try {
            const body = await res.json()
            detail = body?.detail || ''
          } catch { /* ignore */ }
          if (res.status === 404) {
            throw new Error(detail || 'This extraction job is no longer available (server restarted). Please upload the PDF again.')
          }
          if (res.status === 409) {
            throw new Error(detail || 'Extraction is still running — wait for it to finish, then refresh.')
          }
          throw new Error(detail || 'Could not load results')
        }
        return res.json()
      })
      .then((data) => { if (!cancelled) setTables(data.tables) })
      .catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [jobId])

  // Sync when the full-page editor tab saves (BroadcastChannel + storage fallback).
  useEffect(() => {
    const apply = (payload) => {
      if (!payload || payload.jobId !== jobId) return
      const { tableId, edits } = payload
      if (!tableId || !edits) return
      setTables((prev) => prev.map((t) => (t.table_id === tableId ? { ...t, ...edits } : t)))
      setReviewedIds((prev) => new Set(prev).add(tableId))
    }
    let bc
    try {
      bc = new BroadcastChannel(TABLE_EDIT_CHANNEL)
      bc.onmessage = (ev) => {
        if (ev?.data?.type === 'table-edited') apply(ev.data)
      }
    } catch {
      bc = null
    }
    const onStorage = (ev) => {
      if (ev.key !== TABLE_EDIT_CHANNEL || !ev.newValue) return
      try {
        apply(JSON.parse(ev.newValue))
      } catch {
        /* ignore */
      }
    }
    const onFocus = () => {
      // Re-fetch so this tab stays fresh if BroadcastChannel was blocked.
      fetch(`/api/pdf/jobs/${jobId}/result`, withAuthHeaders())
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => { if (data?.tables) setTables(data.tables) })
        .catch(() => {})
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener('focus', onFocus)
    return () => {
      bc?.close()
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('focus', onFocus)
    }
  }, [jobId])

  const saveReview = async (tableId, edits) => {
    setTables((prev) => prev.map((t) => (t.table_id === tableId ? { ...t, ...edits } : t)))
    setReviewedIds((prev) => new Set(prev).add(tableId))
    try {
      await fetch(`/api/pdf/jobs/${jobId}/tables/${tableId}`, withAuthHeaders({
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(edits),
      }))
    } catch {
      // Local state already reflects the edit; a failed PATCH just means it
      // won't persist server-side if the page is reloaded -- non-fatal here.
    }
  }

  const confirmDelete = async () => {
    if (!pendingDeleteIds?.length) return
    setDeleting(true)
    const ids = [...pendingDeleteIds]
    try {
      const res = await fetch(`/api/pdf/jobs/${jobId}/tables/delete`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_ids: ids }),
      }))
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || 'Could not delete tables')
      }
      const idSet = new Set(ids)
      setTables((prev) => prev.filter((t) => !idSet.has(t.table_id)))
      setSelectedIds((prev) => {
        const next = new Set(prev)
        ids.forEach((id) => next.delete(id))
        return next
      })
      setReviewedIds((prev) => {
        const next = new Set(prev)
        ids.forEach((id) => next.delete(id))
        return next
      })
      if (expanded && idSet.has(expanded)) setExpanded(null)
      setPendingDeleteIds(null)
      setSelectedIds(new Set())
      setSelectMode(null)
    } catch (e) {
      setError(e.message || 'Could not delete tables')
      setPendingDeleteIds(null)
    } finally {
      setDeleting(false)
    }
  }

  const confirmMerge = async () => {
    if (!pendingMergeIds?.length || pendingMergeIds.length < 2) return
    setMerging(true)
    setError('')
    const ids = [...pendingMergeIds]
    try {
      const res = await fetch(`/api/pdf/jobs/${jobId}/tables/merge`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_ids: ids }),
      }))
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not merge tables')
      }
      const body = await res.json()
      const survivorId = body.survivor_table_id
      const removed = new Set(body.merged_table_ids || [])
      setTables((prev) => {
        const next = prev.filter((t) => !removed.has(t.table_id))
        if (body.table) {
          return next.map((t) => (t.table_id === survivorId ? { ...t, ...body.table } : t))
        }
        return next
      })
      setReviewedIds((prev) => {
        const next = new Set(prev)
        removed.forEach((id) => next.delete(id))
        return next
      })
      if (expanded && removed.has(expanded)) setExpanded(survivorId || null)
      setPendingMergeIds(null)
      setSelectedIds(new Set())
      setSelectMode(null)
    } catch (e) {
      setError(e.message || 'Could not merge tables')
      setPendingMergeIds(null)
    } finally {
      setMerging(false)
    }
  }

  const exitSelectMode = () => {
    setSelectMode(null)
    setSelectedIds(new Set())
  }

  const enterSelectMode = (mode) => {
    setSelectMode(mode)
    setSelectedIds(new Set())
    setExpanded(null)
    setTablePage(0)
  }

  if (error && !tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <button
              type="button"
              className="mb-3.5 inline-flex items-center gap-1.5 self-start text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={onDone}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Upload another PDF
            </button>
            <div className="font-display text-[26px] font-medium leading-tight text-ink">Review Extracted Tables</div>
            <div className="mt-1 text-[15px] text-ink-soft">Couldn’t load this extraction job.</div>
          </div>
          <div className="flex flex-col gap-3 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
            <ErrorBanner>{error}</ErrorBanner>
            <Button variant="primary" className="self-start" onClick={onDone}>Upload PDF again</Button>
          </div>
        </div>
      </PdfConsoleLayout>
    )
  }
  if (!tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <div className="font-display text-[26px] font-medium leading-tight text-ink">Review Extracted Tables</div>
            <div className="mt-1 text-[15px] text-ink-soft">Loading results…</div>
          </div>
          <div className="rounded-xl border border-line bg-white p-5 py-10 text-center text-ink-soft shadow-sm sm:p-6">
            Loading results…
          </div>
        </div>
      </PdfConsoleLayout>
    )
  }

  if (continuing) {
    const persistDone = continuePhase === 'group'
    const continueSteps = [
      {
        key: 'persist',
        label: 'Saving approved tables',
        status: persistDone ? 'done' : 'active',
        message: persistDone ? undefined : 'Writing reviewed tables so grouping can use them…',
      },
      {
        key: 'group',
        label: 'Grouping similar tables',
        status: persistDone ? 'active' : 'pending',
        message: persistDone ? 'Building embeddings and proposing groups…' : undefined,
      },
    ]
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
        <div className="mx-auto flex max-w-xl flex-col gap-8 py-8">
          <div>
            <div className="font-display text-xl font-medium text-ink">{filename || 'Preparing grouping'}</div>
            <div className="mt-1 text-sm text-ink-soft">
              Saving your tables and running grouping — this may take a moment.
            </div>
          </div>
          <ProcessingStepper steps={continueSteps} />
        </div>
      </PdfConsoleLayout>
    )
  }

  const filterCounts = {
    all: tables.length, needs_review: 0, no_review: 0, reviewed: 0,
    dev_ai_classified: 0, dev_auto_extracted: 0,
  }
  for (const key of Object.keys(REASON_LABELS)) filterCounts[key] = 0
  for (const t of tables) {
    const reviewed = reviewedIds.has(t.table_id)
    if (reviewed) filterCounts.reviewed += 1
    if (matchesStatusFilter(t, 'needs_review', reviewed)) filterCounts.needs_review += 1
    if (matchesStatusFilter(t, 'no_review', reviewed)) filterCounts.no_review += 1
    if (isAiClassified(t)) filterCounts.dev_ai_classified += 1
    else filterCounts.dev_auto_extracted += 1
    for (const reason of collectReviewReasons(t)) {
      if (filterCounts[reason] !== undefined) filterCounts[reason] += 1
    }
  }

  const primaryFilterOptions = [
    { id: 'all', label: 'All' },
    ...PRIMARY_FILTERS
      .filter((id) => (filterCounts[id] ?? 0) > 0)
      .map((id) => ({
        id,
        label: id === 'needs_review' ? 'Review needed' : 'No review needed',
      })),
    ...(filterCounts.reviewed > 0 ? [{ id: 'reviewed', label: 'Reviewed' }] : []),
    // DEV-ONLY: isolate tables that went through the OpenAI classification
    // step vs. the deterministic auto-accepted path, for QA'ing AI output.
    // Never shown in a production build.
    ...(process.env.NODE_ENV !== 'production' ? [
      { id: 'dev_ai_classified', label: 'Dev: AI classified' },
      { id: 'dev_auto_extracted', label: 'Dev: Auto-extracted' },
    ] : []),
  ]

  const reasonFilterOptions = REASON_FILTER_IDS
    .filter((id) => (filterCounts[id] ?? 0) > 0)
    .map((id) => ({ id, label: REASON_LABELS[id] }))

  const allFilterIds = new Set([
    ...primaryFilterOptions.map((o) => o.id),
    ...reasonFilterOptions.map((o) => o.id),
  ])
  // If the active filter no longer has matches (e.g. after deletes), fall back to All.
  const activeFilter = allFilterIds.has(statusFilter) ? statusFilter : 'all'
  const showReasonFilters = (
    activeFilter === 'needs_review' || REASON_FILTER_IDS.includes(activeFilter)
  ) && reasonFilterOptions.length > 0

  let filteredTables = tables.filter((t) =>
    matchesStatusFilter(t, activeFilter, reviewedIds.has(t.table_id))
  )
  // Merge mode: after the first selection, only show tables with the same headers.
  if (selectMode === 'merge' && selectedIds.size > 0) {
    const anchor = tables.find((t) => selectedIds.has(t.table_id))
    const key = anchor ? tableHeaderKey(anchor) : ''
    if (key) {
      filteredTables = filteredTables.filter((t) => tableHeaderKey(t) === key)
    }
  }
  const TABLES_PER_PAGE = 25
  const filteredCount = filteredTables.length
  const pageCount = Math.max(1, Math.ceil(filteredCount / TABLES_PER_PAGE) || 1)
  const currentPage = Math.min(Math.max(0, tablePage), pageCount - 1)
  const pageStart = currentPage * TABLES_PER_PAGE
  const pageTables = filteredTables.slice(pageStart, pageStart + TABLES_PER_PAGE)
  const pageEnd = filteredCount === 0 ? 0 : pageStart + pageTables.length
  const filteredIds = filteredTables.map((t) => t.table_id)
  const allFilteredSelected = filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const selectedCount = selectedIds.size
  const canMerge = selectMode === 'merge' && selectedCount >= 2

  const toggleSelected = (tableId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(tableId)) next.delete(tableId)
      else next.add(tableId)
      return next
    })
  }

  const toggleSelectAllFiltered = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allFilteredSelected) filteredIds.forEach((id) => next.delete(id))
      else filteredIds.forEach((id) => next.add(id))
      return next
    })
  }

  const goPrevTablePage = () => {
    setExpanded(null)
    setTablePage((p) => Math.max(0, Math.min(p, pageCount - 1) - 1))
  }
  const goNextTablePage = () => {
    setExpanded(null)
    setTablePage((p) => Math.min(pageCount - 1, Math.min(p, pageCount - 1) + 1))
  }
  const tablesPaginationBar = filteredCount > 0 ? (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="text-[12.5px] text-ink-soft">
        Showing {pageStart + 1}–{pageEnd} of {filteredCount}
        {activeFilter !== 'all' ? ' (filtered)' : ''}
        {' · '}{TABLES_PER_PAGE} per page
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-white text-ink-soft hover:border-teal hover:text-teal disabled:cursor-not-allowed disabled:opacity-35"
          disabled={currentPage <= 0}
          aria-label="Previous page"
          title="Previous page"
          onClick={goPrevTablePage}
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>
        <span className="min-w-[5.5rem] text-center text-[12.5px] font-semibold tabular-nums text-ink">
          {currentPage + 1} / {pageCount}
        </span>
        <button
          type="button"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-white text-ink-soft hover:border-teal hover:text-teal disabled:cursor-not-allowed disabled:opacity-35"
          disabled={currentPage >= pageCount - 1}
          aria-label="Next page"
          title="Next page"
          onClick={goNextTablePage}
        >
          <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>
      </div>
    </div>
  ) : null

  const chipClass = (active) =>
    `dhara-tab flex h-8 flex-none items-center gap-1.5 rounded-full px-3.5 text-[12.5px] font-semibold ${
      active
        ? 'border-teal-deep bg-teal-deep text-cream'
        : 'border-line bg-white text-ink-soft hover:border-teal/35 hover:bg-sage hover:text-teal-deep'
    }`

  return (
    <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
    <div ref={rootRef} className="flex flex-col gap-[18px]">
      <ScrollToTopButton scrollRootRef={rootRef} />
      {pendingDeleteIds && (
        <DeleteConfirmDialog
          count={pendingDeleteIds.length}
          onCancel={() => !deleting && setPendingDeleteIds(null)}
          onConfirm={confirmDelete}
          deleting={deleting}
        />
      )}
      {pendingMergeIds && (
        <MergeConfirmDialog
          count={pendingMergeIds.length}
          onCancel={() => !merging && setPendingMergeIds(null)}
          onConfirm={confirmMerge}
          merging={merging}
        />
      )}

      {/* Page header — title / purpose stay above the content panel */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
            onClick={onDone}
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            Upload another PDF
          </button>
          <div className="font-display text-[26px] font-medium leading-tight text-ink">Review Extracted Tables</div>
          <div className="mt-1.5 text-[13px] font-medium text-ink">
            {filename || 'PDF report'}
            {filteredCount > 0 ? (
              <span className="font-normal text-ink-soft">
                {' '}· page {currentPage + 1} of {pageCount}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-none flex-wrap items-center justify-end gap-2.5">
          <KydsSummaryCard variant="corner" />
          <Button variant="primary" disabled={continuing} onClick={continueToGrouping} className="inline-flex items-center gap-1.5">
            {continuing ? 'Saving…' : (
              <>
                Continue
                <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
              </>
            )}
          </Button>
        </div>
      </div>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {/* Content box: filters stick at the top of the scrollport while tables scroll underneath. */}
      <div className="rounded-xl border border-line bg-white shadow-sm">
        <div className="sticky top-0 z-20 space-y-2 rounded-t-xl border-b border-line bg-white px-5 py-3 sm:px-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex-none text-[13px] font-bold tracking-wide text-ink">
              Filter by:
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap gap-2" role="tablist" aria-label="Filter tables by review status">
              {primaryFilterOptions.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={activeFilter === id || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter))}
                  className={chipClass(activeFilter === id || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter)))}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold transition-colors duration-[420ms] ${
                    activeFilter === id || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter))
                      ? 'bg-cream/20 text-cream'
                      : 'bg-cream text-ink-soft'
                  }`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
            {!selectMode ? (
              <div className="ml-auto flex flex-none items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={tables.length < 2}
                  onClick={() => enterSelectMode('merge')}
                  title="Merge tables that share the same column headers"
                >
                  Merge
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="!border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                  disabled={tables.length === 0}
                  onClick={() => enterSelectMode('delete')}
                >
                  Delete
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!tables?.length || downloadingZip}
                  onClick={() => enterSelectMode('download')}
                  title="Select tables to download as a ZIP"
                >
                  Download
                </Button>
              </div>
            ) : null}
          </div>

          {showReasonFilters && (
            <div
              className="flex flex-wrap items-center gap-2 border-t border-line/70 pt-2"
              role="tablist"
              aria-label="Filter by review reason"
            >
              <span className="flex-none text-[12px] font-semibold tracking-wide text-ink-soft">
                Reason:
              </span>
              {reasonFilterOptions.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={activeFilter === id}
                  className={chipClass(activeFilter === id)}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold transition-colors duration-[420ms] ${
                    activeFilter === id ? 'bg-cream/20 text-cream' : 'bg-cream text-ink-soft'
                  }`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
          )}

          {selectMode && (
            <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-line bg-cream/80 px-3 py-2">
              <label className="flex cursor-pointer items-center gap-2 text-[13px] font-semibold text-ink">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 accent-teal"
                  checked={allFilteredSelected}
                  disabled={filteredIds.length === 0}
                  onChange={toggleSelectAllFiltered}
                />
                Select all{activeFilter !== 'all' || selectMode === 'merge' ? ' shown' : ''}
              </label>
              <span className="text-[12.5px] text-ink-soft">
                {selectedCount === 0
                  ? (selectMode === 'merge' ? 'Select a table — then only matching headers stay listed' : 'None selected')
                  : `${selectedCount} selected`}
                {selectMode === 'download'
                  ? ' · download as ZIP'
                  : selectMode === 'merge'
                    ? ' · merge same-header tables'
                    : ' · delete'}
              </span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <Button variant="secondary" size="sm" onClick={exitSelectMode} disabled={downloadingZip || merging}>
                  Cancel
                </Button>
                {selectMode === 'delete' ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="!border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                    disabled={selectedCount === 0}
                    onClick={() => setPendingDeleteIds([...selectedIds])}
                  >
                    Delete selected
                  </Button>
                ) : selectMode === 'merge' ? (
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={!canMerge || merging}
                    onClick={() => setPendingMergeIds([...selectedIds])}
                  >
                    Merge selected{selectedCount >= 2 ? ` (${selectedCount})` : ''}
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={!tables?.length || downloadingZip}
                      onClick={() => downloadZip(null)}
                    >
                      {downloadingZip ? 'Preparing…' : 'Download all'}
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={selectedCount === 0 || downloadingZip}
                      onClick={() => downloadZip([...selectedIds])}
                    >
                      {downloadingZip ? 'Preparing…' : `Download selected${selectedCount ? ` (${selectedCount})` : ''}`}
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}

          {tablesPaginationBar ? (
            <div className="border-t border-line pt-2">
              {tablesPaginationBar}
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 px-5 py-3 sm:px-6 sm:pb-5">
          {filteredCount === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-2 py-10 text-center text-[13px] text-ink-soft">
              {selectMode === 'merge' && selectedIds.size > 0
                ? 'No other tables share these column headers.'
                : 'No tables match this filter.'}
            </div>
          ) : pageTables.map((t) => {
            const isOpen = expanded === t.table_id
            const reviewed = reviewedIds.has(t.table_id)
            const selected = selectedIds.has(t.table_id)
            return (
              <div key={t.table_id} className={`overflow-hidden rounded-lg border bg-surface transition-[border-color] duration-300 ease-out ${isOpen ? 'border-teal' : selectMode && selected ? 'border-teal/50' : 'border-line'}`}>
                <div className="flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-cream">
                  {selectMode && (
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 flex-none accent-teal"
                      checked={selected}
                      aria-label={`Select ${displayTitle(t) || `page ${t.page} table`}`}
                      onChange={() => toggleSelected(t.table_id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  )}
                  <div
                    className="flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-3"
                    onClick={() => setExpanded(isOpen ? null : t.table_id)}
                  >
                    <div className="min-w-0 flex-1">
                      <TableTitleDisplay table={t} />
                      <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                        Page {t.page} · {t.semantic_status === 'classified' ? 'AI-classified' : 'Auto-accepted (no AI review)'}
                      </div>
                    </div>
                    <div className="flex flex-none items-center gap-2">
                      {!selectMode && (
                        <button
                          type="button"
                          className="flex h-7 w-7 flex-none items-center justify-center rounded border border-line text-ink-soft hover:border-teal hover:text-teal disabled:opacity-50"
                          title="Download this table"
                          aria-label="Download this table"
                          disabled={downloadingId === t.table_id}
                          onClick={(e) => {
                            e.stopPropagation()
                            downloadOneTable(t.table_id, displayTitle(t) || `page_${t.page}_table`)
                          }}
                        >
                          {downloadingId === t.table_id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
                          ) : (
                            <Download className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden />
                          )}
                        </button>
                      )}
                      {reviewed ? (
                        <Badge tone="ok">
                          <span className="inline-flex items-center gap-1">
                            <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden />
                            Reviewed
                          </span>
                        </Badge>
                      ) : (
                        <ReviewBadge needed={t.human_review_needed} reason={t.human_review_reason} />
                      )}
                    </div>
                  </div>
                </div>
                <TableExpandPanel open={isOpen}>
                  <TableDetail
                    table={t}
                    jobId={jobId}
                    onSave={(edits) => saveReview(t.table_id, edits)}
                    onTitleLive={(title) => {
                      setTables((prev) => prev.map((row) => (
                        row.table_id === t.table_id ? { ...row, title } : row
                      )))
                    }}
                    onTitleCommit={(title) => saveReview(t.table_id, { title })}
                  />
                </TableExpandPanel>
              </div>
            )
          })}

          {tablesPaginationBar ? (
            <div className="mt-2 border-t border-line pt-3">
              {tablesPaginationBar}
            </div>
          ) : null}
        </div>
      </div>
    </div>
    </PdfConsoleLayout>
  )
}
