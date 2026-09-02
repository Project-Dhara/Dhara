import { useState } from 'react'

// Stage 2.5 — Reconcile Source Table ID / Title mismatches (see backend/dhara_dry_run.ipynb).
// A table lands here when the code-based and prompt-based validators disagree
// on whether its extracted `table_id` / `title` fields are correct, so a
// human needs to confirm or correct them before Stage 3's title-based
// grouping runs on possibly-wrong values. The same edit card is offered for
// every table (not just flagged ones) so the user is always free to correct
// a Source Table ID / Title that validation missed — only flagged tables are
// required to be saved before continuing.
//
// Everything here keys off `_uid` (a plain per-file/per-position id the
// backend assigns), not `t.id` -- `t.id` is the catalog/DDI-style code
// derived from the table's own content, and two physically different tables
// (e.g. the same table title appearing in two different uploaded workbooks)
// can legitimately share it. Keying by `t.id` would make a correction to one
// such table silently apply to the other, and would render both under a
// single tab.
export default function ReconcileIds({ tables, onContinue, extraAction, visibleId, onNavigate, onSave, scopeTables }) {
  const mismatched = tables.filter((t) => t.id_title_mismatch)
  const visible = tables.filter((t) => t._uid === visibleId)
  // The top hint/clean message is scoped to whichever dataset is currently
  // in view (falls back to all tables when no scope is given) — otherwise
  // it warns about mismatches in a dataset the user isn't even looking at.
  const scopedMismatched = (scopeTables || tables).filter((t) => t.id_title_mismatch)

  const [drafts, setDrafts] = useState(() =>
    Object.fromEntries(
      tables.map((t) => [t._uid, { table_id: t.table_id || '', title: t.title || '' }])
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
  const [lockedIds, setLockedIds] = useState(() => new Set(tables.filter((t) => !t.id_title_mismatch).map((t) => t._uid)))

  const updateDraft = (uid, field, value) => {
    setDrafts((prev) => ({ ...prev, [uid]: { ...prev[uid], [field]: value } }))
  }

  const isDirty = (t) => {
    const draft = drafts[t._uid] || {}
    const snapshot = savedSnapshots[t._uid]
    const base = snapshot || { table_id: t.table_id || '', title: t.title || '' }
    return draft.table_id !== base.table_id || draft.title !== base.title
  }

  const isSaved = (t) => savedIds.has(t._uid) && !isDirty(t)

  const saveDetails = (uid) => {
    const t = tables.find((m) => m._uid === uid)
    const draft = drafts[uid] || {}
    // Blank input keeps the existing extracted value, same as the
    // notebook's reconciliation loop.
    const correction = {
      table_id: draft.table_id?.trim() || t.table_id,
      title: draft.title?.trim() || t.title,
    }
    setSavedSnapshots((prev) => ({ ...prev, [uid]: { ...drafts[uid] } }))
    const newSaved = new Set(savedIds).add(uid)
    setSavedIds(newSaved)
    setLockedIds((prev) => new Set(prev).add(uid))
    onSave?.(uid, correction)

    // Jump to the next flagged table that still needs saving, so the user
    // works through every mismatch instead of having to hunt for the next one.
    const idx = mismatched.findIndex((m) => m._uid === uid)
    if (idx !== -1) {
      const after = mismatched.slice(idx + 1).find((m) => !newSaved.has(m._uid))
      const before = mismatched.slice(0, idx).find((m) => !newSaved.has(m._uid))
      const next = after || before
      if (next) onNavigate?.(next._uid)
    }
  }

  const editDetails = (uid) => {
    setLockedIds((prev) => {
      const next = new Set(prev)
      next.delete(uid)
      return next
    })
  }

  const handleContinue = () => {
    const corrections = {}
    tables.forEach((t) => {
      const draft = drafts[t._uid] || {}
      // Blank input keeps the existing extracted value, same as the
      // notebook's reconciliation loop.
      corrections[t._uid] = {
        table_id: draft.table_id?.trim() || t.table_id,
        title: draft.title?.trim() || t.title,
      }
    })
    onContinue(corrections)
  }

  const allCorrected = mismatched.every((t) => isSaved(t))

  // Combines the code- and LLM-validator issues for a table into a single
  // de-duped list, and classifies each one by which field(s) it concerns so
  // the reconcile card can tell the user exactly what to fix.
  const mismatchInfo = (t) => {
    const issues = [
      ...(t.id_validation?.code?.issues || []),
      ...(t.id_validation?.llm?.issues || []),
    ].filter((v, i, arr) => arr.indexOf(v) === i)

    let idFlagged = false
    let titleFlagged = false
    issues.forEach((issue) => {
      const lower = issue.toLowerCase()
      const mentionsId = lower.includes('table id') || lower.includes(' id ') || lower.startsWith('id')
      const mentionsTitle = lower.includes('title')
      const isSwap = lower.includes('swap')
      if (isSwap || (mentionsId && mentionsTitle)) {
        idFlagged = true
        titleFlagged = true
      } else if (mentionsId) {
        idFlagged = true
      } else if (mentionsTitle) {
        titleFlagged = true
      } else {
        // Unclassifiable issue — flag both fields rather than hide the reason.
        idFlagged = true
        titleFlagged = true
      }
    })
    return { issues, idFlagged, titleFlagged }
  }

  return (
    <div className="console-grouping-step">
      <div className="reconcile-title">Confirm Source Table Details</div>
      {scopedMismatched.length > 0 ? (
        <div className="reconcile-hint">
          {scopedMismatched.length} table{scopedMismatched.length !== 1 ? 's' : ''} had disagreeing code-based and prompt-based
          validation of the Source Table ID / Table Title fields. Click a flagged table above to confirm or correct it before grouping.
          Any other table can be edited here too, if needed.
        </div>
      ) : (
        <div className="reconcile-clean">✓ No Source Table ID / Title mismatches found — all extracted tables look consistent. You can still edit a table's details below if needed.</div>
      )}

      <div className="reconcile-list">
        {visible.map((t) => {
          const locked = lockedIds.has(t._uid)
          const showReason = t.id_title_mismatch && !isSaved(t)
          const { issues, idFlagged, titleFlagged } = showReason ? mismatchInfo(t) : {}
          return (
            <div className={`reconcile-card${showReason ? ' reconcile-card-unedited' : ''}`} key={t._uid}>
              <div className="reconcile-card-head">{t.id}</div>

              {showReason && issues.length > 0 && (
                <ul className="reconcile-issues">
                  {issues.map((issue, i) => <li key={i}>{issue}</li>)}
                </ul>
              )}

              <div className="reconcile-fields">
                <label className={`reconcile-field${showReason && idFlagged ? ' reconcile-field-bad' : ''}`}>
                  <span>Source Table ID{showReason && idFlagged ? ' — needs fixing' : ''}</span>
                  <input
                    value={drafts[t._uid]?.table_id ?? ''}
                    onChange={(e) => updateDraft(t._uid, 'table_id', e.target.value)}
                    readOnly={locked}
                    spellCheck={false}
                  />
                </label>
                <label className={`reconcile-field${showReason && titleFlagged ? ' reconcile-field-bad' : ''}`}>
                  <span>Table Title{showReason && titleFlagged ? ' — needs fixing' : ''}</span>
                  <input
                    value={drafts[t._uid]?.title ?? ''}
                    onChange={(e) => updateDraft(t._uid, 'title', e.target.value)}
                    readOnly={locked}
                    spellCheck={false}
                  />
                </label>
              </div>

              <div className="reconcile-card-actions">
                <button
                  className="console-secondary-btn reconcile-save-btn"
                  onClick={() => saveDetails(t._uid)}
                  disabled={locked}
                >
                  Save details
                </button>
                <button
                  className="console-secondary-btn reconcile-edit-btn"
                  onClick={() => editDetails(t._uid)}
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
