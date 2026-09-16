'use client'

/** NCO 2015 code-suggestion results for the active occupation column. */
export default function NcoSuggestPanel({ codes, ncoError, ncoLoading, ncoMatches }) {
  return (
    <div className="border-t border-line px-[18px] pb-[18px]">
      <div className="pb-3 pt-4">
        <div className="text-[15px] font-bold text-ink">NCO 2015 code suggestion</div>
        <div className="mt-1 max-w-[520px] text-[13px] leading-snug text-ink-soft">
          Fills Code and Definition above from the suggested NCO code and title. Harmonisation still asks you to verify those codes before they are saved.
        </div>
      </div>
      {ncoError && <div className="mb-2.5 text-[13px] text-[#b91c1c]">{ncoError}</div>}
      {ncoLoading && !ncoMatches && (
        <div className="text-[13px] text-ink-soft">Matching occupation values to NCO 2015…</div>
      )}
      {ncoMatches && (
        <div className="overflow-hidden rounded-lg border border-[#cfc6b4]">
          <div className="grid grid-cols-[1.2fr_0.7fr_0.8fr_1.4fr] items-start gap-3.5 border-b border-[#d7cdb9] bg-[#F4EFE3] px-4 py-2.5 font-sans text-[11.5px] uppercase tracking-wide text-[#8E9398]">
            <div>Value</div><div>Level</div><div>Suggested code</div><div>Title</div>
          </div>
          {codes.map((row) => {
            const m = ncoMatches[row.value]
            return (
              <div className="grid grid-cols-[1.2fr_0.7fr_0.8fr_1.4fr] items-start gap-3.5 border-b border-[#f1ebdf] bg-white px-4 py-2.5 last:border-b-0" key={row.value || row.code}>
                <div className="text-sm font-semibold text-ink">{row.value}</div>
                <div className="text-sm font-semibold text-ink">{m ? m.level : '—'}</div>
                <div className="text-sm font-semibold text-ink">{m ? m.code : '—'}</div>
                <div>
                  <div className="text-sm font-semibold text-ink">{m ? m.title : '—'}</div>
                  {m && (
                    <div className="mt-0.5 text-xs text-ink-soft">
                      {m.confidence} confidence
                      {m.auto_fill ? ' · auto-filled' : ' · review before using'}
                      {m.source ? ` · ${m.source}` : ''}
                      {m.codes?.length > 1 ? ' · both valid' : ''}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
