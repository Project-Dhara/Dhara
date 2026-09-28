'use client'

import { useEffect, useMemo, useState } from 'react'
import Combobox from '../ui/Combobox'

// Coral wash for required fields that are still empty.
export const REQUIRED_EMPTY_FIELD_CLASS = 'border-coral/50 bg-[rgba(217,91,104,0.08)]'
export const REQUIRED_EMPTY_INPUT_CLASS = 'border-coral/55 bg-[rgba(217,91,104,0.06)]'

// Metadata entry, one card per table/metadata group. Field set mirrors what
// the backend's /api/catalogue/batch-push accepts (see BatchReview.jsx).
// Which fields are required comes from Settings → Metadata configuration
// (merged onto these column defs in BatchReview).
// Short categorical / date fields share a wide 2-column card grid so values
// stay readable; free-text fields get their own full-width row.
export const METADATA_COLUMNS = [
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
  el.style.height = `${Math.max(expanded ? el.scrollHeight : 34, 34)}px`
}

export function applyRequiredFieldsToColumns(columns, requiredMap) {
  if (!requiredMap || typeof requiredMap !== 'object') return columns
  return columns.map((c) => ({
    ...c,
    required: c.key in requiredMap ? Boolean(requiredMap[c.key]) : Boolean(c.required),
  }))
}

export function missingRequiredSheetFields(values, columns) {
  return columns.filter((c) => c.required && !(values?.[c.key] || '').trim())
}

export default function MetadataSheetGrid({
  rows,
  columns = METADATA_COLUMNS,
  onChange,
  renderGroupFooter,
  renderGroupHeaderActions,
}) {
  const badgeCols = columns.filter((c) => c.type === 'badge' || c.type === 'date')
  const longCols = columns.filter((c) => c.type === 'long')

  const [activeIndex, setActiveIndex] = useState(0)
  useEffect(() => {
    if (activeIndex >= rows.length) setActiveIndex(Math.max(0, rows.length - 1))
  }, [rows.length, activeIndex])

  const activeRow = rows[activeIndex]
  const useDropdown = rows.length > 10
  const groupOptions = useMemo(
    () => rows.map((row, ri) => ({
      value: ri,
      label: `${ri + 1}. ${row.label || row.values?.title || `Group ${ri + 1}`}`,
    })),
    [rows],
  )

  const aiKeySet = useMemo(
    () => new Set(activeRow?.aiFilledKeys || []),
    [activeRow],
  )

  const fieldStatusLabel = (key, value) => {
    const filled = Boolean(String(value || '').trim())
    if (aiKeySet.has(key) && filled) {
      return { text: 'AI', className: 'border-teal/30 bg-[#e7f3ef] text-teal-deep', title: 'Filled by AI autofill' }
    }
    if (!filled) {
      return { text: 'Empty', className: 'border-line bg-white text-ink-muted', title: 'Not filled yet' }
    }
    if (activeRow?.autofillSkippedNoKey) {
      return { text: 'Manual', className: 'border-[#f0d6a3] bg-[#fdf0d8] text-[#a15c00]', title: 'Needs manual entry (AI autofill did not run)' }
    }
    return { text: 'Manual', className: 'border-line bg-white text-ink-soft', title: 'Entered or edited manually' }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="m-0 font-sans text-[13px] font-bold uppercase tracking-wide text-ink">Available Groups</h3>
        </div>
        {useDropdown ? (
          <div className="w-full">
            <Combobox
              options={groupOptions}
              value={activeIndex}
              onChange={(next) => setActiveIndex(Number(next))}
              placeholder="Select a group"
              ariaLabel="Select metadata group"
            />
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-x-4 gap-y-3.5 max-[900px]:grid-cols-2 max-[560px]:grid-cols-1">
            {rows.map((row, ri) => {
              const chipLabel = row.label || row.values?.title
              return (
              <button
                key={row.id}
                type="button"
                className={`dhara-tab grid min-w-0 grid-cols-[18px_1fr] items-center gap-2 rounded-full px-2.5 py-1.5 pl-2 font-sans text-[12.5px] font-medium ${
                  ri === activeIndex
                    ? 'border-teal-deep bg-teal-deep text-cream'
                    : 'border-line bg-surface text-ink-soft hover:border-teal/35 hover:bg-sage hover:text-teal-deep'
                }`}
                onClick={() => setActiveIndex(ri)}
                title={chipLabel}
              >
                <span className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-full text-[10.5px] font-bold transition-colors duration-[420ms] ${ri === activeIndex ? 'bg-cream/20 text-cream' : 'bg-[#ece4d6] text-ink-soft'}`}>{ri + 1}</span>
                <span className="line-clamp-2 min-w-0 text-center leading-tight">{chipLabel}</span>
              </button>
              )
            })}
          </div>
        )}
      </div>

      {activeRow && (
        <div key={activeRow.id} className="dhara-tab-panel flex items-start">
          <div className="min-w-0 flex-1">
            {(() => {
              const row = activeRow
              const ri = activeIndex
              return (
            <div className="flex min-w-0 flex-col gap-3 [overflow-wrap:anywhere] rounded-[10px] border border-line bg-surface p-4 px-[18px]" key={row.id}>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="flex-none font-sans text-xs text-[#8E9398]">{ri + 1}</span>
              <span className="min-w-0 flex-1 text-[15px] font-semibold text-ink" title={row.label}>
                {row.label || 'Untitled group'}
              </span>
              {row.autofillSkippedNoKey && (
                <span
                  className="flex-none rounded-md border border-[#f0d6a3] bg-[#fdf0d8] px-2 py-0.5 font-sans text-[11.5px] font-semibold text-[#a15c00]"
                  title="AI autofill did not run — fill in the fields below by hand"
                >
                  Not AI-filled
                </span>
              )}
              {!row.autofillSkippedNoKey && row.aiFilled && (
                <span
                  className="flex-none rounded-md border border-teal/30 bg-[#e7f3ef] px-2 py-0.5 font-sans text-[11.5px] font-semibold text-teal-deep"
                  title="Some fields in this group were filled by AI"
                >
                  AI auto-filled{(row.aiFilledKeys || []).length ? ` (${row.aiFilledKeys.length})` : ''}
                </span>
              )}
              {!row.autofillSkippedNoKey && row.manual && !row.aiFilled && (
                <span
                  className="flex-none rounded-md border border-[#f0d6a3] bg-[#fdf0d8] px-2 py-0.5 font-sans text-[11.5px] font-semibold text-[#a15c00]"
                  title="No metadata was auto-mapped for this group — fill in the fields below by hand"
                >
                  Not auto-mapped — fill in manually
                </span>
              )}
              {renderGroupHeaderActions && (
                <div className="ml-auto flex flex-none flex-wrap items-center gap-2">
                  {renderGroupHeaderActions(row, ri)}
                </div>
              )}
            </div>

            {badgeCols.length > 0 && (
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {badgeCols.map((c) => {
                  const missing = c.required && !(row.values[c.key] || '').trim()
                  const status = fieldStatusLabel(c.key, row.values[c.key])
                  return (
                  <label
                    key={c.key}
                    className={`flex w-full min-w-0 flex-col gap-1 rounded-[10px] border px-3 py-2 transition-colors focus-within:border-teal hover:border-[#c9bda6] ${
                      missing ? REQUIRED_EMPTY_FIELD_CLASS : 'border-line bg-[#F7F3EA]'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-label text-[11px] tracking-wide text-[#8E9398]">{c.label}{c.required && ' *'}</span>
                      <span
                        className={`flex-none rounded px-1.5 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide ${status.className}`}
                        title={status.title}
                      >
                        {status.text}
                      </span>
                    </span>
                    {c.readOnly ? (
                      <span
                        className="block min-h-[34px] w-full [overflow-wrap:anywhere] break-words rounded-lg border border-solid border-line bg-cream px-2.5 py-1.5 font-sans text-[13px] font-medium leading-snug text-ink"
                        title={row.values[c.key] || ''}
                        tabIndex={0}
                      >
                        {row.values[c.key] || c.placeholder}
                      </span>
                    ) : c.type === 'date' ? (
                      <input
                        className="box-border h-[34px] w-full rounded-lg border border-solid border-line bg-surface px-2.5 font-sans text-[13px] text-ink"
                        type="date"
                        value={row.values[c.key] || ''}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                        aria-required={c.required || undefined}
                      />
                    ) : (
                      <textarea
                        className="box-border block min-h-[34px] w-full resize-none overflow-hidden whitespace-pre-wrap break-words rounded-lg border border-dashed border-[#cfc6b4] bg-surface px-2.5 py-1.5 font-sans text-[13px] font-medium leading-snug text-ink placeholder:font-normal placeholder:text-[#a49c8e] hover:border-teal focus:border-solid focus:border-teal focus:outline-none focus:ring-[3px] focus:ring-teal/10"
                        rows={1}
                        value={row.values[c.key] || ''}
                        placeholder={c.placeholder}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                        onInput={(e) => resizeBadgeInput(e.target, true)}
                        ref={(el) => resizeBadgeInput(el, true)}
                        aria-required={c.required || undefined}
                      />
                    )}
                  </label>
                )})}
              </div>
            )}

            {longCols.length > 0 && (
              <div className="flex flex-col gap-2.5">
                {longCols.map((c) => {
                  const missing = c.required && !(row.values[c.key] || '').trim()
                  const status = fieldStatusLabel(c.key, row.values[c.key])
                  return (
                  <label key={c.key} className="flex flex-col gap-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-sans text-[11px] font-semibold uppercase tracking-wide text-[#8E9398]">
                        {c.label}
                        {c.code ? <span className="ml-1 font-medium normal-case tracking-normal">({c.code})</span> : null}
                        {c.required ? ' *' : ''}
                      </span>
                      <span
                        className={`flex-none rounded px-1.5 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide ${status.className}`}
                        title={status.title}
                      >
                        {status.text}
                      </span>
                    </span>
                    <textarea
                      className={`box-border min-h-[44px] w-full resize-y rounded-lg border px-3 py-2 font-sans text-[13.5px] leading-relaxed text-ink placeholder:text-[#a49c8e] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal ${
                        missing ? REQUIRED_EMPTY_INPUT_CLASS : 'border-line bg-cream'
                      }`}
                      rows={3}
                      value={row.values[c.key] || ''}
                      placeholder={c.placeholder}
                      onChange={(e) => onChange(row.id, c.key, e.target.value)}
                      aria-required={c.required || undefined}
                    />
                  </label>
                  )
                })}
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
