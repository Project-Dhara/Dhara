'use client'

import { useState } from 'react'
import { ArrowRight, AlertTriangle, Check, Sparkles } from 'lucide-react'
import Button from '../ui/Button'

function hasAiFilledFields(t) {
  return Boolean(t?.title_repaired_by_llm || t?.table_id_repaired_by_llm)
}

// Stage 2.5 — Reconcile Source Table ID / Title mismatches (see backend/dhara_dry_run.ipynb).
// A table lands here when the code-based and prompt-based validators disagree
// on whether its extracted `table_id` / `title` fields are correct, so a
// human needs to confirm or correct them before Stage 3's title-based
// grouping runs on possibly-wrong values. The same edit card is offered for
// every table (not just flagged ones) so the user is always free to correct
// a Source Table ID / Title that validation missed — only flagged tables are
// required to be saved before continuing.
//
// Fields auto-filled by the LLM (`table_id_repaired_by_llm` /
// `title_repaired_by_llm`) are highlighted for review even when validation
// passed after the repair.
//
// Everything here keys off `_uid` (a plain per-file/per-position id the
// backend assigns), not `t.id` -- `t.id` is the catalog/DDI-style code
// derived from the table's own content, and two physically different tables
// (e.g. the same table title appearing in two different uploaded workbooks)
// can legitimately share it. Keying by `t.id` would make a correction to one
// such table silently apply to the other, and would render both under a
// single tab.
export default function ReconcileIds({ tables, onContinue, extraAction, visibleId, onNavigate, onSave, scopeTables, savedIds: persistedSavedIds }) {
  const mismatched = tables.filter((t) => t.id_title_mismatch)
  const visible = tables.filter((t) => t._uid === visibleId)
  // The top hint/clean message is scoped to whichever dataset is currently
  // in view (falls back to all tables when no scope is given) — otherwise
  // it warns about mismatches in a dataset the user isn't even looking at.
  const scopedMismatched = (scopeTables || tables).filter((t) => t.id_title_mismatch)
  const scopedAiFilled = (scopeTables || tables).filter((t) => hasAiFilledFields(t))

  const [drafts, setDrafts] = useState(() =>
    Object.fromEntries(
      tables.map((t) => [t._uid, { table_id: t.table_id || '', title: t.title || '' }])
    )
  )
  // The values as they stood the last time "Save details" was clicked for
  // that table — compared against the live draft to decide whether the
  // save button should reappear (edited again since saving).
  const [savedSnapshots, setSavedSnapshots] = useState({})
  // Seeded from the parent's persisted `savedIds` (keyed by `_uid`, and kept
  // alive across the whole console session) rather than starting empty —
  // this component unmounts whenever the wizard leaves the preview step
  // (e.g. visiting the grouping page and coming back), and an empty-Set
  // restart made every already-saved table look unsaved/"needs fixing"
  // again despite the correction still being applied to `matchResult`.
  const [savedIds, setSavedIds] = useState(() => new Set(persistedSavedIds ?? []))
  // Fields lock (read-only) right after a save, so the user has to
  // deliberately click "Edit" to change a table's details again. Tables
  // that passed validation start locked too — the user must click "Edit"
  // before those fields (and the Save button) become usable, whereas a
  // flagged or AI-filled table starts unlocked since it needs reviewing.
  const [lockedIds, setLockedIds] = useState(() => new Set(
    tables
      .filter((t) => {
        if (persistedSavedIds?.has(t._uid)) return true
        if (t.id_title_mismatch) return false
        if (hasAiFilledFields(t)) return false
        return true
      })
      .map((t) => t._uid)
  ))

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

    // Jump to the next flagged / AI-filled table that still needs saving.
    const reviewQueue = tables.filter((m) => m.id_title_mismatch || hasAiFilledFields(m))
    const idx = reviewQueue.findIndex((m) => m._uid === uid)
    if (idx !== -1) {
      const after = reviewQueue.slice(idx + 1).find((m) => !newSaved.has(m._uid))
      const before = reviewQueue.slice(0, idx).find((m) => !newSaved.has(m._uid))
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

  const fieldLabelClass = ({ needsFix, aiFilled }) => {
    if (needsFix) return 'font-semibold text-coral'
    if (aiFilled) return 'font-semibold text-[#2F6FED]'
    return 'text-ink-soft'
  }

  const fieldInputClass = ({ needsFix, aiFilled, locked }) => {
    const base = 'rounded-lg border px-2.5 py-2 font-sans text-[13.5px] text-ink focus:border-teal focus:outline-none read-only:cursor-default read-only:bg-mist read-only:text-ink-soft'
    if (needsFix) return `${base} border-2 border-coral bg-error-bg`
    if (aiFilled && !locked) return `${base} border-2 border-[#5B8DEF] bg-[#EEF4FF]`
    if (aiFilled) return `${base} border-[#5B8DEF]/70 bg-[#EEF4FF]`
    return `${base} border-line-strong`
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="mb-0.5 text-lg font-bold text-ink">Confirm Source Table Details</div>
      {scopedMismatched.length > 0 ? (
        <div className="text-[13px] leading-relaxed text-ink-soft">
          {scopedMismatched.length} table{scopedMismatched.length !== 1 ? 's' : ''} had disagreeing code-based and prompt-based
          validation of the Source Table ID / Table Title fields. Click a flagged table above to confirm or correct it before grouping.
          Any other table can be edited here too, if needed.
        </div>
      ) : (
        <div className="rounded-[10px] border border-green bg-sage px-4 py-3 text-sm text-ink">
          <span className="inline-flex items-start gap-1.5">
            <Check className="mt-0.5 h-4 w-4 flex-none text-green" strokeWidth={2.5} aria-hidden />
            No Source Table ID / Title mismatches found — all extracted tables look consistent. You can still edit a table&apos;s details below if needed.
          </span>
        </div>
      )}
      {scopedAiFilled.length > 0 && (
        <div className="rounded-[10px] border border-[#5B8DEF]/45 bg-[#EEF4FF] px-4 py-3 text-sm text-ink">
          <span className="inline-flex items-start gap-1.5">
            <Sparkles className="mt-0.5 h-4 w-4 flex-none text-[#2F6FED]" strokeWidth={2} aria-hidden />
            <span>
              <span className="font-semibold text-[#2F6FED]">AI review:</span>{' '}
              {scopedAiFilled.length} table{scopedAiFilled.length !== 1 ? 's' : ''} had Source Table ID and/or Table Title filled by AI — blue-highlighted fields below are worth a quick check.
            </span>
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-[12px] text-ink-soft">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-coral" aria-hidden />
          Needs fixing
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-[#2F6FED]" aria-hidden />
          AI review
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-green" aria-hidden />
          Reviewed / OK
        </span>
      </div>
      <div className="flex flex-col gap-3.5">
        {visible.map((t) => {
          const locked = lockedIds.has(t._uid)
          const showReason = t.id_title_mismatch && !isSaved(t)
          const { issues, idFlagged, titleFlagged } = showReason ? mismatchInfo(t) : {}
          const idAi = Boolean(t.table_id_repaired_by_llm) && !isSaved(t)
          const titleAi = Boolean(t.title_repaired_by_llm) && !isSaved(t)
          return (
            <div className="flex flex-col gap-3 rounded-[10px] border border-line bg-white p-4 px-[18px]" key={t._uid}>
              <div className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-ink">
                <span>{t.id}</span>
                {showReason && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-coral/40 bg-error-bg px-2 py-0.5 text-[11px] font-semibold text-coral">
                    <AlertTriangle className="h-3 w-3" strokeWidth={2} aria-hidden />
                    Needs fixing
                  </span>
                )}
                {hasAiFilledFields(t) && !isSaved(t) && !showReason && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-[#5B8DEF]/45 bg-[#EEF4FF] px-2 py-0.5 text-[11px] font-semibold text-[#2F6FED]">
                    <Sparkles className="h-3 w-3" strokeWidth={2} aria-hidden />
                    AI review
                  </span>
                )}
              </div>

              {showReason && issues.length > 0 && (
                <ul className="m-0 ml-[18px] mt-1 list-disc p-0 text-[12.5px] text-ink-soft">
                  {issues.map((issue, i) => <li key={i}>{issue}</li>)}
                </ul>
              )}

              <div className="flex flex-wrap gap-4">
                <label className={`flex flex-1 basis-[260px] flex-col gap-1 text-xs ${fieldLabelClass({ needsFix: showReason && idFlagged, aiFilled: idAi })}`}>
                  <span>
                    Source Table ID
                    {showReason && idFlagged ? ' — needs fixing' : ''}
                    {!showReason && idAi ? ' — filled by AI' : ''}
                  </span>
                  <input
                    className={fieldInputClass({ needsFix: showReason && idFlagged, aiFilled: idAi, locked })}
                    value={drafts[t._uid]?.table_id ?? ''}
                    onChange={(e) => updateDraft(t._uid, 'table_id', e.target.value)}
                    readOnly={locked}
                    spellCheck={false}
                  />
                </label>
                <label className={`flex flex-1 basis-[260px] flex-col gap-1 text-xs ${fieldLabelClass({ needsFix: showReason && titleFlagged, aiFilled: titleAi })}`}>
                  <span>
                    Table Title
                    {showReason && titleFlagged ? ' — needs fixing' : ''}
                    {!showReason && titleAi ? ' — filled by AI' : ''}
                  </span>
                  <input
                    className={fieldInputClass({ needsFix: showReason && titleFlagged, aiFilled: titleAi, locked })}
                    value={drafts[t._uid]?.title ?? ''}
                    onChange={(e) => updateDraft(t._uid, 'title', e.target.value)}
                    readOnly={locked}
                    spellCheck={false}
                  />
                </label>
              </div>

              <div className="flex items-center gap-2.5">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => saveDetails(t._uid)}
                  disabled={locked}
                >
                  Save details
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => editDetails(t._uid)}
                  disabled={!locked}
                >
                  Edit
                </Button>
                {isSaved(t) && (
                  <span className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-green">
                    <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
                    Saved
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex items-center gap-4">
        {allCorrected && (
          <Button onClick={handleContinue} className="inline-flex items-center gap-1.5">
            {mismatched.length > 0 ? 'Apply corrections & continue' : 'Continue'}
            <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
          </Button>
        )}
        {extraAction}
      </div>
      {!allCorrected && (
        <div className="mt-1.5 text-sm text-[#8a4b0f]">
          Correct and save all {mismatched.length} flagged table{mismatched.length !== 1 ? 's' : ''} above
          ({mismatched.length - mismatched.filter((t) => isSaved(t)).length} remaining) before continuing.
        </div>
      )}
    </div>
  )
}
