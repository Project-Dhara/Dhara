'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, Download, Info, Loader2, X } from 'lucide-react'
import * as XLSX from 'xlsx'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { withAuthHeaders } from '../lib/auth'
import { headerColumnsFromRawRows } from '../lib/consoleTableEdit'
import { buildMultiLevelHeaderRows, columnHeaderPath } from '../lib/pdfReviewHelpers'


const MAX_DISPLAY = 500
const PREVIEW_ROWS = 5

const DATASET_ID_INFO = 'The Dataset ID is generated and is used for grouping and table identification.'
const TABLE_TITLE_INFO = 'The table title is extracted from the table and can be configured manually.'

function InfoTip({ text, placement = 'top' }) {
  const side = placement === 'right'
  const below = placement === 'bottom'
  return (
    <span className="group relative z-30 inline-flex h-4 w-4 flex-shrink-0 cursor-help items-center justify-center rounded-full border border-line bg-[#F4EFE3] text-ink-soft">
      <Info className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
      <span
        className={[
          'pointer-events-none absolute z-50 w-60 rounded-md bg-ink px-2.5 py-2 text-left text-xs font-medium leading-snug text-white opacity-0 shadow-lg transition-all',
          'after:absolute after:border-[5px] after:border-transparent',
          side
            ? 'left-[calc(100%+8px)] top-1/2 -translate-x-1 -translate-y-1/2 after:right-full after:top-1/2 after:-translate-y-1/2 after:border-r-ink group-hover:translate-x-0 group-hover:opacity-100'
            : below
              ? 'left-1/2 top-[calc(100%+8px)] -translate-x-1/2 -translate-y-1 after:bottom-full after:left-1/2 after:-translate-x-1/2 after:border-b-ink group-hover:translate-y-0 group-hover:opacity-100'
              : 'bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 translate-y-1 after:left-1/2 after:top-full after:-translate-x-1/2 after:border-t-ink group-hover:translate-y-0 group-hover:opacity-100',
        ].join(' ')}
      >
        {text}
      </span>
    </span>
  )
}

const TH_BASE =
  'border border-[#c4b9a3] bg-[#F4EFE3] px-3.5 py-[11px] font-sans font-medium tracking-wide text-[#5c6166]'

const MODAL_TH =
  'border border-[#c4b9a3] bg-[#F4EFE3] px-2 py-1.5 font-sans text-[11px] font-medium leading-tight tracking-wide text-[#5c6166]'

function ExcelTableHead({ columns, rawHeaderRows }) {
  const headerCols = headerColumnsFromRawRows(rawHeaderRows, columns)
  const { depth, rows } = buildMultiLevelHeaderRows(headerCols)

  if (depth <= 1) {
    return (
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col}
              title={col}
              className={`sticky top-0 z-[2] max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap text-left ${TH_BASE}`}
            >
              {col}
            </th>
          ))}
        </tr>
      </thead>
    )
  }

  return (
    <thead>
      {rows.map((segs, r) => (
        <tr key={`hr-${r}`}>
          {segs.map((seg) => {
            const isGroup = !seg.isLeaf
            return (
              <th
                key={seg.key}
                colSpan={seg.colSpan > 1 ? seg.colSpan : undefined}
                rowSpan={seg.rowSpan > 1 ? seg.rowSpan : undefined}
                title={seg.label}
                className={[
                  TH_BASE,
                  'max-w-[220px] align-middle',
                  isGroup || seg.colSpan > 1 ? 'text-center font-semibold' : 'text-left',
                ].filter(Boolean).join(' ')}
              >
                <span className="block max-w-full overflow-hidden text-ellipsis whitespace-nowrap">
                  {seg.label}
                </span>
              </th>
            )
          })}
        </tr>
      ))}
    </thead>
  )
}

/** Modal table head — sticky while scrolling; compact, even columns. */
function ModalExcelTableHead({ columns, rawHeaderRows }) {
  const headerCols = headerColumnsFromRawRows(rawHeaderRows, columns)
  const { depth, rows } = buildMultiLevelHeaderRows(headerCols)
  const rowRefs = useRef([])
  const [stickyTops, setStickyTops] = useState(() => Array.from({ length: Math.max(depth, 1) }, () => 0))
  const headerSig = `${depth}:${headerCols.map((c) => columnHeaderPath(c).join('\u0001')).join('\u0002')}`

  useLayoutEffect(() => {
    const measure = () => {
      const baseEl = rowRefs.current[0]
      if (!baseEl) return
      const base = baseEl.getBoundingClientRect().top
      const tops = rows.map((_, i) => {
        const el = rowRefs.current[i]
        if (!el) return 0
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
  }, [headerSig, rows])

  const stickyReady = depth <= 1 || (
    stickyTops.length >= depth && stickyTops.every((t, i) => i === 0 || t > 0)
  )

  if (depth <= 1) {
    return (
      <thead>
        <tr ref={(el) => { rowRefs.current[0] = el }}>
          {columns.map((col) => (
            <th
              key={col}
              title={col}
              className={`sticky top-0 z-[3] text-left align-middle ${MODAL_TH}`}
            >
              <span className="block whitespace-normal break-words [overflow-wrap:anywhere]">
                {col}
              </span>
            </th>
          ))}
        </tr>
      </thead>
    )
  }

  return (
    <thead>
      {rows.map((segs, r) => (
        <tr key={`hr-${r}`} ref={(el) => { rowRefs.current[r] = el }}>
          {segs.map((seg) => {
            const isGroup = !seg.isLeaf
            return (
              <th
                key={seg.key}
                colSpan={seg.colSpan > 1 ? seg.colSpan : undefined}
                rowSpan={seg.rowSpan > 1 ? seg.rowSpan : undefined}
                title={seg.label}
                className={[
                  MODAL_TH,
                  stickyReady ? 'sticky' : '',
                  'align-middle',
                  isGroup || seg.colSpan > 1 ? 'text-center font-semibold' : 'text-left',
                ].filter(Boolean).join(' ')}
                style={stickyReady ? { top: stickyTops[r] ?? 0, zIndex: 3 + r } : undefined}
              >
                <span className="block whitespace-normal break-words [overflow-wrap:anywhere]">
                  {seg.label}
                </span>
              </th>
            )
          })}
        </tr>
      ))}
    </thead>
  )
}

function TableExpandModal({ table, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  if (typeof document === 'undefined') return null

  const cols = table.columns || []
  const colPct = `${100 / Math.max(cols.length, 1)}%`
  const totalRows = table.row_count ?? table.rows?.length ?? 0

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/40 p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={table.title || 'Table preview'}
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-[min(96vw,1200px)] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-dhara"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-3">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold leading-snug text-ink">{table.title}</div>
            <div className="mt-0.5 text-[12.5px] text-ink-soft">
              {table.sheet ? `Sheet: ${table.sheet} · ` : ''}
              {Number(totalRows).toLocaleString()} rows · {cols.length} columns
            </div>
          </div>
          <button
            type="button"
            className="flex h-8 w-8 flex-none items-center justify-center rounded-md text-ink-soft transition-colors hover:bg-sage hover:text-ink"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 pb-4 pt-3">
          <table className="w-full table-fixed border-collapse text-[11px] leading-tight">
            <colgroup>
              {cols.map((col) => (
                <col key={col} style={{ width: colPct }} />
              ))}
            </colgroup>
            <ModalExcelTableHead columns={cols} rawHeaderRows={table.raw_header_rows} />
            <tbody>
              {(table.rows || []).map((row, i) => (
                <tr key={i} className="bg-white">
                  {cols.map((col) => {
                    const val = row[col]
                    const isNull = val == null || val === ''
                    return (
                      <td
                        key={col}
                        className={`border border-[#c4b9a3] px-2 py-1.5 align-middle ${isNull ? 'italic text-ink-muted' : 'text-ink'}`}
                        title={isNull ? '' : String(val)}
                      >
                        <span className="block whitespace-normal break-words [overflow-wrap:anywhere]">
                          {isNull ? '—' : String(val)}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function escape(v) {
  const s = v == null ? '' : String(v)
  return s.includes(',') || s.includes('"') || s.includes('\n')
    ? `"${s.replace(/"/g, '""')}"`
    : s
}

function downloadCSV(table) {
  const header = table.columns.map(escape).join(',')
  const body = table.rows.map((row) => table.columns.map((c) => escape(row[c])).join(','))
  const blob = new Blob(['﻿' + [header, ...body].join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${table.title.replace(/[/\\?%*:|"<>]/g, '_')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function safeSheetName(name, usedNames) {
  let safe = name.replace(/[/\\?*[\]:]/g, '_').slice(0, 31)
  if (!safe.trim()) safe = 'Sheet'
  if (usedNames.has(safe)) {
    let n = 2
    while (usedNames.has(`${safe.slice(0, 27)}_${n}`)) n++
    safe = `${safe.slice(0, 27)}_${n}`
  }
  usedNames.add(safe)
  return safe
}

function inferType(colName, rows) {
  const vals = rows.map((r) => r[colName]).filter((v) => v != null && v !== '')
  if (!vals.length) return 'Empty'
  const numCount = vals.filter((v) => !isNaN(Number(v)) && String(v).trim() !== '').length
  if (numCount === vals.length) return 'Numeric'
  if (numCount > vals.length / 2) return 'Mixed'
  return 'Text'
}

function numericStats(colName, rows) {
  const nums = rows
    .map((r) => r[colName])
    .filter((v) => v != null && !isNaN(Number(v)) && String(v).trim() !== '')
    .map(Number)
  if (!nums.length) return { min: '', max: '', avg: '', count: 0 }
  const sum = nums.reduce((a, b) => a + b, 0)
  return { min: Math.min(...nums), max: Math.max(...nums), avg: (sum / nums.length).toFixed(2), count: nums.length }
}

async function downloadMetadataExcel(table, setLoading) {
  setLoading(true)
  try {
    const res = await fetch('/api/table-metadata', withAuthHeaders(withLlmKeyHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: table.title,
        description: table.description || '',
        raw_header_rows: table.raw_header_rows || [],
        columns: table.columns,
        sample_rows: table.rows.slice(0, 8),
        raw_notes: table.raw_notes || [],
      }),
    })))
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      throw new Error(err.detail || 'Metadata extraction failed')
    }
    let { categories } = await res.json()

    // Deduplicate categories by name (LLM sometimes returns near-duplicates)
    const seenCatNames = new Set()
    categories = categories.filter((cat) => {
      const key = (cat.name ?? '').toLowerCase().trim()
      if (!key || seenCatNames.has(key)) return false
      seenCatNames.add(key)
      return true
    })

    const wb = XLSX.utils.book_new()
    const usedSheetNames = new Set()

    // ── Overview sheet — two clean sections, consistent columns ─────────────
    const overviewMatrix = [
      ['Table Title',   table.title],
      ['Description',   table.description || ''],
      ['Source File',   table.filename],
      ['Sheet',         table.sheet],
      ['Total Columns', table.columns.length],
      ['Total Rows',    table.row_count],
      ['LLM Categories', categories.length],
      [],
      ['── Column Summary ──'],
      ['#', 'Column Name', 'Data Type', 'Unique / Min', 'Max', 'Avg', 'Non-null Count'],
    ]

    table.columns.forEach((col, i) => {
      const type = inferType(col, table.rows)
      if (type === 'Numeric' || type === 'Mixed') {
        const s = numericStats(col, table.rows)
        overviewMatrix.push([i + 1, col, type, s.min, s.max, s.avg, s.count])
      } else {
        const uniq = new Set(table.rows.map((r) => r[col]).filter((v) => v != null && v !== ''))
        const nonNull = table.rows.filter((r) => r[col] != null && r[col] !== '').length
        overviewMatrix.push([i + 1, col, type, uniq.size, '', '', nonNull])
      }
    })

    if (table.raw_notes?.length) {
      overviewMatrix.push([], ['── Source Notes ──'])
      table.raw_notes.forEach((n) => overviewMatrix.push([n]))
    }

    const wsOv = XLSX.utils.aoa_to_sheet(overviewMatrix)
    wsOv['!cols'] = [{ wch: 26 }, { wch: 42 }, { wch: 12 }, { wch: 14 }, { wch: 10 }, { wch: 10 }, { wch: 16 }]
    XLSX.utils.book_append_sheet(wb, wsOv, safeSheetName('Overview', usedSheetNames))

    // ── One sheet per LLM-identified category ───────────────────────────────
    for (const cat of categories) {
      if (!cat.values?.length) continue

      // Deduplicate values within this category
      const seenVals = new Set()
      const uniqueValues = cat.values.filter((v) => {
        const key = (v.value ?? '').toLowerCase().trim()
        if (!key || seenVals.has(key)) return false
        seenVals.add(key)
        return true
      })

      // Build sheet as a clean array-of-arrays: info block then data table
      const matrix = [
        [cat.name],
        [cat.description || ''],
        [],
        ['Value', 'Code', 'Description'],
        ...uniqueValues.map((v) => [v.value ?? '', v.code ?? '', v.description ?? '']),
      ]

      const ws = XLSX.utils.aoa_to_sheet(matrix)
      ws['!cols'] = [{ wch: 30 }, { wch: 26 }, { wch: 65 }]
      XLSX.utils.book_append_sheet(wb, ws, safeSheetName(cat.name, usedSheetNames))
    }

    const safe = table.title.replace(/[/\\?%*:|"<>[\]]/g, '_').slice(0, 55)
    XLSX.writeFile(wb, `${safe}_metadata.xlsx`)
  } catch (err) {
    alert(`Metadata generation failed: ${err.message}`)
  } finally {
    setLoading(false)
  }
}

export default function TableViewer({ table, onUpdateId, compact = false }) {
  const [metaLoading, setMetaLoading] = useState(false)
  const [editingId, setEditingId] = useState(false)
  const [draftId, setDraftId] = useState('')
  const [modalOpen, setModalOpen] = useState(false)

  useEffect(() => {
    setEditingId(false)
    setDraftId('')
  }, [table?._uid, table?.id])

  const startEdit = () => { setDraftId(table.id); setEditingId(true) }
  const cancelEdit = () => setEditingId(false)
  const saveEdit = () => {
    const trimmed = draftId.trim()
    if (trimmed && trimmed !== table.id) onUpdateId?.(trimmed)
    setEditingId(false)
  }
  const handleKeyDown = (e) => {
    if (e.key === 'Enter') saveEdit()
    if (e.key === 'Escape') cancelEdit()
  }

  const idInfoIcon = <InfoTip text={DATASET_ID_INFO} />
  const titleInfoIcon = <InfoTip text={TABLE_TITLE_INFO} placement="right" />

  const editIdControl = editingId ? (
    <>
      <input
        className="min-w-0 flex-1 rounded-md border-[1.5px] border-teal bg-white px-2.5 py-1 font-mono text-[13px] font-bold tracking-wide text-ink outline-none sm:min-w-[280px]"
        value={draftId}
        onChange={(e) => setDraftId(e.target.value)}
        onKeyDown={handleKeyDown}
        autoFocus
        spellCheck={false}
        aria-label="Dataset ID"
      />
      <button className="rounded bg-teal px-2 py-[3px] text-[13px] font-bold text-white transition-colors hover:bg-teal-dark" onClick={saveEdit} title="Save" aria-label="Save">
        <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
      </button>
      <button className="rounded border border-line px-2 py-[3px] text-[13px] text-ink-soft transition-colors hover:bg-[#F4EFE3] hover:text-ink" onClick={cancelEdit} title="Cancel" aria-label="Cancel">
        <X className="h-3.5 w-3.5" strokeWidth={2} />
      </button>
    </>
  ) : (
    <button className="flex-shrink-0 whitespace-nowrap rounded border border-line bg-white px-2.5 py-[3px] text-[11px] font-semibold text-teal transition-colors hover:bg-[#F4EFE3] hover:border-teal" onClick={startEdit} title="Edit dataset ID">Edit ID</button>
  )

  const totalRows = table.row_count ?? table.rows?.length ?? 0
  const rowLimit = compact ? PREVIEW_ROWS : MAX_DISPLAY
  const displayRows = table.rows.slice(0, rowLimit)
  const hasMore = totalRows > rowLimit

  return (
    <div className={`flex flex-col ${compact ? 'gap-5 overflow-visible' : 'max-h-[calc(100vh-100px)] gap-4 overflow-hidden'}`}>
      {compact ? (
        <div className="flex flex-col gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Table title</div>
              {titleInfoIcon}
            </div>
            <div className="mt-1 text-[15px] font-semibold leading-snug text-ink">{table.title}</div>
            {table.description && (
              <div className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-ink-soft">{table.description}</div>
            )}
          </div>
          <div className="text-[12.5px] text-ink-soft">
            {table.sheet ? `Sheet: ${table.sheet} · ` : ''}
            {Number(totalRows).toLocaleString()} rows · {table.columns.length} columns
          </div>
        </div>
      ) : (
        <div className="flex-shrink-0 rounded-[10px] border border-line bg-surface px-[22px] pb-3.5 pt-4">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            {editingId ? editIdControl : (
              <>
                <span className="flex-shrink-0 text-[12.5px] font-semibold leading-tight text-ink">{table.id}</span>
                {idInfoIcon}
                {editIdControl}
              </>
            )}
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded bg-[#e8f2f0] px-2 py-0.5 font-sans text-xs font-bold uppercase tracking-wide text-teal">Table Title</div>
            <div className="min-w-0 flex-1 text-[12.5px] font-semibold leading-tight text-ink">{table.title}</div>
          </div>
          {table.description && <div className="mb-2.5 text-[12.5px] leading-relaxed text-ink-soft">{table.description}</div>}
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-line bg-[#FFFCF6] px-2.5 py-[3px] text-[11.5px] text-ink-soft">Sheet: {table.sheet}</span>
            <span className="rounded-full border border-line bg-[#FFFCF6] px-2.5 py-[3px] text-[11.5px] text-ink-soft">{Number(totalRows).toLocaleString()} rows</span>
            <span className="rounded-full border border-line bg-[#FFFCF6] px-2.5 py-[3px] text-[11.5px] text-ink-soft">{table.columns.length} columns</span>
            <button className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-teal px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-dark" onClick={() => downloadCSV(table)}>
              <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              Download CSV
            </button>
            <button
              className="ml-2 inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-teal px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:opacity-60"
              onClick={() => downloadMetadataExcel(table, setMetaLoading)}
              disabled={metaLoading}
            >
              {metaLoading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
                  Analysing…
                </>
              ) : (
                <>
                  <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                  Download Classifications
                </>
              )}
            </button>
          </div>
        </div>
      )}

      <div className="flex min-h-0 flex-col gap-2.5">
        <div className="overflow-auto rounded-lg border border-[#cfc6b4] bg-surface">
          <table className="w-full border-collapse text-[12.5px]">
            <ExcelTableHead columns={table.columns} rawHeaderRows={table.raw_header_rows} />
            <tbody>
              {displayRows.map((row, i) => (
                <tr key={i} className="bg-white hover:bg-[#FDFCF9]">
                  {table.columns.map((col) => {
                    const val = row[col]
                    const isNull = val == null || val === ''
                    return (
                      <td
                        key={col}
                        className={`max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap border border-[#c4b9a3] px-3.5 py-2.5 ${isNull ? 'italic text-ink-muted' : 'text-ink'}`}
                        title={isNull ? '' : String(val)}
                      >
                        {isNull ? '—' : String(val)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {compact && hasMore && (
          <div className="flex flex-shrink-0 justify-center">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-3.5 py-1.5 text-[12px] font-semibold text-teal transition-colors hover:border-teal hover:bg-sage"
              onClick={() => setModalOpen(true)}
            >
              Show more
              <span className="font-medium text-ink-soft">
                ({PREVIEW_ROWS} of {Number(totalRows).toLocaleString()} rows)
              </span>
            </button>
          </div>
        )}
      </div>

      {!compact && hasMore && (
        <div className="flex-shrink-0 rounded-lg border border-[#f5d9a8] bg-[#fef9f0] px-4 py-2 text-center text-xs text-ink-soft">
          Showing first {MAX_DISPLAY.toLocaleString()} of {Number(totalRows).toLocaleString()} rows — download CSV for full data.
        </div>
      )}

      {compact && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-4">
          <span className="inline-flex items-center rounded bg-[#e8f2f0] px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-teal">
            Dataset ID
          </span>
          {editingId ? (
            editIdControl
          ) : (
            <>
              <span className="flex-shrink-0 font-mono text-[14px] font-bold tracking-wide text-ink">{table.id}</span>
              {idInfoIcon}
              {editIdControl}
            </>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button className="inline-flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-1.5 text-[12.5px] font-semibold text-ink transition-colors hover:bg-sage" onClick={() => downloadCSV(table)}>
              <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              Download CSV
            </button>
            <button
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-teal px-3 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:opacity-60"
              onClick={() => downloadMetadataExcel(table, setMetaLoading)}
              disabled={metaLoading}
            >
              {metaLoading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
                  Analysing…
                </>
              ) : (
                <>
                  <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                  Download Classifications
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {modalOpen && (
        <TableExpandModal table={table} onClose={() => setModalOpen(false)} />
      )}
    </div>
  )
}