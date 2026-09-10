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
  Download,
  Loader2,
  Minus,
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

/** Nearest ancestor that actually scrolls (AppShell main pane). */
function getScrollParent(el) {
  let node = el?.parentElement
  while (node && node !== document.body) {
    const { overflowY } = getComputedStyle(node)
    if (overflowY === 'auto' || overflowY === 'scroll') return node
    node = node.parentElement
  }
  return null
}

function ScrollToTopButton({ scrollRootRef }) {
  const [visible, setVisible] = useState(false)
  const scrollElRef = useRef(null)

  useEffect(() => {
    const scrollEl = getScrollParent(scrollRootRef?.current)
    scrollElRef.current = scrollEl
    if (!scrollEl) return undefined

    const onScroll = () => setVisible(scrollEl.scrollTop > 240)
    onScroll()
    scrollEl.addEventListener('scroll', onScroll, { passive: true })
    return () => scrollEl.removeEventListener('scroll', onScroll)
  }, [scrollRootRef])

  const scrollUp = () => {
    const el = scrollElRef.current
    if (el) el.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <button
      type="button"
      aria-label="Scroll to top"
      onClick={scrollUp}
      className={`fixed bottom-7 right-7 z-40 flex h-11 w-11 items-center justify-center rounded-full border border-line bg-white text-teal shadow-[0_6px_20px_rgba(16,64,63,0.16)] transition-all duration-200 hover:border-teal hover:bg-sage ${
        visible ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0'
      }`}
    >
      <ArrowUp className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
    </button>
  )
}

const CLASSIFICATION_LABELS = {
  domain: 'Domain', subject: 'Subject', entity: 'Entity', table_type: 'Table type',
  geography: 'Geography', time_period: 'Time period', frequency: 'Frequency', unit: 'Unit',
}

const REASON_LABELS = {
  garbled_extracted_value: 'Garbled/corrupted value',
  // ADDED: post-LLM structural check when cells don't match their column headers.
  column_alignment_mismatch: 'Column alignment mismatch',
  conflicting_extraction: 'Conflicting extraction',
  uncertain_extraction: 'Uncertain extraction',
  uncertain_semantic_role: 'Uncertain column role',
  uncertain_concept: 'Uncertain concept',
  ambiguous_column: 'Ambiguous column',
}

const ROLE_OPTIONS = ['identifier', 'dimension', 'measure', 'attribute', 'unknown']

/** Primary filter chips shown in order; others appear only when present. */
const PRIMARY_FILTERS = ['needs_review', 'no_review', 'uncertain_extraction', 'garbled_extracted_value']

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
  if (table.human_review_reason) reasons.add(table.human_review_reason)
  for (const field of Object.values(table.classification || {})) {
    if (field?.human_review_reason) reasons.add(field.human_review_reason)
  }
  for (const col of table.columns || []) {
    if (col.human_review_reason) reasons.add(col.human_review_reason)
  }
  if (tableHasGarbledCells(table)) reasons.add('garbled_extracted_value')
  if ((table.uncertain_cells || []).length > 0 && !reasons.has('conflicting_extraction')) {
    reasons.add('uncertain_extraction')
  }
  return reasons
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
  return collectReviewReasons(table).has(filter)
}

function ReviewBadge({ needed, reason }) {
  if (!needed) return <Badge tone="ok">No review needed</Badge>
  return <Badge tone="warn">{REASON_LABELS[reason] || 'Needs review'}</Badge>
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
      'px-2.5 py-1.5 align-top font-sans text-[11.5px] uppercase tracking-wide text-cream bg-teal',
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
                <span className={sticky || stickyOn ? 'block [overflow-wrap:anywhere] break-words hyphens-auto' : undefined}>
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
 * Reconstruct body cell merges from empty cells under label columns
 * (pymupdf leaves rowspan/colspan continuations empty).
 *
 * Returns spans[r][c] = { rowSpan, colSpan } or null when covered by a prior merge.
 *
 * Vertical spans stop when:
 *  - a label column to the left introduces a new value, or
 *  - a sibling group label changes (e.g. Item "Others" → "ALL"), or
 *  - a table-footer summary row (last row with TOTAL/ALL in Sex etc.) would
 *    otherwise absorb blank Sl. No. / District cells from the group above.
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
        className={`${controlWidth} box-border rounded px-1 py-0.5 text-[12.5px] ${flagged ? 'border border-yellow bg-[#fff8e1]' : 'border border-transparent bg-transparent hover:border-line focus:border-teal'} ${dir?.className || ''}`}
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
    return (
      <input
        size={1}
        className={`${controlWidth} box-border rounded px-1 py-0.5 text-[12.5px] ${flagged ? 'border border-yellow bg-[#fff8e1]' : 'border border-transparent bg-transparent hover:border-line focus:border-teal'}`}
        style={fitStyle}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
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
      className={`block ${fitWidth ? 'min-w-0 [overflow-wrap:anywhere] break-words' : ''} ${display == null ? 'italic text-[#a49c8e]' : 'text-ink'}`}
      title={display || ''}
    >
      {display == null ? '—' : display}
    </span>
  )
}

/**
 * KYDS-style overlay with an Excel-like scrollable grid of all extracted rows.
 * Edits flow through onChangeCell into TableDetail's draft.
 */
function ExtractedDataRowsModal({
  table,
  rows,
  sourceRows,
  lockedCols,
  onChangeCell,
  onClose,
}) {
  const columns = table.columns || []
  const columnCount = columns.length
  const cellSpans = buildBodyCellSpans(rows, columns)
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

  // Percentages must sum to exactly 100% (no rem + % mix) or the table grows past the modal.
  const INDEX_PCT = columnCount >= 8 ? 3 : 4
  const labelFlags = columns.map((col, i) => {
    const n = String(col?.name || '').toLowerCase()
    return (
      n.includes('state')
      || n.includes('indicator')
      || (n.includes('name') && !n.includes('percentage'))
      || (n.includes('ut') && n.includes('state'))
    )
  })
  const weights = columns.map((_, i) => (labelFlags[i] ? 2.4 : 1))
  const weightSum = weights.reduce((a, b) => a + b, 0) || 1
  const remPct = 100 - INDEX_PCT
  const colWidths = weights.map((w) => (remPct * w) / weightSum)

  if (!mounted) return null
  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center overflow-hidden bg-[rgba(16,64,63,0.52)] p-4 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="extracted-data-title"
      onClick={onClose}
    >
      <div
        className="flex h-[min(720px,90vh)] w-[min(1200px,calc(100vw-2rem))] flex-none flex-col overflow-hidden rounded-[14px] bg-surface shadow-dhara"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative flex flex-shrink-0 items-center justify-center bg-cream px-12 pb-4 pt-5 text-center">
          <div className="min-w-0 max-w-full">
            <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-teal">Extracted data</div>
            <div id="extracted-data-title" className={`truncate text-2xl font-bold tracking-tight ${displayTitle(table) ? 'text-ink' : 'italic text-ink-soft'}`}>
              {displayTitle(table) || 'No title — review'}
            </div>
            <div className="mt-1.5 text-[13.5px] leading-relaxed text-ink-soft">
              Page {table.page} · {rows.length.toLocaleString()} row{rows.length === 1 ? '' : 's'} · {columnCount} column{columnCount === 1 ? '' : 's'}
              {lockedCols.some(Boolean) ? ' · numeric columns read-only' : ''}
            </div>
          </div>
          <button
            type="button"
            className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-cream hover:text-ink"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
        </div>

        {/* Vertical scroll only: clip X on the scroller so wide tables cannot add a horizontal bar. */}
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 pb-4 pt-3 sm:px-5 sm:pb-5 sm:pt-4">
          <div className="w-full max-w-full overflow-hidden rounded-lg border border-[#cfc6b4] bg-surface">
            <table
              className="w-full max-w-full table-fixed border-collapse text-[12px]"
              style={{ width: '100%', tableLayout: 'fixed' }}
            >
              <colgroup>
                <col style={{ width: `${INDEX_PCT}%` }} />
                {colWidths.map((w, i) => (
                  <col key={i} style={{ width: `${w}%` }} />
                ))}
              </colgroup>
              <ExtractedTableHead columns={columns} lockedCols={lockedCols} sticky showIndex />
              <tbody>
                {rows.map((row, r) => (
                  <tr
                    key={r}
                    className={`${r % 2 === 0 ? 'bg-[#FFFCF6]' : 'bg-surface'} hover:bg-[#F4EFE3]`}
                  >
                    <td className="max-w-0 border border-[#cfc6b4] px-1 py-1.5 text-center text-[10px] tabular-nums text-ink-soft">
                      {r + 1}
                    </td>
                    {Array.from({ length: columnCount }, (_, c) => {
                      const span = cellSpans[r]?.[c]
                      if (span == null) return null
                      const merged = span.rowSpan > 1 || span.colSpan > 1
                      return (
                        <td
                          key={c}
                          rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                          colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                          className={`max-w-0 overflow-hidden border border-[#cfc6b4] px-1 py-1.5 ${merged ? 'align-middle' : 'align-top'}`}
                        >
                          <ExtractedDataCell
                            value={row[c] ?? null}
                            sourceValue={sourceRows[r]?.[c]}
                            col={columns[c]}
                            locked={lockedCols[c]}
                            fitWidth
                            onChange={(next) => onChangeCell(r, c, next)}
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex flex-shrink-0 items-center justify-end gap-2.5 border-t border-line bg-cream/60 px-5 py-3">
          <Button variant="primary" size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
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
// (integer / decimal / percentage) stay read-only.
function TableDetail({ table, onSave, onTitleLive, onTitleCommit }) {
  const classificationNeedsReview = Object.values(table.classification || {}).some((f) => f?.human_review_needed)
  const columnsNeedReview = (table.columns || []).some((c) => c.human_review_needed)
  const columnCount = (table.columns || []).length
  // Auto-accepted tables skip the LLM classify step, so classification /
  // column semantics stay empty — hide those sections in Preview.
  const showSemanticSections = table.semantic_status === 'classified'

  const [draft, setDraft] = useState(() => ({
    title: titleForEdit(table),
    classification: Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [k, f?.value ?? ''])
    ),
    columns: (table.columns || []).map((c) => ({ role: c.role, concept: c.concept || '', description: c.description || '' })),
    rows: padRowsToColumns(table.rows || [], columnCount),
  }))
  const [saved, setSaved] = useState(false)
  const [rowsModalOpen, setRowsModalOpen] = useState(false)
  const [classificationOpen, setClassificationOpen] = useState(classificationNeedsReview)
  const [columnsOpen, setColumnsOpen] = useState(columnsNeedReview)

  useEffect(() => {
    setDraft((prev) => ({ ...prev, title: titleForEdit(table) }))
  }, [table.title, table.columns])

  const setField = (key, value) =>
    setDraft((prev) => ({ ...prev, classification: { ...prev.classification, [key]: value } }))
  const setColumn = (idx, key, value) =>
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => (i === idx ? { ...c, [key]: value } : c)),
    }))
  const setCell = (rowIdx, colIdx, value) => {
    setSaved(false)
    setDraft((prev) => ({
      ...prev,
      rows: prev.rows.map((row, r) => {
        if (r !== rowIdx) return row
        const next = padRowsToColumns([row], columnCount)[0]
        next[colIdx] = value
        return next
      }),
    }))
  }

  const previewRows = draft.rows || []
  const sourceRows = padRowsToColumns(table.rows || [], columnCount)
  const previewCap = 5
  const previewLimit = Math.min(previewCap, previewRows.length)
  const visiblePreviewRows = previewRows.slice(0, previewLimit)
  const previewCellSpans = buildBodyCellSpans(visiblePreviewRows, table.columns || [])
  const hiddenCount = Math.max(0, previewRows.length - previewLimit)
  const garbledCellCount = sourceRows.flat().filter((v) => isGarbled(v)).length
  const anyCellGarbled = garbledCellCount > 0
  const lockedCols = (table.columns || []).map((col, i) => isNumericColumn(col, i, sourceRows))
  const editableColCount = lockedCols.filter((locked) => !locked).length
  const rowsDirty = JSON.stringify(draft.rows) !== JSON.stringify(sourceRows)
  const titleDirty = (draft.title || '').trim() !== titleForEdit(table)
  const canSave = (table.human_review_needed || rowsDirty || titleDirty) && !saved

  const handleSave = () => {
    const classification = Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [
        k,
        { value: draft.classification[k], human_review_needed: false, human_review_reason: null },
      ])
    )
    const columns = (table.columns || []).map((c, i) => ({
      ...c,
      role: draft.columns[i].role,
      concept: draft.columns[i].concept,
      description: draft.columns[i].description,
      human_review_needed: false,
      human_review_reason: null,
    }))
    const title = draft.title.trim() || null
    onSave({
      title,
      classification,
      columns,
      rows: draft.rows,
      human_review_needed: false,
      human_review_reason: null,
    })
    setSaved(true)
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line px-3.5 pb-3.5 pt-3">
      {rowsModalOpen && (
        <ExtractedDataRowsModal
          table={table}
          rows={previewRows}
          sourceRows={sourceRows}
          lockedCols={lockedCols}
          onChangeCell={setCell}
          onClose={() => setRowsModalOpen(false)}
        />
      )}
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-teal">Table title</span>
        <input
          type="text"
          className="rounded-md border border-line bg-white px-2.5 py-1.5 text-[13.5px] font-semibold text-ink outline-none focus:border-teal"
          value={draft.title}
          placeholder="Add a table title"
          onChange={(e) => {
            const nextTitle = e.target.value
            setSaved(false)
            setDraft((prev) => ({ ...prev, title: nextTitle }))
            // Keep parent Preview state in sync so Continue persists the latest title
            // even if the user never clicks "Save changes".
            onTitleLive?.(nextTitle.trim() || null)
          }}
          onBlur={() => {
            // Persist title into job reviews (Continue also sends tables; this
            // covers reload-before-Continue).
            onTitleCommit?.(draft.title.trim() || null)
          }}
        />
      </label>

      {table.description && <p className="text-[13px] text-ink-soft">{table.description}</p>}

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
        label="Columns"
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
              {(table.columns || []).map((c, i) => (
                <tr key={i} className={c.human_review_needed ? 'bg-[#fff8e1]' : ''}>
                  <td className="border border-line px-2.5 py-1.5">{c.name}</td>
                  <td className="border border-line px-2.5 py-1.5">
                    {c.human_review_needed ? (
                      <select className="w-full rounded border border-yellow px-1 py-0.5" value={draft.columns[i].role} onChange={(e) => setColumn(i, 'role', e.target.value)}>
                        {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    ) : c.role}
                  </td>
                  <td className="border border-line px-2.5 py-1.5">
                    {c.human_review_needed ? (
                      <input className="w-full rounded border border-yellow px-1 py-0.5" value={draft.columns[i].concept} onChange={(e) => setColumn(i, 'concept', e.target.value)} />
                    ) : (c.concept ?? '—')}
                  </td>
                  <td className="border border-line px-2.5 py-1.5">
                    {c.human_review_needed ? (
                      <input className="w-full rounded border border-yellow px-1 py-0.5" value={draft.columns[i].description} onChange={(e) => setColumn(i, 'description', e.target.value)} />
                    ) : (c.description ?? '—')}
                  </td>
                  <td className="border border-line px-2.5 py-1.5">{c.data_type}</td>
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

      <div className="text-[11px] font-bold uppercase tracking-wide text-green">
        Extracted data ({previewRows.length} rows
        {anyCellGarbled ? ` — ${garbledCellCount} cell(s) need review` : ''}
        {editableColCount < columnCount ? ' · numeric columns read-only' : ''})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-collapse text-[13px]">
          <ExtractedTableHead columns={table.columns || []} lockedCols={lockedCols} />
          <tbody>
            {visiblePreviewRows.map((row, r) => (
              <tr key={r}>
                {Array.from({ length: columnCount }, (_, c) => {
                  const span = previewCellSpans[r]?.[c]
                  if (span == null) return null
                  const v = row[c] ?? null
                  const col = table.columns?.[c]
                  const merged = span.rowSpan > 1 || span.colSpan > 1
                  return (
                    <td
                      key={c}
                      rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                      colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                      className={`border border-line px-2.5 py-1.5 ${merged ? 'align-middle' : ''}`}
                    >
                      <ExtractedDataCell
                        value={v}
                        sourceValue={sourceRows[r]?.[c]}
                        col={col}
                        locked={lockedCols[c]}
                        onChange={(next) => setCell(r, c, next)}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {hiddenCount > 0 && (
          <div className="mt-2.5 flex justify-center border-t border-line pt-2.5">
            <button
              type="button"
              onClick={() => setRowsModalOpen(true)}
              className="group inline-flex items-center gap-2 rounded-full border border-line bg-white px-3.5 py-1.5 text-[12.5px] font-semibold text-teal shadow-[0_1px_2px_rgba(16,64,63,0.06)] transition-all hover:border-teal hover:bg-sage"
            >
              <span
                className="flex h-5 w-5 items-center justify-center rounded-full bg-sage text-teal"
                aria-hidden
              >
                <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
              </span>
              <span className="inline-flex items-center gap-1.5">
                Show all {previewRows.length} rows
                <span className="rounded-full bg-cream px-2 py-0.5 text-[11px] font-bold text-ink-soft group-hover:bg-white">
                  +{hiddenCount} more
                </span>
              </span>
            </button>
          </div>
        )}
      </div>

      {canSave && (
        <Button variant="primary" className="self-start" onClick={handleSave}>
          {table.human_review_needed ? 'Save review & mark resolved' : 'Save changes'}
        </Button>
      )}
      {saved && (
        <div className="text-[13px] font-semibold text-[#3d7a3d] inline-flex items-center gap-1.5">
          <Check className="h-4 w-4" strokeWidth={2.25} aria-hidden />
          Saved — changes kept for this table.
        </div>
      )}
    </div>
  )
}

export default function PdfReview({ jobId, filename, onDone }) {
  const [tables, setTables] = useState(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [reviewedIds, setReviewedIds] = useState(() => new Set())
  const [statusFilter, setStatusFilter] = useState('all')
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

  const needsReview = tables.filter((t) => t.human_review_needed && !reviewedIds.has(t.table_id))

  const filterCounts = { all: tables.length, needs_review: 0, no_review: 0, reviewed: 0 }
  for (const key of Object.keys(REASON_LABELS)) filterCounts[key] = 0
  for (const t of tables) {
    const reviewed = reviewedIds.has(t.table_id)
    if (reviewed) filterCounts.reviewed += 1
    if (matchesStatusFilter(t, 'needs_review', reviewed)) filterCounts.needs_review += 1
    if (matchesStatusFilter(t, 'no_review', reviewed)) filterCounts.no_review += 1
    for (const reason of collectReviewReasons(t)) {
      if (filterCounts[reason] !== undefined) filterCounts[reason] += 1
    }
  }

  const filterOptions = [
    { id: 'all', label: 'All' },
    ...PRIMARY_FILTERS
      .filter((id) => (filterCounts[id] ?? 0) > 0)
      .map((id) => ({
        id,
        label: id === 'needs_review' ? 'Review needed' : id === 'no_review' ? 'No review needed' : REASON_LABELS[id],
      })),
    ...Object.keys(REASON_LABELS)
      .filter((id) => !PRIMARY_FILTERS.includes(id) && (filterCounts[id] ?? 0) > 0)
      .map((id) => ({ id, label: REASON_LABELS[id] })),
    ...(filterCounts.reviewed > 0 ? [{ id: 'reviewed', label: 'Reviewed' }] : []),
  ]

  // If the active filter no longer has matches (e.g. after deletes), fall back to All.
  const activeFilter = filterOptions.some((o) => o.id === statusFilter) ? statusFilter : 'all'

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
            <span className="font-normal text-ink-soft">
              {' '}· {tables.length} table(s) · {needsReview.length} need review
              {activeFilter !== 'all' ? ` · showing ${filteredTables.length}` : ''}
            </span>
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
            <div className="flex min-w-0 flex-1 flex-wrap gap-2" role="tablist" aria-label="Filter tables by review status">
              {filterOptions.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={activeFilter === id}
                  className={chipClass(activeFilter === id)}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
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
        </div>

        <div className="flex flex-col gap-2 px-5 py-3 sm:px-6 sm:pb-5">
          {filteredTables.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-2 py-10 text-center text-[13px] text-ink-soft">
              {selectMode === 'merge' && selectedIds.size > 0
                ? 'No other tables share these column headers.'
                : 'No tables match this filter.'}
            </div>
          ) : filteredTables.map((t) => {
            const isOpen = expanded === t.table_id
            const reviewed = reviewedIds.has(t.table_id)
            const selected = selectedIds.has(t.table_id)
            return (
              <div key={t.table_id} className={`overflow-hidden rounded-lg border bg-surface ${isOpen ? 'border-teal' : selectMode && selected ? 'border-teal/50' : 'border-line'}`}>
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
                {isOpen && (
                  <TableDetail
                    table={t}
                    onSave={(edits) => saveReview(t.table_id, edits)}
                    onTitleLive={(title) => {
                      setTables((prev) => prev.map((row) => (
                        row.table_id === t.table_id ? { ...row, title } : row
                      )))
                    }}
                    onTitleCommit={(title) => saveReview(t.table_id, { title })}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
    </PdfConsoleLayout>
  )
}
