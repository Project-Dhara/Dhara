'use client'

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

function candidateList(match) {
  if (!match) return []
  if (Array.isArray(match.candidates) && match.candidates.length) return match.candidates
  const primary = {
    code: match.lgd_code || match.code,
    title: match.name_english || match.title,
    entity_type: match.entity_type || match.level,
    hierarchy: match.hierarchy,
  }
  const alts = Array.isArray(match.alternates) ? match.alternates : []
  const seen = new Set()
  const out = []
  for (const c of [primary, ...alts]) {
    const code = String(c?.code || c?.lgd_code || '').trim()
    if (!code || seen.has(code)) continue
    seen.add(code)
    out.push(c)
  }
  return out
}

/** Modal preview of LGD suggestions (same fields as lgd_explorer result cards). */
export default function LgdSuggestPanel({
  open,
  onClose,
  codes,
  lgdError,
  lgdLoading,
  lgdMatches,
  onPickCandidate,
}) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="lgd-preview-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.()
      }}
    >
      <div className="flex max-h-[min(720px,88vh)] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-surface shadow-dhara">
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 id="lgd-preview-title" className="m-0 text-[16px] font-bold text-ink">
              LGD code suggestion
            </h2>
            <p className="m-0 mt-1 max-w-[36rem] text-[13px] leading-snug text-ink-soft">
              Fills Code and Definition from the Local Government Directory match
              (same search as the LGD explorer). Rows with multiple LGD codes are
              highlighted — pick one.
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
          {lgdError && <div className="mb-3 text-[13px] text-[#b91c1c]">{lgdError}</div>}
          {lgdLoading && !lgdMatches && (
            <div className="text-[13px] text-ink-soft">Matching values to LGD hierarchy…</div>
          )}
          {lgdMatches && (
            <div className="overflow-x-auto rounded-lg border border-[#cfc6b4]">
              <table className="w-full min-w-[560px] table-fixed border-separate border-spacing-0 text-left">
                <thead>
                  <tr className="bg-[#F4EFE3] text-[11px] uppercase tracking-wide text-[#8E9398]">
                    <th className="w-[24%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Value</th>
                    <th className="w-[14%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Type</th>
                    <th className="w-[14%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">LGD code</th>
                    <th className="w-[48%] border-b border-[#d7cdb9] px-3 py-2.5 font-semibold">Name / hierarchy</th>
                  </tr>
                </thead>
                <tbody>
                  {codes.map((row) => {
                    const m = lgdMatches[row.value]
                    const notFound = !m
                    const ambiguous = Boolean(m?.ambiguous) && (m?.candidate_count > 1 || candidateList(m).length > 1)
                    const candidates = candidateList(m)
                    const selectedCode = String(row.code || m?.lgd_code || m?.code || '').trim()
                    return (
                      <tr
                        className={ambiguous ? 'bg-[#fff6e4]' : (notFound ? 'bg-[#f7f3ea]' : 'bg-white')}
                        key={row.value || row.code}
                      >
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-semibold leading-snug text-ink break-words">
                          {row.value}
                          {ambiguous && (
                            <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-[#9a6700]">
                              Multiple LGD codes — pick one
                            </div>
                          )}
                          {notFound && (
                            <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                              Not found
                            </div>
                          )}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-medium capitalize text-ink">
                          {m ? String(m.entity_type || m.level || '').replaceAll('_', ' ') : '—'}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-semibold tabular-nums text-ink">
                          {notFound ? '-' : (selectedCode || m.lgd_code || m.code || '—')}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top">
                          <div className="text-[13px] font-semibold leading-snug text-ink break-words">
                            {notFound ? '-' : (m.name_english || m.title || '—')}
                          </div>
                          {m?.hierarchy && !ambiguous && (
                            <div className="mt-1 text-[12px] leading-snug text-ink-soft break-words">
                              {m.hierarchy}
                            </div>
                          )}
                          {m && !ambiguous && (
                            <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                              {m.kind || m.confidence}
                              {m.auto_fill ? ' · auto-filled' : ' · review before using'}
                            </div>
                          )}
                          {ambiguous && (
                            <div className="mt-2 flex flex-col gap-1.5">
                              {candidates.map((c) => {
                                const code = String(c.code || c.lgd_code || '').trim()
                                const picked = code && code === selectedCode
                                return (
                                  <button
                                    key={code}
                                    type="button"
                                    className={`rounded-md border px-2.5 py-2 text-left transition-colors ${
                                      picked
                                        ? 'border-teal bg-sage/60'
                                        : 'border-[#e6d7a8] bg-white hover:border-teal/50 hover:bg-sage/40'
                                    }`}
                                    onClick={() => onPickCandidate?.(row.value, c)}
                                  >
                                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                                      <span className="text-[13px] font-semibold tabular-nums text-ink">
                                        {code}
                                      </span>
                                      <span className="text-[11.5px] font-medium capitalize text-ink-soft">
                                        {String(c.entity_type || '').replaceAll('_', ' ')}
                                        {picked ? ' · selected' : ''}
                                      </span>
                                    </div>
                                    <div className="mt-0.5 text-[12.5px] font-medium text-ink break-words">
                                      {c.name_english || c.title || '—'}
                                    </div>
                                    {c.hierarchy && (
                                      <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft break-words">
                                        {c.hierarchy}
                                      </div>
                                    )}
                                  </button>
                                )
                              })}
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!lgdLoading && !lgdMatches && !lgdError && (
            <div className="text-[13px] text-ink-soft">
              Run Suggest LGD codes to generate a preview.
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
