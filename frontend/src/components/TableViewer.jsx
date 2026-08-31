import { useState } from 'react'
import * as XLSX from 'xlsx'
import { withLlmKeyHeaders } from '../llmKey'
import { withAuthHeaders } from '../auth'


const MAX_DISPLAY = 500

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

  const editIdControl = editingId ? (
    <>
      <input
        className="id-edit-input"
        value={draftId}
        onChange={(e) => setDraftId(e.target.value)}
        onKeyDown={handleKeyDown}
        autoFocus
        spellCheck={false}
      />
      <button className="id-edit-save" onClick={saveEdit} title="Save">✓</button>
      <button className="id-edit-cancel" onClick={cancelEdit} title="Cancel">✕</button>
    </>
  ) : (
    <button className="id-edit-btn" onClick={startEdit} title="Edit dataset ID">Edit ID</button>
  )

  const displayRows = table.rows.slice(0, MAX_DISPLAY)
  const truncated = table.rows.length > MAX_DISPLAY
  return (
    <div className="table-viewer">
      {compact ? (
        <div className="viewer-compact-header">
          <div className="viewer-compact-title">{table.description || table.title}</div>
          <div className="viewer-compact-meta">
            Sheet: {table.sheet} · {table.row_count.toLocaleString()} rows · {table.columns.length} columns
          </div>
          <div className="viewer-compact-actions">
            <button className="btn-csv" onClick={() => downloadCSV(table)}>Download CSV</button>
            <button
              className="btn-meta"
              onClick={() => downloadMetadataExcel(table, setMetaLoading)}
              disabled={metaLoading}
            >
              {metaLoading ? 'Analysing…' : 'Download Classifications'}
            </button>
          </div>
        </div>
      ) : (
        <div className="viewer-header">
          <div className="viewer-title-row">
            <span className="catalogue-id-chip" title="Dataset ID (editable)">{table.id}</span>
            {editIdControl}
          </div>
          {table.description && <div className="viewer-desc">{table.description}</div>}
          <div className="viewer-meta">
            <span className="meta-chip">Sheet: {table.sheet}</span>
            <span className="meta-chip">{table.row_count.toLocaleString()} rows</span>
            <span className="meta-chip">{table.columns.length} columns</span>
            <button className="btn-csv" onClick={() => downloadCSV(table)}>
              ⬇ Download CSV
            </button>
            <button
              className="btn-meta"
              onClick={() => downloadMetadataExcel(table, setMetaLoading)}
              disabled={metaLoading}
            >
              {metaLoading ? '⏳ Analysing…' : '⬇ Download Classifications'}
            </button>
          </div>
        </div>
      )}

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {table.columns.map((col) => (
                <th key={col} title={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, i) => (
              <tr key={i}>
                {table.columns.map((col) => {
                  const val = row[col]
                  const isNull = val == null || val === ''
                  return (
                    <td key={col} className={isNull ? 'null-cell' : ''} title={isNull ? '' : String(val)}>
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
        <div className="row-limit-note">
          Showing first {MAX_DISPLAY.toLocaleString()} of {table.row_count.toLocaleString()} rows — download CSV for full data.
        </div>
      )}

      {compact && (
        <div className="viewer-id-footer">
          <span className="viewer-id-footer-label">Dataset ID</span>
          <span className="catalogue-id-chip" title="Dataset ID (editable)">{table.id}</span>
          {editIdControl}
        </div>
      )}
    </div>
  )
}
