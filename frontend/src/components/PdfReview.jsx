'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { withAuthHeaders } from '../lib/auth'
import { isGarbled } from '../lib/garbled'
import Badge from './ui/Badge'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'
import PdfConsoleLayout from './PdfConsoleLayout'

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
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
        <path d="M9 3.5v11M9 3.5 4.5 8M9 3.5 13.5 8" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
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
  return (
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
    </div>
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
          className={`flex h-5 w-5 flex-none items-center justify-center rounded-full border border-line bg-white text-[10px] text-ink-soft transition-all duration-300 ease-out group-hover:border-teal group-hover:text-teal ${open ? 'rotate-180 bg-sage/40' : 'rotate-0'}`}
          aria-hidden
        >
          ▾
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

// One table's classification/column fields, editable where flagged for
// human review -- plus extracted-data cells for non-numeric columns
// (garbled/corrupted values stay highlighted). Numeric columns
// (integer / decimal / percentage) stay read-only.
function TableDetail({ table, onSave }) {
  const classificationNeedsReview = Object.values(table.classification || {}).some((f) => f?.human_review_needed)
  const columnsNeedReview = (table.columns || []).some((c) => c.human_review_needed)
  const columnCount = (table.columns || []).length

  const [draft, setDraft] = useState(() => ({
    classification: Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [k, f?.value ?? ''])
    ),
    columns: (table.columns || []).map((c) => ({ role: c.role, concept: c.concept || '', description: c.description || '' })),
    rows: padRowsToColumns(table.rows || [], columnCount),
  }))
  const [saved, setSaved] = useState(false)
  const [showAllRows, setShowAllRows] = useState(false)
  const [classificationOpen, setClassificationOpen] = useState(classificationNeedsReview)
  const [columnsOpen, setColumnsOpen] = useState(columnsNeedReview)

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
  const previewLimit = showAllRows ? previewRows.length : Math.min(previewCap, previewRows.length)
  const hiddenCount = Math.max(0, previewRows.length - previewCap)
  const garbledCellCount = sourceRows.flat().filter((v) => isGarbled(v)).length
  const anyCellGarbled = garbledCellCount > 0
  const lockedCols = (table.columns || []).map((col, i) => isNumericColumn(col, i, sourceRows))
  const editableColCount = lockedCols.filter((locked) => !locked).length
  const rowsDirty = JSON.stringify(draft.rows) !== JSON.stringify(sourceRows)
  const canSave = (table.human_review_needed || rowsDirty) && !saved

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
    onSave({ classification, columns, rows: draft.rows, human_review_needed: false, human_review_reason: null })
    setSaved(true)
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line px-3.5 pb-3.5 pt-3">
      {table.description && <p className="text-[13px] text-ink-soft">{table.description}</p>}

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
                  <th key={h} className="border border-line bg-outer-bg px-2.5 py-1.5 text-left text-[11.5px] uppercase text-ink-soft">{h}</th>
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

      {table.uncertain_cells?.length > 0 && (
        <>
          <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Extraction uncertainties</div>
          <ul className="list-disc pl-5 text-[13px] text-ink">
            {table.uncertain_cells.map((note, i) => <li key={i}>{note}</li>)}
          </ul>
        </>
      )}

      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">
        Extracted data ({previewRows.length} rows
        {anyCellGarbled ? ` — ${garbledCellCount} cell(s) need review` : ''}
        {editableColCount < columnCount ? ' · numeric columns read-only' : ''})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-collapse text-[13px]">
          <thead>
            <tr>
              {(table.columns || []).map((c, i) => (
                <th
                  key={i}
                  className="border border-line bg-outer-bg px-2.5 py-1.5 text-left text-[11.5px] uppercase text-ink-soft"
                  title={lockedCols[i] ? 'Numeric column — read-only' : 'Editable'}
                >
                  {c.name}
                  {lockedCols[i] ? <span className="ml-1 font-semibold normal-case tracking-normal text-ink-soft/70">· locked</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {previewRows.slice(0, previewLimit).map((row, r) => (
              <tr key={r}>
                {Array.from({ length: columnCount }, (_, c) => {
                  const v = row[c] ?? null
                  const col = table.columns?.[c]
                  const flagged = isGarbled(sourceRows[r]?.[c]) || (v == null && col?.input_type === 'dropdown')
                  const editable = !lockedCols[c]
                  const dropdownOptions =
                    editable && col?.input_type === 'dropdown' && Array.isArray(col.input_options) && col.input_options.length > 0
                      ? col.input_options
                      : null
                  return (
                    <td key={c} className={`border border-line px-2.5 py-1.5 ${flagged ? 'bg-[#fff8e1]' : ''}`}>
                      {editable && dropdownOptions ? (
                        <select
                          className={`w-full rounded px-1 py-0.5 ${flagged ? 'border border-yellow' : 'border border-transparent hover:border-line focus:border-teal'}`}
                          value={v ?? ''}
                          onChange={(e) => setCell(r, c, e.target.value || null)}
                        >
                          <option value="">—</option>
                          {dropdownOptions.map((opt) => (
                            <option key={opt} value={opt}>{opt}</option>
                          ))}
                        </select>
                      ) : editable ? (
                        <input
                          className={`w-full rounded px-1 py-0.5 ${flagged ? 'border border-yellow' : 'border border-transparent hover:border-line focus:border-teal'}`}
                          value={v ?? ''}
                          onChange={(e) => setCell(r, c, e.target.value)}
                        />
                      ) : (v === null || v === undefined ? '' : String(v))}
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
              onClick={() => setShowAllRows((v) => !v)}
              className="group inline-flex items-center gap-2 rounded-full border border-line bg-white px-3.5 py-1.5 text-[12.5px] font-semibold text-teal shadow-[0_1px_2px_rgba(16,64,63,0.06)] transition-all hover:border-teal hover:bg-sage"
            >
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full bg-sage text-[10px] text-teal transition-transform duration-300 ease-out ${showAllRows ? 'rotate-180' : 'rotate-0'}`}
                aria-hidden
              >
                ▾
              </span>
              {showAllRows ? (
                <span>Show fewer rows</span>
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  Show all {previewRows.length} rows
                  <span className="rounded-full bg-cream px-2 py-0.5 text-[11px] font-bold text-ink-soft group-hover:bg-white">
                    +{hiddenCount} more
                  </span>
                </span>
              )}
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
        <div className="text-[13px] font-semibold text-[#3d7a3d]">
          ✓ Saved — changes kept for this table.
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
  const [selectMode, setSelectMode] = useState(false)
  const [pendingDeleteIds, setPendingDeleteIds] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const rootRef = useRef(null)
  const router = useRouter()

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
      setSelectMode(false)
    } catch (e) {
      setError(e.message || 'Could not delete tables')
      setPendingDeleteIds(null)
    } finally {
      setDeleting(false)
    }
  }

  const exitSelectMode = () => {
    setSelectMode(false)
    setSelectedIds(new Set())
  }

  if (error && !tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={2}>
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <button
              type="button"
              className="mb-3.5 self-start text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={onDone}
            >
              ← Upload another PDF
            </button>
            <div className="font-display text-[32px] font-medium leading-tight text-ink">Review Extracted Tables</div>
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
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={2}>
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <div className="font-display text-[32px] font-medium leading-tight text-ink">Review Extracted Tables</div>
            <div className="mt-1 text-[15px] text-ink-soft">Loading results…</div>
          </div>
          <div className="rounded-xl border border-line bg-white p-5 py-10 text-center text-ink-soft shadow-sm sm:p-6">
            Loading results…
          </div>
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

  const filteredTables = tables.filter((t) =>
    matchesStatusFilter(t, activeFilter, reviewedIds.has(t.table_id))
  )
  const filteredIds = filteredTables.map((t) => t.table_id)
  const allFilteredSelected = filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const selectedCount = selectedIds.size

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
    `flex h-8 flex-none items-center gap-1.5 rounded-full border px-3.5 text-[12.5px] font-semibold transition-colors ${
      active ? 'border-teal bg-sage text-ink' : 'border-line bg-white text-ink-soft hover:border-teal hover:text-ink'
    }`

  return (
    <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={2}>
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

      {/* Page header — title / purpose stay above the content panel */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            className="mb-3.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
            onClick={onDone}
          >
            ← Upload another PDF
          </button>
          <div className="font-display text-[32px] font-medium leading-tight text-ink">Review Extracted Tables</div>
          <div className="mt-1 text-[15px] text-ink-soft">
            Check classification, fix uncertain cells, and remove tables you don’t want to keep.
          </div>
          <div className="mt-1.5 text-[13px] font-medium text-ink">
            {filename || 'PDF report'}
            <span className="font-normal text-ink-soft">
              {' '}· {tables.length} table(s) · {needsReview.length} need review
              {activeFilter !== 'all' ? ` · showing ${filteredTables.length}` : ''}
            </span>
          </div>
        </div>
        <div className="flex flex-none items-center gap-2.5">
          <Button variant="primary" onClick={() => router.push(`/console/pdf-next-steps/${jobId}`)}>Continue →</Button>
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
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold ${activeFilter === id ? 'bg-teal/15 text-teal' : 'bg-cream text-ink-soft'}`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
            {!selectMode ? (
              <Button
                variant="secondary"
                size="sm"
                className="ml-auto flex-none !border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                disabled={tables.length === 0}
                onClick={() => setSelectMode(true)}
              >
                Delete
              </Button>
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
                Select all{activeFilter !== 'all' ? ' shown' : ''}
              </label>
              <span className="text-[12.5px] text-ink-soft">
                {selectedCount === 0 ? 'None selected' : `${selectedCount} selected`}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <Button variant="secondary" size="sm" onClick={exitSelectMode}>Cancel</Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="!border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                  disabled={selectedCount === 0}
                  onClick={() => setPendingDeleteIds([...selectedIds])}
                >
                  Delete selected
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2 px-5 py-3 sm:px-6 sm:pb-5">
          {filteredTables.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-2 py-10 text-center text-[13px] text-ink-soft">
              No tables match this filter.
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
                      aria-label={`Select ${t.title || `page ${t.page} table`}`}
                      onChange={() => toggleSelected(t.table_id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  )}
                  <div
                    className="flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-3"
                    onClick={() => setExpanded(isOpen ? null : t.table_id)}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[14px] font-semibold leading-snug text-ink">{t.title || `Page ${t.page} table`}</div>
                      <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                        Page {t.page} · {t.semantic_status === 'classified' ? 'AI-classified' : 'Auto-accepted (no AI review)'}
                      </div>
                    </div>
                    {reviewed ? <Badge tone="ok">✓ Reviewed</Badge> : <ReviewBadge needed={t.human_review_needed} reason={t.human_review_reason} />}
                  </div>
                </div>
                {isOpen && <TableDetail table={t} onSave={(edits) => saveReview(t.table_id, edits)} />}
              </div>
            )
          })}
        </div>
      </div>
    </div>
    </PdfConsoleLayout>
  )
}
