'use client'

import { isOccupationColumn, relatedAliasCount } from '../../../lib/classifyColumns'
import NcoSuggestPanel from './NcoSuggestPanel'

const saveBtnClass = 'h-9 rounded-md border-0 px-4 text-[13px] font-semibold text-white transition-colors bg-teal hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'
const fieldClass = 'box-border h-8 w-full min-w-0 rounded border border-line bg-cream px-2 font-sans text-[12.5px] text-ink focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal'

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

  const panelKey = `${column._metadataId || ''}:${column.name}`

  return (
    <div key={panelKey} className="dhara-group-panel">
      <div className="flex items-center justify-between gap-3 px-[18px] pb-2 pt-3.5">
        <div className="min-w-0">
          <span className="text-[16px] font-bold text-ink">{column.name}</span>
          {column.concept && column.concept !== column.name && (
            <span className="ml-2 text-[12.5px] text-ink-soft">{column.concept}</span>
          )}
          <div className="mt-0.5 text-[12px] text-ink-soft">
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
            className="h-8 flex-none rounded-md border-0 bg-teal px-3 text-[12.5px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
            disabled={fillAiLoading || !codes.length}
            onClick={onFillAi}
          >
            {fillAiLoading ? 'Filling…' : 'Fill with AI'}
          </button>
        ) : (
          <button
            type="button"
            className="h-8 flex-none rounded-md border-0 bg-teal px-3 text-[12.5px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
            disabled={ncoLoading || codes.length === 0}
            onClick={onSuggestNco}
          >
            {ncoLoading ? 'Matching…' : 'Suggest NCO codes'}
          </button>
        )}
      </div>

      <div className="mx-[18px] mb-3 max-h-[min(360px,50vh)] overflow-auto rounded-md border border-[#cfc6b4]">
        <table className="w-full min-w-[520px] table-fixed border-collapse text-left">
          <thead className="sticky top-0 z-[1]">
            <tr className="bg-[#F4EFE3] text-[11px] uppercase tracking-wide text-[#8E9398]">
              <th className="w-[28%] border-b border-[#d7cdb9] px-2.5 py-1.5 font-semibold">Code</th>
              <th className="w-[32%] border-b border-[#d7cdb9] px-2.5 py-1.5 font-semibold">Value</th>
              <th className="w-[40%] border-b border-[#d7cdb9] px-2.5 py-1.5 font-semibold">Definition</th>
            </tr>
          </thead>
          <tbody>
            {codes.map((row, i) => (
              <tr className="border-b border-[#f1ebdf] bg-white last:border-b-0" key={i}>
                <td className="px-2 py-1 align-middle">
                  <input
                    className={fieldClass}
                    type="text"
                    value={row.code}
                    onChange={(e) => onCodeFieldChange(i, 'code', e.target.value)}
                    title={row.code}
                  />
                </td>
                <td className="px-2.5 py-1 align-middle text-[12.5px] font-medium leading-snug text-ink">
                  <span className="line-clamp-2" title={row.value}>{row.value}</span>
                </td>
                <td className="px-2 py-1 align-middle">
                  <input
                    className={fieldClass}
                    type="text"
                    value={row.definition}
                    onChange={(e) => onCodeFieldChange(i, 'definition', e.target.value)}
                    title={row.definition}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between gap-3 px-[18px] pb-3.5 pt-1">
        <span className="text-[12.5px] text-ink-soft">Code and definition can be edited. Values come from the data and stay fixed.</span>
        <button className={saveBtnClass} disabled={!dirty} onClick={onSave}>Save changes</button>
      </div>

      {occupation && ncoPanelOpen && (
        <NcoSuggestPanel codes={codes} ncoError={ncoError} ncoLoading={ncoLoading} ncoMatches={ncoMatches} />
      )}
    </div>
  )
}
