'use client'

import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import NcoHierarchy from './NcoHierarchy'

/** Merge primary + candidates + alternatives, deduped by code. */
function candidateList(match) {
  if (!match || match.status === 'not_an_occupation') return []
  const out = []
  const seen = new Set()
  const push = (item) => {
    if (!item) return
    const code = String(item.code || '').trim()
    if (!code) return
    if (seen.has(code)) return
    seen.add(code)
    out.push(item)
  }
  if (match.code && String(match.code).trim()) {
    push({
      code: match.code,
      level: match.level,
      title: match.title,
      division_code: match.division_code,
      division_title: match.division_title,
      subdivision_code: match.subdivision_code,
      subdivision_title: match.subdivision_title,
      group_code: match.group_code,
      group_title: match.group_title,
      family_code: match.family_code,
      family_title: match.family_title,
    })
  }
  if (Array.isArray(match.candidates)) {
    for (const c of match.candidates) push(c)
  }
  if (Array.isArray(match.alternatives)) {
    for (const c of match.alternatives) push(c)
  }
  if (!out.length && Array.isArray(match.codes) && match.codes.length) {
    for (const code of match.codes) {
      push({ code, level: match.level, title: match.title })
    }
  }
  return out
}

function isResolvedMatch(match, row) {
  if (!match) return false
  if (match.chosen || match.status === 'steward_pick') return true
  const rowCode = String(row?.code || '').trim()
  const matchCode = String(match.code || '').trim()
  return Boolean(rowCode && matchCode && rowCode === matchCode)
}

/** Chip face is title-only; code stays in tooltip / selected detail. */
function pillLabel(candidate) {
  return String(candidate?.title || '').trim() || '—'
}

/** Restore pending picks from current row/match codes for multi-choice rows. */
function seedPendingFromCodes(codes, ncoMatches) {
  const next = {}
  if (!ncoMatches || !Array.isArray(codes)) return next
  for (const row of codes) {
    const value = row?.value
    if (value == null || value === '') continue
    const m = ncoMatches[value]
    if (!m || m.status === 'not_an_occupation') continue
    const candidates = candidateList(m)
    if (candidates.length <= 1) continue
    const code = String(row.code || m.code || '').trim()
    if (!code) continue
    const match = candidates.find((c) => String(c.code || '').trim() === code)
    if (match) next[value] = match
  }
  return next
}

/** Modal preview of NCO 2015 suggestions for the active occupation column. */
export default function NcoSuggestPanel({
  open,
  onClose,
  codes,
  ncoError,
  ncoRetrievalMode = '',
  ncoLoading,
  ncoMatches,
  ncoStage = '',
  ncoProgress = null,
  ncoWaitingMessage = '',
  needsStandard = false,
  onGoSettings,
  onFillAiFallback,
  fillAiLoading = false,
  onConfirmPicks,
  onStopWaiting,
  showStopWaiting = false,
}) {
  const [pendingByValue, setPendingByValue] = useState({})

  const matchesKey = useMemo(() => {
    if (!ncoMatches) return ''
    return Object.keys(ncoMatches).sort().join('\0')
  }, [ncoMatches])

  useEffect(() => {
    if (!open) return
    // Seed from confirmed / current codes so reopening keeps picks highlighted.
    setPendingByValue(seedPendingFromCodes(codes, ncoMatches))
  }, [open, matchesKey, codes, ncoMatches])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const pendingCount = Object.keys(pendingByValue).length

  const handleConfirm = () => {
    // Parent closes the modal (and clears ncoPanelOpen) before applying picks.
    onConfirmPicks?.(pendingByValue)
  }

  const stageCopy = (() => {
    const stage = String(ncoStage || '').trim()
    if (stage === 'loading_model') return 'Loading embedding model…'
    if (stage === 'preparing_index') return 'Preparing NCO index…'
    if (stage === 'matching') {
      const done = ncoProgress?.done
      const total = ncoProgress?.total
      if (total != null && done != null) {
        return `Matching occupations… (${done}/${total})`
      }
      return 'Matching occupations…'
    }
    if (stage === 'queued') return 'Queued — waiting for the processing service…'
    if (ncoWaitingMessage) return ncoWaitingMessage
    return 'Matching occupation values to NCO 2015…'
  })()

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="nco-preview-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.()
      }}
    >
      <div className="flex max-h-[min(720px,88vh)] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-surface shadow-dhara">
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 id="nco-preview-title" className="m-0 text-[16px] font-bold text-ink">
              NCO 2015 code suggestion
            </h2>
            <p className="m-0 mt-1 max-w-[40rem] text-[13px] leading-snug text-ink-soft">
              {needsStandard
                ? 'Occupation matching needs a classification standard selected in Settings. Or fill definitions with AI without NCO codes.'
                : 'Compare each option’s hierarchy, pick one per highlighted row, then Confirm to fill Code and Definition.'}
            </p>
          </div>
          <button
            type="button"
            className="flex h-8 w-8 flex-none items-center justify-center rounded-md text-ink-soft transition-colors hover:bg-cream hover:text-ink"
            aria-label="Close preview"
            onClick={onClose}
          >
            <X className="h-4 w-4" strokeWidth={2} aria-hidden />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {ncoError && <div className="mb-3 text-[13px] text-[#b91c1c]">{ncoError}</div>}
          {needsStandard && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {onGoSettings && (
                <button
                  type="button"
                  className="h-8 rounded-md border-0 bg-teal px-3 text-[12.5px] font-semibold text-white transition-colors hover:bg-teal-dark"
                  onClick={onGoSettings}
                >
                  Open Settings
                </button>
              )}
              {onFillAiFallback && (
                <button
                  type="button"
                  className="h-8 rounded-md border border-line bg-white px-3 text-[12.5px] font-semibold text-ink-soft transition-colors hover:border-teal/40 hover:text-teal disabled:cursor-default disabled:opacity-50"
                  disabled={fillAiLoading || !codes.length}
                  onClick={onFillAiFallback}
                >
                  {fillAiLoading ? 'Filling…' : 'Fill with AI instead'}
                </button>
              )}
            </div>
          )}
          {ncoLoading && !ncoMatches && (
            <div className="text-[13px] text-ink-soft">
              <div>{stageCopy}</div>
              <div className="mt-1 text-[12px]">
                First run after app start can take several minutes while the embedding model loads.
              </div>
              {showStopWaiting && onStopWaiting && (
                <button
                  type="button"
                  className="mt-3 h-8 rounded-md border border-line bg-white px-3 text-[12.5px] font-semibold text-ink-soft transition-colors hover:border-teal/40 hover:text-teal"
                  onClick={onStopWaiting}
                >
                  Stop waiting
                </button>
              )}
            </div>
          )}
          {ncoMatches && (
            <div className="overflow-x-auto rounded-lg border border-[#cfc6b4]">
              <table className="w-full min-w-[560px] table-fixed border-separate border-spacing-0 text-left">
                <thead>
                  <tr className="bg-[#F4EFE3] text-[11px] uppercase tracking-wide text-[#8E9398]">
                    <th className="w-[34%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Value</th>
                    <th className="w-[14%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Level</th>
                    <th className="w-[16%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Suggested code</th>
                    <th className="w-[36%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Title</th>
                  </tr>
                </thead>
                <tbody>
                  {codes.map((row) => {
                    const m = ncoMatches[row.value]
                    const notOccupation = m?.status === 'not_an_occupation'
                    const resolved = isResolvedMatch(m, row)
                    const candidates = candidateList(m)
                    const multiCandidates = !notOccupation && candidates.length > 1
                    // Unresolved multi: pick UI. Resolved: confirmed title (current UI).
                    // Reopen review: chips stay available under confirmed detail with distinct colors.
                    const needsPick = multiCandidates && !resolved
                    const pending = pendingByValue[row.value]
                    const confirmedCode = String(row.code || m?.code || '').trim()
                    const selectedCode = String(
                      pending?.code || confirmedCode || '',
                    ).trim()
                    const displayLevel = pending?.level || m?.level
                    const displayTitle = pending?.title || m?.title || (needsPick ? 'Choose a candidate' : '—')
                    const expanded = pending || (resolved ? m : null)
                    const showConfirmedDetail = resolved && !needsPick
                    return (
                      <tr
                        className={needsPick ? 'bg-[#fff6e4]' : (notOccupation ? 'bg-[#f7f3ea]' : 'bg-white')}
                        key={row.value || row.code}
                      >
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-semibold leading-snug text-ink break-words">
                          {row.value}
                          {needsPick && (
                            <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-[#9a6700]">
                              Multiple NCO codes — pick one
                            </div>
                          )}
                          {multiCandidates && resolved && (
                            <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-teal">
                              Confirmed — select another to change
                            </div>
                          )}
                          {notOccupation && (
                            <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                              Not an occupation
                            </div>
                          )}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-medium capitalize text-ink">
                          {notOccupation ? '—' : (displayLevel || '—')}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-semibold tabular-nums text-ink">
                          {notOccupation ? '—' : (selectedCode || '—')}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top">
                          {notOccupation ? (
                            <div className="text-[13px] font-semibold leading-snug text-ink-soft break-words">
                              {m.reason || 'Employment status, not an occupation.'}
                            </div>
                          ) : (
                            <>
                              {showConfirmedDetail && (
                                <>
                                  <div className="text-[13px] font-semibold leading-snug text-ink break-words">
                                    {displayTitle}
                                  </div>
                                  <NcoHierarchy match={expanded || m} />
                                  {m && (
                                    <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                                      {m.confidence} confidence
                                      {' · confirmed'}
                                    </div>
                                  )}
                                </>
                              )}
                              {!multiCandidates && !showConfirmedDetail && (
                                <>
                                  <div className="text-[13px] font-semibold leading-snug text-ink break-words">
                                    {displayTitle}
                                  </div>
                                  <NcoHierarchy match={expanded || m} />
                                  {m && (
                                    <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                                      {m.confidence} confidence
                                      {resolved ? ' · confirmed' : (m.auto_fill ? ' · auto-filled' : ' · review before using')}
                                    </div>
                                  )}
                                </>
                              )}
                              {multiCandidates && (
                                <div className={showConfirmedDetail ? 'mt-2' : 'mt-1'}>
                                  <div className="flex flex-wrap gap-1.5">
                                    {candidates.map((c) => {
                                      const code = String(c.code || '').trim()
                                      const picked = code && code === selectedCode
                                      const isConfirmedPick = Boolean(
                                        code
                                        && confirmedCode
                                        && code === confirmedCode
                                        && resolved,
                                      )
                                      const label = pillLabel(c)
                                      let chipClass = 'border-[#e6d7a8] bg-white text-ink hover:border-teal/50 hover:bg-sage/40'
                                      if (isConfirmedPick && picked) {
                                        chipClass = 'border-teal bg-teal text-white'
                                      } else if (picked) {
                                        chipClass = 'border-teal bg-sage/60 text-ink'
                                      }
                                      return (
                                        <button
                                          key={`${c.level || ''}-${code}`}
                                          type="button"
                                          title={`${code} ${c.title || ''}`.trim()}
                                          className={`max-w-full truncate rounded-md border px-2.5 py-1 text-left text-[12.5px] font-semibold transition-colors ${chipClass}`}
                                          onClick={() => {
                                            setPendingByValue((prev) => ({
                                              ...prev,
                                              [row.value]: c,
                                            }))
                                          }}
                                        >
                                          {label}
                                          {isConfirmedPick && picked ? ' · confirmed' : ''}
                                        </button>
                                      )
                                    })}
                                  </div>
                                  {pending && (
                                    <div className={`mt-2 rounded-md border px-2.5 py-2 ${
                                      resolved && String(pending.code || '').trim() === confirmedCode
                                        ? 'border-teal bg-teal text-white'
                                        : 'border-teal/40 bg-sage/40 text-ink'
                                    }`}
                                    >
                                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                                        <span className={`text-[13px] font-semibold tabular-nums ${
                                          resolved && String(pending.code || '').trim() === confirmedCode
                                            ? 'text-white'
                                            : 'text-ink'
                                        }`}
                                        >
                                          {String(pending.code || '').trim()}
                                        </span>
                                        <span className={`text-[11.5px] font-medium capitalize ${
                                          resolved && String(pending.code || '').trim() === confirmedCode
                                            ? 'text-white/80'
                                            : 'text-ink-soft'
                                        }`}
                                        >
                                          {pending.level || ''}
                                          {resolved && String(pending.code || '').trim() === confirmedCode
                                            ? ' · confirmed'
                                            : ' · selected'}
                                        </span>
                                      </div>
                                      <div className={`mt-0.5 text-[12.5px] font-semibold leading-snug break-words ${
                                        resolved && String(pending.code || '').trim() === confirmedCode
                                          ? 'text-white'
                                          : 'text-ink'
                                      }`}
                                      >
                                        {pending.title || '—'}
                                      </div>
                                      <NcoHierarchy
                                        match={pending}
                                        className={
                                          resolved && String(pending.code || '').trim() === confirmedCode
                                            ? 'text-white/80'
                                            : 'text-ink-soft'
                                        }
                                      />
                                    </div>
                                  )}
                                </div>
                              )}
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!ncoLoading && !ncoMatches && !needsStandard && !ncoError && (
            <div className="text-[13px] text-ink-soft">
              Run Suggest NCO codes to generate a preview.
            </div>
          )}
        </div>

        {ncoMatches && !needsStandard && (
          <div className="flex flex-none items-center justify-between gap-3 border-t border-line px-5 py-3">
            <span className="text-[12.5px] text-ink-soft">
              {pendingCount
                ? `${pendingCount} selected — Confirm to fill Code and Definition`
                : 'Select options above, then Confirm'}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="h-9 rounded-md border border-line bg-white px-4 text-[13px] font-semibold text-ink-soft transition-colors hover:border-teal/40 hover:text-teal"
                onClick={onClose}
              >
                Close
              </button>
              <button
                type="button"
                className="h-9 rounded-md border-0 bg-teal px-4 text-[13px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
                disabled={pendingCount === 0}
                onClick={handleConfirm}
              >
                Confirm{pendingCount ? ` (${pendingCount})` : ''}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
