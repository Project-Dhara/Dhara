'use client'

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

/** Modal preview of NCO 2015 suggestions for the active occupation column. */
export default function NcoSuggestPanel({
  open,
  onClose,
  codes,
  ncoError,
  ncoLoading,
  ncoMatches,
  needsStandard = false,
  onGoSettings,
  onFillAiFallback,
  fillAiLoading = false,
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
      aria-labelledby="nco-preview-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.()
      }}
    >
      <div className="flex max-h-[min(640px,88vh)] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-surface shadow-dhara">
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 id="nco-preview-title" className="m-0 text-[16px] font-bold text-ink">
              NCO 2015 code suggestion
            </h2>
            <p className="m-0 mt-1 max-w-[36rem] text-[13px] leading-snug text-ink-soft">
              {needsStandard
                ? 'Occupation matching needs a classification file uploaded and selected in Settings. Or fill definitions with AI without NCO codes.'
                : 'Fills Code and Definition from the suggested NCO code and title.'}
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
            <div className="text-[13px] text-ink-soft">Matching occupation values to NCO 2015…</div>
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
                    return (
                      <tr className="bg-white" key={row.value || row.code}>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-semibold leading-snug text-ink break-words">
                          {row.value}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-medium capitalize text-ink">
                          {m ? m.level : '—'}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top text-[13px] font-semibold tabular-nums text-ink">
                          {m ? m.code : '—'}
                        </td>
                        <td className="border-b border-[#f1ebdf] px-3 py-2.5 align-top">
                          <div className="text-[13px] font-semibold leading-snug text-ink break-words">
                            {m ? m.title : '—'}
                          </div>
                          {m && (
                            <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                              {m.confidence} confidence
                              {m.auto_fill ? ' · auto-filled' : ' · review before using'}
                              {m.source ? ` · ${m.source}` : ''}
                              {m.codes?.length > 1 ? ' · both valid' : ''}
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
          {!ncoLoading && !ncoMatches && !needsStandard && !ncoError && (
            <div className="text-[13px] text-ink-soft">
              Run Suggest NCO codes to generate a preview.
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
