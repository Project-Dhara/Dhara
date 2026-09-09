'use client'

import { useEffect, useState } from 'react'

// Metadata entry, one card per table/metadata group. Field set mirrors what
// the backend's /api/catalogue/push and /api/catalogue/batch-push accept
// (see PushModal.jsx / BatchReview.jsx) — only `title` is actually required.
// Short categorical fields render as compact editable badges; focused fields
// expand to show wrapped content. Free-text fields get their own full-width row.
export const METADATA_COLUMNS = [
  { key: 'title', label: 'Title', type: 'primary', placeholder: 'Dataset / table title', required: true },
  { key: 'product', label: 'Product', type: 'badge', placeholder: 'e.g. Population_Data' },
  { key: 'category', label: 'Category', type: 'badge', placeholder: 'e.g. Demographics' },
  { key: 'geography', label: 'Geography', type: 'badge', placeholder: 'e.g. India' },
  { key: 'frequency', label: 'Frequency', type: 'badge', placeholder: 'e.g. Annually' },
  { key: 'time_period', label: 'Time period', type: 'badge', placeholder: 'e.g. 2001–2021' },
  { key: 'data_source', label: 'Source', type: 'badge', placeholder: 'e.g. Census of India' },
  { key: 'last_updated', label: 'Last updated', type: 'date' },
  { key: 'future_release', label: 'Future release', type: 'date' },
  { key: 'description', label: 'Description', type: 'long', placeholder: 'What this dataset covers' },
  { key: 'key_statistics', label: 'Key statistics', type: 'long', placeholder: 'Headline measures worth calling out' },
  { key: 'remarks', label: 'Remarks', type: 'long', placeholder: 'Any additional notes or caveats' },
]

function resizeBadgeInput(el, expanded) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = expanded ? `${el.scrollHeight}px` : ''
}

export default function MetadataSheetGrid({
  rows,
  columns = METADATA_COLUMNS,
  onChange,
  renderGroupFooter,
}) {
  const primaryCol = columns.find((c) => c.type === 'primary')
  const badgeCols = columns.filter((c) => c.type === 'badge' || c.type === 'date')
  const longCols = columns.filter((c) => c.type === 'long')

  const [activeIndex, setActiveIndex] = useState(0)
  useEffect(() => {
    if (activeIndex >= rows.length) setActiveIndex(Math.max(0, rows.length - 1))
  }, [rows.length, activeIndex])

  const activeRow = rows[activeIndex]

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="m-0 font-sans text-[13px] font-bold uppercase tracking-wide text-ink">Available Groups</h3>
          <span className="text-[13px] leading-snug text-ink-soft">
            {rows.length} metadata group{rows.length !== 1 ? 's' : ''} — select to review
          </span>
        </div>
        <div className="grid grid-cols-4 gap-x-4 gap-y-3.5 max-[900px]:grid-cols-2 max-[560px]:grid-cols-1">
        {rows.map((row, ri) => (
          <button
            key={row.id}
            type="button"
            className={`grid min-w-0 grid-cols-[18px_1fr] items-center gap-2 rounded-full border px-2.5 py-1.5 pl-2 font-sans text-[12.5px] font-medium transition-colors ${
              ri === activeIndex
                ? 'border-teal bg-sage text-ink'
                : 'border-line bg-surface text-ink-soft hover:border-teal hover:text-ink'
            }`}
            onClick={() => setActiveIndex(ri)}
            title={row.label}
          >
            <span className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-full text-[10.5px] font-bold ${ri === activeIndex ? 'bg-teal text-white' : 'bg-[#ece4d6] text-ink-soft'}`}>{ri + 1}</span>
            <span className="line-clamp-2 min-w-0 text-center leading-tight">{row.label}</span>
          </button>
        ))}
        </div>
      </div>

      {activeRow && (
        <div className="flex items-start">
          <div className="min-w-0 flex-1">
            {(() => {
              const row = activeRow
              const ri = activeIndex
              return (
            <div className="flex min-w-0 flex-col gap-3 [overflow-wrap:anywhere] rounded-[10px] border border-line bg-surface p-4 px-[18px]" key={row.id}>
            <div className="flex items-baseline gap-2">
              <span className="flex-none font-sans text-xs text-[#8E9398]">{ri + 1}</span>
              <span className="text-[15px] font-semibold text-ink" title={row.label}>{row.label}</span>
              {row.manual && (
                <span
                  className="rounded-md border border-[#f0d6a3] bg-[#fdf0d8] px-2 py-0.5 font-sans text-[11.5px] font-semibold text-[#a15c00]"
                  title="No metadata was auto-mapped for this group — fill in the fields below by hand"
                >
                  Not auto-mapped — fill in manually
                </span>
              )}
            </div>

            {primaryCol && (
              <input
                className={`box-border h-[42px] w-full rounded-lg border px-3.5 font-sans text-[15px] font-medium text-ink placeholder:text-[#a49c8e] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal ${
                  primaryCol.required && !(row.values[primaryCol.key] || '').trim() ? 'border-[#e3b3ba] bg-[rgba(217,91,104,0.06)]' : 'border-[#ddd3c0] bg-cream'
                }`}
                type="text"
                value={row.values[primaryCol.key] || ''}
                placeholder={`${primaryCol.placeholder}${primaryCol.required ? ' *' : ''}`}
                onChange={(e) => onChange(row.id, primaryCol.key, e.target.value)}
              />
            )}

            {badgeCols.length > 0 && (
              <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
                {badgeCols.map((c) => {
                  const missing = c.required && !(row.values[c.key] || '').trim()
                  return (
                  <label
                    key={c.key}
                    className={`flex w-full items-center gap-2 rounded-[10px] border py-1.5 pl-3 pr-2 transition-colors focus-within:border-teal hover:border-[#c9bda6] ${
                      missing ? 'border-[#e3b3ba] bg-[rgba(217,91,104,0.08)]' : 'border-line bg-[#F7F3EA]'
                    } ${c.readOnly ? 'items-center' : ''}`}
                  >
                    <span className="flex-none self-center whitespace-nowrap font-sans text-[11px] tracking-wide text-[#8E9398]">{c.label}{c.required && ' *'}</span>
                    {c.readOnly ? (
                      <span
                        className="block flex-1 truncate rounded-lg border border-solid border-[#ddd3c0] bg-cream px-2.5 py-1 font-sans text-[12.5px] font-medium text-ink outline-none focus:whitespace-normal focus:[overflow-wrap:anywhere] focus:break-words"
                        title={row.values[c.key] || ''}
                        tabIndex={0}
                      >
                        {row.values[c.key] || c.placeholder}
                      </span>
                    ) : c.type === 'date' ? (
                      <input
                        className="flex-1 rounded-lg border border-solid border-[#ddd3c0] bg-surface px-2.5 py-1 font-sans text-xs text-ink"
                        type="date"
                        value={row.values[c.key] || ''}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                      />
                    ) : (
                      <textarea
                        className="block flex-1 resize-none overflow-hidden truncate whitespace-nowrap rounded-lg border border-dashed border-[#cfc6b4] bg-surface px-2.5 py-1 font-sans text-[12.5px] font-medium leading-snug text-ink placeholder:font-normal placeholder:text-[#a49c8e] hover:border-teal focus:overflow-visible focus:whitespace-pre-wrap focus:text-clip focus:[overflow-wrap:anywhere] focus:break-words focus:border-solid focus:border-teal focus:outline-none focus:ring-[3px] focus:ring-teal/10"
                        rows={1}
                        value={row.values[c.key] || ''}
                        placeholder={c.placeholder}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                        onFocus={(e) => resizeBadgeInput(e.target, true)}
                        onBlur={(e) => resizeBadgeInput(e.target, false)}
                        onInput={(e) => {
                          if (document.activeElement === e.target) resizeBadgeInput(e.target, true)
                        }}
                      />
                    )}
                  </label>
                )})}
              </div>
            )}

            {longCols.length > 0 && (
              <div className="flex flex-col gap-2.5">
                {longCols.map((c) => (
                  <label key={c.key} className="flex flex-col gap-1">
                    <span className="font-sans text-[11px] font-semibold uppercase tracking-wide text-[#8E9398]">
                      {c.label}
                      {c.code ? <span className="ml-1 font-medium normal-case tracking-normal">({c.code})</span> : null}
                      {c.required ? ' *' : ''}
                    </span>
                    <textarea
                      className="box-border min-h-[44px] w-full resize-y rounded-lg border border-line bg-cream px-3 py-2 font-sans text-[13.5px] leading-relaxed text-ink placeholder:text-[#a49c8e] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                      rows={3}
                      value={row.values[c.key] || ''}
                      placeholder={c.placeholder}
                      onChange={(e) => onChange(row.id, c.key, e.target.value)}
                    />
                  </label>
                ))}
              </div>
            )}

            {renderGroupFooter && (
              <div>
                {renderGroupFooter(row, ri)}
              </div>
            )}
          </div>
              )
            })()}
          </div>
        </div>
      )}
    </div>
  )
}