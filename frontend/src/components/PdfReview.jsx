import { useEffect, useState } from 'react'
import { withAuthHeaders } from '../auth'

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
  if (!needed) return <span className="pdf-badge pdf-badge-ok">No review needed</span>
  return <span className="pdf-badge pdf-badge-warn">{REASON_LABELS[reason] || 'Needs review'}</span>
}

// One table's classification/column fields, editable where flagged for
// human review. Only classification/column metadata is ever edited here --
// the extracted rows themselves are shown read-only and untouched, per the
// "human review is about table meaning, not rewriting source data" contract.
function TableDetail({ table, onSave }) {
  const [draft, setDraft] = useState(() => ({
    classification: Object.fromEntries(
      Object.entries(table.classification || {}).map(([k, f]) => [k, f?.value ?? ''])
    ),
    columns: (table.columns || []).map((c) => ({ role: c.role, concept: c.concept || '', description: c.description || '' })),
  }))
  const [saved, setSaved] = useState(false)

  const setField = (key, value) =>
    setDraft((prev) => ({ ...prev, classification: { ...prev.classification, [key]: value } }))
  const setColumn = (idx, key, value) =>
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => (i === idx ? { ...c, [key]: value } : c)),
    }))

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
    onSave({ classification, columns, human_review_needed: false, human_review_reason: null })
    setSaved(true)
  }

  return (
    <div className="pdf-table-detail">
      {table.description && <p className="pdf-table-description">{table.description}</p>}

      <div className="pdf-detail-section-label">Classification</div>
      <div className="pdf-classification-grid">
        {Object.entries(CLASSIFICATION_LABELS).map(([key, label]) => {
          const field = table.classification?.[key] || {}
          return (
            <div key={key} className={`pdf-field${field.human_review_needed ? ' pdf-field-flagged' : ''}`}>
              <div className="pdf-field-label">{label}</div>
              {field.human_review_needed ? (
                <input
                  className="pdf-field-input"
                  value={draft.classification[key] ?? ''}
                  onChange={(e) => setField(key, e.target.value)}
                />
              ) : (
                <div className="pdf-field-value">{field.value ?? <em className="pdf-field-empty">—</em>}</div>
              )}
              {field.human_review_needed && <ReviewBadge needed reason={field.human_review_reason} />}
            </div>
          )
        })}
      </div>

      <div className="pdf-detail-section-label">Columns</div>
      <div className="pdf-columns-table-wrap">
        <table className="pdf-columns-table">
          <thead>
            <tr>
              <th>Name</th><th>Role</th><th>Concept</th><th>Description</th><th>Data type</th><th>Review</th>
            </tr>
          </thead>
          <tbody>
            {(table.columns || []).map((c, i) => (
              <tr key={i} className={c.human_review_needed ? 'pdf-column-flagged' : ''}>
                <td>{c.name}</td>
                <td>
                  {c.human_review_needed ? (
                    <select value={draft.columns[i].role} onChange={(e) => setColumn(i, 'role', e.target.value)}>
                      {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  ) : c.role}
                </td>
                <td>
                  {c.human_review_needed ? (
                    <input value={draft.columns[i].concept} onChange={(e) => setColumn(i, 'concept', e.target.value)} />
                  ) : (c.concept ?? '—')}
                </td>
                <td>
                  {c.human_review_needed ? (
                    <input value={draft.columns[i].description} onChange={(e) => setColumn(i, 'description', e.target.value)} />
                  ) : (c.description ?? '—')}
                </td>
                <td>{c.data_type}</td>
                <td>{c.human_review_needed ? <ReviewBadge needed reason={c.human_review_reason} /> : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {table.uncertain_cells?.length > 0 && (
        <>
          <div className="pdf-detail-section-label">Extraction uncertainties</div>
          <ul className="pdf-uncertain-list">
            {table.uncertain_cells.map((note, i) => <li key={i}>{note}</li>)}
          </ul>
        </>
      )}

      <div className="pdf-detail-section-label">Extracted data ({table.rows?.length || 0} rows, read-only)</div>
      <div className="pdf-rows-preview-wrap">
        <table className="pdf-rows-preview">
          <thead><tr>{(table.columns || []).map((c, i) => <th key={i}>{c.name}</th>)}</tr></thead>
          <tbody>
            {(table.rows || []).slice(0, 5).map((row, i) => (
              <tr key={i}>{row.map((v, j) => <td key={j}>{v === null ? '' : String(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {table.rows?.length > 5 && <div className="pdf-rows-more">…and {table.rows.length - 5} more row(s)</div>}
      </div>

      {table.human_review_needed && !saved && (
        <button className="console-primary-btn" onClick={handleSave}>Save review & mark resolved</button>
      )}
      {saved && <div className="pdf-reviewed-hint">✓ Reviewed — this table's flags are cleared.</div>}
    </div>
  )
}

export default function PdfReview({ jobId, filename, onDone }) {
  const [tables, setTables] = useState(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [reviewedIds, setReviewedIds] = useState(() => new Set())

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

  if (error) return <div className="error-banner"><strong>Error:</strong> {error}</div>
  if (!tables) return <div className="pdf-review-loading">Loading results…</div>

  const needsReview = tables.filter((t) => t.human_review_needed && !reviewedIds.has(t.table_id))

  return (
    <div className="pdf-review">
      <div className="pdf-review-header">
        <div>
          <div className="pdf-review-title">{filename}</div>
          <div className="pdf-review-subtitle">
            {tables.length} table(s) extracted · {needsReview.length} need review
          </div>
        </div>
        <button className="console-secondary-btn" onClick={onDone}>Upload another PDF</button>
      </div>

      <div className="pdf-review-list">
        {tables.map((t) => {
          const isOpen = expanded === t.table_id
          const reviewed = reviewedIds.has(t.table_id)
          return (
            <div key={t.table_id} className={`pdf-review-card${isOpen ? ' pdf-review-card-open' : ''}`}>
              <div className="pdf-review-card-head" onClick={() => setExpanded(isOpen ? null : t.table_id)}>
                <div className="pdf-review-card-titles">
                  <div className="pdf-review-card-title">{t.title || `Page ${t.page} table`}</div>
                  <div className="pdf-review-card-meta">
                    Page {t.page} · {t.semantic_status === 'classified' ? 'AI-classified' : 'Auto-accepted (no AI review)'}
                  </div>
                </div>
                {reviewed ? (
                  <span className="pdf-badge pdf-badge-ok">✓ Reviewed</span>
                ) : (
                  <ReviewBadge needed={t.human_review_needed} reason={t.human_review_reason} />
                )}
              </div>
              {isOpen && <TableDetail table={t} onSave={(edits) => saveReview(t.table_id, edits)} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
