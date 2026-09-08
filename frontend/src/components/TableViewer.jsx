'use client'

import { useState } from 'react'
import { Check, Download, Info, Loader2, X } from 'lucide-react'
import * as XLSX from 'xlsx'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { withAuthHeaders } from '../lib/auth'


const MAX_DISPLAY = 500

const DATASET_ID_INFO = 'The Dataset ID is generated and is used for grouping and table identification.'

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

  const idInfoIcon = (
    <span className="group relative inline-flex h-4 w-4 flex-shrink-0 cursor-help items-center justify-center rounded-full border border-line bg-[#F4EFE3] text-ink-soft">
      <Info className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
      <span className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-20 w-60 -translate-x-1/2 translate-y-1 rounded-md bg-ink px-2.5 py-2 text-left text-xs font-medium leading-snug text-white opacity-0 shadow-lg transition-all after:absolute after:left-1/2 after:top-full after:-translate-x-1/2 after:border-[5px] after:border-transparent after:border-t-ink group-hover:translate-y-0 group-hover:opacity-100">
        {DATASET_ID_INFO}
      </span>
    </span>
  )

  const editIdControl = editingId ? (
    <>
      <input
        className="min-w-[320px] rounded-md border-[1.5px] border-teal px-2.5 py-[3px] font-mono text-xs font-bold tracking-wide text-ink outline-none"
        value={draftId}
        onChange={(e) => setDraftId(e.target.value)}
        onKeyDown={handleKeyDown}
        autoFocus
        spellCheck={false}
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

  const displayRows = table.rows.slice(0, MAX_DISPLAY)
  const truncated = table.rows.length > MAX_DISPLAY
  return (
    <div className="flex max-h-[calc(100vh-100px)] flex-col gap-4 overflow-hidden">
      {compact ? (
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-[10px] border border-line bg-surface p-3.5 px-[18px]">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded bg-[#e8f2f0] px-2 py-0.5 font-sans text-xs font-bold uppercase tracking-wide text-teal">Table Title</div>
            <div className="min-w-0 flex-1 text-[12.5px] font-semibold leading-tight text-ink">{table.title}</div>
          </div>
          {table.description && <div className="text-[12.5px] leading-relaxed text-ink-soft">{table.description}</div>}
          <div className="whitespace-nowrap font-sans text-xs text-ink-soft">
            Sheet: {table.sheet} · {table.row_count.toLocaleString()} rows · {table.columns.length} columns
          </div>
        </div>
      ) : (
        <div className="flex-shrink-0 rounded-[10px] border border-line bg-surface px-[22px] pb-3.5 pt-4">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <span className="flex-shrink-0 text-[12.5px] font-semibold leading-tight text-ink">{table.id}</span>
            {idInfoIcon}
            {editIdControl}
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded bg-[#e8f2f0] px-2 py-0.5 font-sans text-xs font-bold uppercase tracking-wide text-teal">Table Title</div>
            <div className="min-w-0 flex-1 text-[12.5px] font-semibold leading-tight text-ink">{table.title}</div>
          </div>
          {table.description && <div className="mb-2.5 text-[12.5px] leading-relaxed text-ink-soft">{table.description}</div>}
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-line bg-[#FFFCF6] px-2.5 py-[3px] text-[11.5px] text-ink-soft">Sheet: {table.sheet}</span>
            <span className="rounded-full border border-line bg-[#FFFCF6] px-2.5 py-[3px] text-[11.5px] text-ink-soft">{table.row_count.toLocaleString()} rows</span>
            <span className="rounded-full border border-line bg-[#FFFCF6] px-2.5 py-[3px] text-[11.5px] text-ink-soft">{table.columns.length} columns</span>
            <button className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-teal px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-dark" onClick={() => downloadCSV(table)}>
              <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              Download CSV
            </button>
            <button
              className="ml-2 inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-teal-deep px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#0b2f2e] disabled:cursor-default disabled:opacity-60"
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

      <div className="flex-1 overflow-auto rounded-lg border border-[#cfc6b4] bg-surface">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr>
              {table.columns.map((col) => (
                <th
                  key={col}
                  title={col}
                  className="sticky top-0 z-[2] max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap border-b border-[#d7cdb9] border-r border-line bg-[#F4EFE3] px-3.5 py-[11px] text-left font-sans font-medium tracking-wide text-[#5c6166]"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, i) => (
              <tr key={i} className={`${i % 2 === 0 ? 'bg-[#FFFCF6]' : 'bg-surface'} hover:bg-[#F4EFE3]`}>
                {table.columns.map((col) => {
                  const val = row[col]
                  const isNull = val == null || val === ''
                  return (
                    <td
                      key={col}
                      className={`max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap border-b border-[#f1ebdf] border-r border-[#f4efe3] px-3.5 py-2.5 ${isNull ? 'italic text-[#a49c8e]' : 'text-ink'}`}
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

      {truncated && (
        <div className="flex-shrink-0 rounded-lg border border-[#f5d9a8] bg-[#fef9f0] px-4 py-2 text-center text-xs text-ink-soft">
          Showing first {MAX_DISPLAY.toLocaleString()} of {table.row_count.toLocaleString()} rows — download CSV for full data.
        </div>
      )}

      {compact && (
        <div className="flex flex-wrap items-center gap-2.5 rounded-[10px] border border-line bg-surface px-[18px] py-3.5">
          <span className="inline-flex items-center rounded bg-[#e8f2f0] px-2 py-0.5 font-sans text-xs font-bold uppercase tracking-wide text-teal">Dataset ID</span>
          <span className="flex-shrink-0 text-[12.5px] font-semibold leading-tight text-ink">{table.id}</span>
          {idInfoIcon}
          {editIdControl}
          <div className="ml-auto flex items-center gap-2">
            <button className="inline-flex items-center gap-1.5 rounded-md bg-teal px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-dark" onClick={() => downloadCSV(table)}>
              <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              Download CSV
            </button>
            <button
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-teal-deep px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#0b2f2e] disabled:cursor-default disabled:opacity-60"
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
    </div>
  )
}