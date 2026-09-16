'use client'

import { isOccupationColumn, relatedAliasCount } from '../../../lib/classifyColumns'
import NcoSuggestPanel from './NcoSuggestPanel'

const saveBtnClass = 'h-11 rounded-lg border-0 px-5 text-[15px] font-semibold text-white transition-colors bg-teal hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'

/**
 * Active column's editable code/value/definition table, its header
 * (Fill with AI / Suggest NCO codes), and the NCO suggestion panel below it.
 */
export default function CodeListEditor({
  column,
  codes,
  dirty,
  fillAiLoading,
  fillAiError,
  onFillAi,
  ncoLoading,
  ncoError,
  ncoMatches,
  ncoPanelOpen,
  onSuggestNco,
  onCodeFieldChange,
  onSave,
}) {
  const occupation = isOccupationColumn(column.name)

  return (
    <>
      <div className="flex items-center justify-between gap-4 px-[18px] pb-3 pt-[18px]">
        <div className="min-w-0">
          <span className="text-xl font-bold text-ink">{column.name}</span>
          {column.concept && column.concept !== column.name && (
            <span className="ml-2.5 text-sm text-ink-soft">{column.concept}</span>
          )}
          <div className="mt-0.5 text-[13px] text-ink-soft">
            {codes.length} values
            {relatedAliasCount(column) > 0
              ? ` · ${relatedAliasCount(column)} related in harmonisation`
              : column.note ? ` · ${column.note}` : ''}
            {fillAiError && !occupation ? ` · ${fillAiError}` : ''}
          </div>
        </div>
        {!occupation ? (
          <button
            type="button"
            className="h-[34px] flex-none rounded-md border-0 bg-teal px-3.5 text-[13px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
            disabled={fillAiLoading || !codes.length}
            onClick={onFillAi}
          >
            {fillAiLoading ? 'Filling…' : 'Fill with AI'}
          </button>
        ) : (
          <button
            type="button"
            className="h-[34px] flex-none rounded-md border-0 bg-teal px-3.5 text-[13px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
            disabled={ncoLoading || codes.length === 0}
            onClick={onSuggestNco}
          >
            {ncoLoading ? 'Matching…' : 'Suggest NCO codes'}
          </button>
        )}
      </div>

      <div className="mx-[18px] mb-4 overflow-hidden rounded-lg border border-[#cfc6b4]">
        <div className="grid grid-cols-[1fr_1.1fr_1.6fr] items-center gap-3.5 border-b border-[#d7cdb9] bg-[#F4EFE3] px-4 py-2.5 font-sans text-[11.5px] uppercase tracking-wide text-[#8E9398]">
          <div>Code</div><div>Value</div><div>Definition</div>
        </div>
        {codes.map((row, i) => (
          <div className="grid grid-cols-[1fr_1.1fr_1.6fr] items-center gap-3.5 border-b border-[#f1ebdf] bg-white px-4 py-2.5 last:border-b-0" key={i}>
            <input
              className="box-border h-[38px] rounded-md border border-line bg-cream px-3 font-sans text-sm text-ink focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
              type="text"
              value={row.code}
              onChange={(e) => onCodeFieldChange(i, 'code', e.target.value)}
            />
            <div className="text-sm font-semibold text-ink">{row.value}</div>
            <input
              className="box-border h-[38px] rounded-md border border-line bg-cream px-3 font-sans text-sm text-ink focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
              type="text"
              value={row.definition}
              onChange={(e) => onCodeFieldChange(i, 'definition', e.target.value)}
            />
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-4 px-[18px] pb-[18px] pt-3.5">
        <span className="text-sm text-ink-soft">Code and definition can be edited. Values come from the data and stay fixed.</span>
        <button className={saveBtnClass} disabled={!dirty} onClick={onSave}>Save changes</button>
      </div>

      {occupation && ncoPanelOpen && (
        <NcoSuggestPanel codes={codes} ncoError={ncoError} ncoLoading={ncoLoading} ncoMatches={ncoMatches} />
      )}
    </>
  )
}
