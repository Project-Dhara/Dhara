import { useState } from 'react'

function ValidatorResult({ label, result }) {
  if (!result) return null
  const { valid, issues = [] } = result
  const status = valid === true ? 'ok' : valid === false ? 'bad' : 'unknown'
  const statusText = valid === true ? 'Valid' : valid === false ? 'Invalid' : 'Skipped'
  return (
    <div className="reconcile-validator">
      <span className={`reconcile-validator-label reconcile-validator-${status}`}>{label}: {statusText}</span>
      {issues.length > 0 && (
        <ul className="reconcile-issues">
          {issues.map((issue, i) => <li key={i}>{issue}</li>)}
        </ul>
      )}
    </div>
  )
}

// Stage 2.5 — Reconcile Table ID / Title mismatches (see backend/dhara_dry_run.ipynb).
// A table lands here when the code-based and prompt-based validators disagree
// on whether its extracted `table_id` / `title` fields are correct, so a
// human needs to confirm or correct them before Stage 3's title-based
// grouping runs on possibly-wrong values.
export default function ReconcileIds({ tables, onContinue }) {
  const mismatched = tables.filter((t) => t.id_title_mismatch)

  const [drafts, setDrafts] = useState(() =>
    Object.fromEntries(
      mismatched.map((t) => [t.id, { table_id: t.table_id || '', title: t.title || '' }])
    )
  )

  const updateDraft = (id, field, value) => {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], [field]: value } }))
  }

  const handleContinue = () => {
    const corrections = {}
    mismatched.forEach((t) => {
      const draft = drafts[t.id] || {}
      // Blank input keeps the existing extracted value, same as the
      // notebook's reconciliation loop.
      corrections[t.id] = {
        table_id: draft.table_id?.trim() || t.table_id,
        title: draft.title?.trim() || t.title,
      }
    })
    onContinue(corrections)
  }

  if (mismatched.length === 0) {
    return (
      <div className="console-grouping-step">
        <div className="reconcile-clean">✓ No Table ID / Title mismatches found — all extracted tables look consistent.</div>
        <div className="console-step-actions">
          <button className="console-primary-btn" onClick={() => onContinue({})}>Continue →</button>
        </div>
      </div>
    )
  }

  return (
    <div className="console-grouping-step">
      <div className="reconcile-hint">
        {mismatched.length} table{mismatched.length !== 1 ? 's' : ''} had disagreeing code-based and prompt-based
        validation of the Table ID / Table Title fields. Confirm or correct them below before grouping.
      </div>

      <div className="reconcile-list">
        {mismatched.map((t) => (
          <div className="reconcile-card" key={t.id}>
            <div className="reconcile-card-head">{t.id}</div>

            <div className="reconcile-validators">
              <ValidatorResult label="Code-based" result={t.id_validation?.code} />
              <ValidatorResult label="Prompt-based" result={t.id_validation?.llm} />
            </div>

            <div className="reconcile-fields">
              <label className="reconcile-field">
                <span>Table ID</span>
                <input
                  value={drafts[t.id]?.table_id ?? ''}
                  onChange={(e) => updateDraft(t.id, 'table_id', e.target.value)}
                  spellCheck={false}
                />
              </label>
              <label className="reconcile-field">
                <span>Table Title</span>
                <input
                  value={drafts[t.id]?.title ?? ''}
                  onChange={(e) => updateDraft(t.id, 'title', e.target.value)}
                  spellCheck={false}
                />
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="console-step-actions">
        <button className="console-primary-btn" onClick={handleContinue}>Apply corrections & continue →</button>
      </div>
    </div>
  )
}
