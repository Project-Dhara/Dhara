'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { withAuthHeaders } from '../lib/auth'
import { isGarbled } from '../lib/garbled'
import Badge from './ui/Badge'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'

const CLASSIFICATION_LABELS = {
  domain: 'Domain', subject: 'Subject', entity: 'Entity', table_type: 'Table type',
  geography: 'Geography', time_period: 'Time period', frequency: 'Frequency', unit: 'Unit',
}

const REASON_LABELS = {
  garbled_extracted_value: 'Garbled/corrupted value',
  conflicting_extraction: 'Conflicting extraction',
  uncertain_extraction: 'Uncertain extraction',
  uncertain_semantic_role: 'Uncertain column role',
  uncertain_concept: 'Uncertain concept',
  ambiguous_column: 'Ambiguous column',
}

const ROLE_OPTIONS = ['identifier', 'dimension', 'measure', 'attribute', 'unknown']

function ReviewBadge({ needed, reason }) {
  if (!needed) return <Badge tone="ok">No review needed</Badge>
  return <Badge tone="warn">{REASON_LABELS[reason] || 'Needs review'}</Badge>
}

// One table's classification/column fields, editable where flagged for
// human review -- plus, now, individual extracted-data cells that look
// garbled/corrupted (auto-detected, see utils/garbled.js). Everything else
// in the extracted rows stays read-only: human review is about table
// meaning (and fixing genuine extraction corruption), not rewriting data.
function TableDetail({ table, onSave }) {
  const [draft, setDraft] = useState(() => ({
    classification: Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [k, f?.value ?? ''])
    ),
    columns: (table.columns || []).map((c) => ({ role: c.role, concept: c.concept || '', description: c.description || '' })),
    rows: (table.rows || []).map((row) => [...row]),
  }))
  const [saved, setSaved] = useState(false)

  const setField = (key, value) =>
    setDraft((prev) => ({ ...prev, classification: { ...prev.classification, [key]: value } }))
  const setColumn = (idx, key, value) =>
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => (i === idx ? { ...c, [key]: value } : c)),
    }))
  const setCell = (rowIdx, colIdx, value) =>
    setDraft((prev) => ({
      ...prev,
      rows: prev.rows.map((row, r) => (r === rowIdx ? row.map((v, c) => (c === colIdx ? value : v)) : row)),
    }))

  const previewRows = table.rows || []
  const previewLimit = Math.min(5, previewRows.length)
  const anyCellGarbled = previewRows.slice(0, previewLimit).some((row) => row.some((v) => isGarbled(v)))

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

      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Classification</div>
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

      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Columns</div>
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

      {table.uncertain_cells?.length > 0 && (
        <>
          <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Extraction uncertainties</div>
          <ul className="list-disc pl-5 text-[13px] text-ink">
            {table.uncertain_cells.map((note, i) => <li key={i}>{note}</li>)}
          </ul>
        </>
      )}

      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">
        Extracted data ({table.rows?.length || 0} rows{anyCellGarbled ? ` — ${previewRows.slice(0, previewLimit).flat().filter((v) => isGarbled(v)).length} cell(s) need review` : ', read-only'})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-collapse text-[13px]">
          <thead>
            <tr>{(table.columns || []).map((c, i) => <th key={i} className="border border-line bg-outer-bg px-2.5 py-1.5 text-left text-[11.5px] uppercase text-ink-soft">{c.name}</th>)}</tr>
          </thead>
          <tbody>
            {previewRows.slice(0, previewLimit).map((row, r) => (
              <tr key={r}>
                {row.map((v, c) => {
                  const flagged = isGarbled(v)
                  return (
                    <td key={c} className={`border border-line px-2.5 py-1.5 ${flagged ? 'bg-[#fff8e1]' : ''}`}>
                      {flagged ? (
                        <input
                          className="w-full rounded border border-yellow px-1 py-0.5"
                          value={draft.rows[r]?.[c] ?? ''}
                          onChange={(e) => setCell(r, c, e.target.value)}
                        />
                      ) : (v === null ? '' : String(v))}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {previewRows.length > previewLimit && (
          <div className="mt-1 text-xs text-ink-soft">…and {previewRows.length - previewLimit} more row(s)</div>
        )}
      </div>

      {table.human_review_needed && !saved && (
        <Button variant="primary" className="self-start" onClick={handleSave}>Save review &amp; mark resolved</Button>
      )}
      {saved && <div className="text-[13px] font-semibold text-[#3d7a3d]">✓ Reviewed — this table's flags are cleared.</div>}
    </div>
  )
}

export default function PdfReview({ jobId, filename, onDone }) {
  const [tables, setTables] = useState(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [reviewedIds, setReviewedIds] = useState(() => new Set())
  const router = useRouter()

  useEffect(() => {
    let cancelled = false
    fetch(`/api/pdf/jobs/${jobId}/result`, withAuthHeaders())
      .then((res) => {
        if (!res.ok) throw new Error('Could not load results')
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

  if (error) return <ErrorBanner>{error}</ErrorBanner>
  if (!tables) return <div className="py-10 text-center text-ink-soft">Loading results…</div>

  const needsReview = tables.filter((t) => t.human_review_needed && !reviewedIds.has(t.table_id))

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-lg font-bold leading-snug text-ink">{filename}</div>
          <div className="mt-0.5 text-[13px] text-ink-soft">
            {tables.length} table(s) extracted · {needsReview.length} need review
          </div>
        </div>
        <div className="flex flex-none items-center gap-2.5">
          <Button variant="secondary" onClick={onDone}>Upload another PDF</Button>
          <Button variant="primary" onClick={() => router.push(`/console/pdf-next-steps/${jobId}`)}>Continue →</Button>
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-line bg-white p-3 sm:p-4">
        {tables.map((t) => {
          const isOpen = expanded === t.table_id
          const reviewed = reviewedIds.has(t.table_id)
          return (
            <div key={t.table_id} className={`overflow-hidden rounded-lg border bg-surface ${isOpen ? 'border-teal' : 'border-line'}`}>
              <div
                className="flex cursor-pointer items-center justify-between gap-3 px-3.5 py-2.5 hover:bg-cream"
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
              {isOpen && <TableDetail table={t} onSave={(edits) => saveReview(t.table_id, edits)} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
