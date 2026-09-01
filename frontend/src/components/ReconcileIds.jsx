import { useState } from 'react'

// Stage 2.5 — Reconcile Table ID / Title mismatches (see backend/dhara_dry_run.ipynb).
// A table lands here when the code-based and prompt-based validators disagree
// on whether its extracted `table_id` / `title` fields are correct, so a
// human needs to confirm or correct them before Stage 3's title-based
// grouping runs on possibly-wrong values. The same edit card is offered for
// every table (not just flagged ones) so the user is always free to correct
// a Table ID / Title that validation missed — only flagged tables are
// required to be saved before continuing.
export default function ReconcileIds({ tables, onContinue, extraAction, visibleId, onNavigate, onSave }) {
  const mismatched = tables.filter((t) => t.id_title_mismatch)
  const visible = tables.filter((t) => t.id === visibleId)

  const [drafts, setDrafts] = useState(() =>
    Object.fromEntries(
      tables.map((t) => [t.id, { table_id: t.table_id || '', title: t.title || '' }])
    )
  )
  // The values as they stood the last time "Save details" was clicked for
  // that table — compared against the live draft to decide whether the
  // save button should reappear (edited again since saving).
  const [savedSnapshots, setSavedSnapshots] = useState({})
  const [savedIds, setSavedIds] = useState(() => new Set())
  // Fields lock (read-only) right after a save, so the user has to
  // deliberately click "Edit" to change a table's details again. Tables
  // that passed validation start locked too — the user must click "Edit"
  // before those fields (and the Save button) become usable, whereas a
  // flagged table starts unlocked since it needs correcting right away.
  const [lockedIds, setLockedIds] = useState(() => new Set(tables.filter((t) => !t.id_title_mismatch).map((t) => t.id)))

  const updateDraft = (id, field, value) => {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], [field]: value } }))
  }

  const isDirty = (t) => {
    const draft = drafts[t.id] || {}
    const snapshot = savedSnapshots[t.id]
    const base = snapshot || { table_id: t.table_id || '', title: t.title || '' }
    return draft.table_id !== base.table_id || draft.title !== base.title
  }

  const isSaved = (t) => savedIds.has(t.id) && !isDirty(t)

  const saveDetails = (id) => {
    const t = tables.find((m) => m.id === id)
    const draft = drafts[id] || {}
    // Blank input keeps the existing extracted value, same as the
    // notebook's reconciliation loop.
    const correction = {
      table_id: draft.table_id?.trim() || t.table_id,
      title: draft.title?.trim() || t.title,
    }
    setSavedSnapshots((prev) => ({ ...prev, [id]: { ...drafts[id] } }))
    const newSaved = new Set(savedIds).add(id)
    setSavedIds(newSaved)
    setLockedIds((prev) => new Set(prev).add(id))
    onSave?.(id, correction)

    // Jump to the next flagged table that still needs saving, so the user
    // works through every mismatch instead of having to hunt for the next one.
    const idx = mismatched.findIndex((m) => m.id === id)
    if (idx !== -1) {
      const after = mismatched.slice(idx + 1).find((m) => !newSaved.has(m.id))
      const before = mismatched.slice(0, idx).find((m) => !newSaved.has(m.id))
      const next = after || before
      if (next) onNavigate?.(next.id)
    }
  }

  const editDetails = (id) => {
    setLockedIds((prev) => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  const handleContinue = () => {
    const corrections = {}
    tables.forEach((t) => {
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

  const allCorrected = mismatched.every((t) => isSaved(t))

  return (
    <div className="console-grouping-step">
      <div className="reconcile-title">Confirm Table Details</div>
      {mismatched.length > 0 ? (
        <div className="reconcile-hint">
          {mismatched.length} table{mismatched.length !== 1 ? 's' : ''} had disagreeing code-based and prompt-based
          validation of the Table ID / Table Title fields. Click a flagged table above to confirm or correct it before grouping.
          Any other table can be edited here too, if needed.
        </div>
      ) : (
        <div className="reconcile-clean">✓ No Table ID / Title mismatches found — all extracted tables look consistent. You can still edit a table's details below if needed.</div>
      )}

      <div className="reconcile-list">
        {visible.map((t) => {
          const locked = lockedIds.has(t.id)
          return (
            <div className={`reconcile-card${t.id_title_mismatch && !isSaved(t) ? ' reconcile-card-unedited' : ''}`} key={t.id}>
              <div className="reconcile-card-head">{t.id}</div>

              <div className="reconcile-fields">
                <label className="reconcile-field">
                  <span>Table ID</span>
                  <input
                    value={drafts[t.id]?.table_id ?? ''}
                    onChange={(e) => updateDraft(t.id, 'table_id', e.target.value)}
                    readOnly={locked}
                    spellCheck={false}
                  />
                </label>
                <label className="reconcile-field">
                  <span>Table Title</span>
                  <input
                    value={drafts[t.id]?.title ?? ''}
                    onChange={(e) => updateDraft(t.id, 'title', e.target.value)}
                    readOnly={locked}
                    spellCheck={false}
                  />
                </label>
              </div>

              <div className="reconcile-card-actions">
                <button
                  className="console-secondary-btn reconcile-save-btn"
                  onClick={() => saveDetails(t.id)}
                  disabled={locked}
                >
                  Save details
                </button>
                <button
                  className="console-secondary-btn reconcile-edit-btn"
                  onClick={() => editDetails(t.id)}
                  disabled={!locked}
                >
                  Edit
                </button>
                {isSaved(t) && <span className="reconcile-saved-hint">✓ Saved</span>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="console-step-actions">
        {allCorrected && (
          <button className="console-primary-btn" onClick={handleContinue}>
            {mismatched.length > 0 ? 'Apply corrections & continue →' : 'Continue →'}
          </button>
        )}
        {extraAction}
      </div>
      {!allCorrected && (
        <div className="reconcile-blocked-hint">
          Correct and save all {mismatched.length} flagged table{mismatched.length !== 1 ? 's' : ''} above
          ({mismatched.length - mismatched.filter((t) => isSaved(t)).length} remaining) before continuing.
        </div>
      )}
    </div>
  )
}
