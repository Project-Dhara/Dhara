'use client'

import { useEffect, useState } from 'react'
import { isOccupationColumn, relatedAliasCount } from '../../../lib/classifyColumns'
import NcoSuggestPanel from './NcoSuggestPanel'

const saveBtnClass = 'h-9 rounded-md border-0 px-4 text-[13px] font-semibold text-white transition-colors bg-teal hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'
const fieldClass = 'box-border h-9 w-full min-w-0 border-0 bg-transparent px-2.5 font-sans text-[12.5px] text-ink focus:bg-white focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal'
const fieldMissingClass = 'box-border h-9 w-full min-w-0 border-0 bg-[#fff3d9] px-2.5 font-sans text-[12.5px] text-ink placeholder:text-[#a15c00]/70 focus:bg-[#fff0cc] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-[#e6b86a]'
const colRule = 'border-r border-[#d7cdb9]'
const rowRule = 'border-b border-[#d7cdb9]'

/**
 * Active column's editable code/value/definition table and header actions.
 * NCO suggestions open in a preview modal via a small button beside Suggest.
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
  highlightIncomplete = false,
  ncoNeedsStandard = false,
  onGoNcoSettings,
}) {
  const occupation = isOccupationColumn(column.name)
  const panelKey = `${column._metadataId || ''}:${column.name}`
  const [previewOpen, setPreviewOpen] = useState(false)

  const canPreview = Boolean(
    ncoMatches || ncoNeedsStandard || ncoError || ncoLoading || ncoPanelOpen,
  )

  // Open preview when Suggest produces results or needs Settings / AI fallback.
  useEffect(() => {
    if (!occupation) return
    if (ncoNeedsStandard || (ncoMatches && !ncoLoading) || (ncoError && !ncoLoading)) {
      setPreviewOpen(true)
    }
  }, [occupation, ncoNeedsStandard, ncoMatches, ncoLoading, ncoError])

  useEffect(() => {
    setPreviewOpen(false)
  }, [panelKey])

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
            {fillAiError ? ` · ${fillAiError}` : ''}
            {highlightIncomplete ? ' · empty fields highlighted' : ''}
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
          <div className="flex flex-none items-center gap-2">
            <button
              type="button"
              className="h-8 rounded-md border-0 bg-teal px-3 text-[12.5px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
              disabled={ncoLoading || codes.length === 0}
              onClick={onSuggestNco}
            >
              {ncoLoading ? 'Matching…' : 'Suggest NCO codes'}
            </button>
            <button
              type="button"
              className="h-8 rounded-md border border-line bg-white px-2.5 text-[12px] font-semibold text-ink-soft transition-colors hover:border-teal/40 hover:text-teal-deep disabled:cursor-default disabled:opacity-45"
              disabled={!canPreview}
              title={canPreview ? 'Show suggestion results' : 'Run Suggest NCO codes first'}
              onClick={() => setPreviewOpen(true)}
            >
              Show results
            </button>
          </div>
        )}
      </div>

      <div className="mx-[18px] mb-3 max-h-[min(360px,50vh)] overflow-auto rounded-md border border-[#cfc6b4]">
        <table className="w-full min-w-[520px] table-fixed border-separate border-spacing-0 text-left">
          <thead className="sticky top-0 z-[1]">
            <tr className="bg-[#F4EFE3] text-[11px] uppercase tracking-wide text-[#8E9398]">
              <th className={`w-[28%] ${rowRule} ${colRule} px-2.5 py-1.5 font-semibold`}>Code</th>
              <th className={`w-[32%] ${rowRule} ${colRule} px-2.5 py-1.5 font-semibold`} title="From the data — not editable">
                <span className="flex flex-col items-start gap-0.5 leading-tight">
                  <span>Value</span>
                  <span className="font-semibold normal-case tracking-normal text-[#c36637]">fixed</span>
                </span>
              </th>
              <th className={`w-[40%] ${rowRule} px-2.5 py-1.5 font-semibold`}>Definition</th>
            </tr>
          </thead>
          <tbody>
            {codes.map((row, i) => {
              const missingCode = highlightIncomplete && !String(row.code || '').trim()
              const missingDefinition = highlightIncomplete && !String(row.definition || '').trim()
              return (
                <tr className="bg-white" key={i}>
                  <td className={`${rowRule} ${colRule} p-0 align-middle ${missingCode ? 'bg-[#fff3d9]' : 'bg-white'}`}>
                    <input
                      className={missingCode ? fieldMissingClass : fieldClass}
                      type="text"
                      value={row.code}
                      onChange={(e) => onCodeFieldChange(i, 'code', e.target.value)}
                      title={row.code || (missingCode ? 'Code required' : '')}
                      placeholder={missingCode ? 'Code required' : ''}
                    />
                  </td>
                  <td className={`${rowRule} ${colRule} bg-[#FBF7EF] px-2.5 py-2 align-middle text-[12.5px] font-medium leading-snug text-ink`} title="From the data — not editable">
                    <span className="line-clamp-2" title={row.value}>{row.value}</span>
                  </td>
                  <td className={`${rowRule} p-0 align-middle ${missingDefinition ? 'bg-[#fff3d9]' : 'bg-white'}`}>
                    <input
                      className={missingDefinition ? fieldMissingClass : fieldClass}
                      type="text"
                      value={row.definition}
                      onChange={(e) => onCodeFieldChange(i, 'definition', e.target.value)}
                      title={row.definition || (missingDefinition ? 'Definition required' : '')}
                      placeholder={missingDefinition ? 'Definition required' : ''}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between gap-3 px-[18px] pb-3.5 pt-1">
        <span className="text-[12.5px] text-ink-soft">Code and definition can be edited. Values come from the data and stay fixed.</span>
        <button className={saveBtnClass} disabled={!dirty} onClick={onSave}>Save changes</button>
      </div>

      {occupation && (
        <NcoSuggestPanel
          open={previewOpen}
          onClose={() => setPreviewOpen(false)}
          codes={codes}
          ncoError={ncoError}
          ncoLoading={ncoLoading}
          ncoMatches={ncoMatches}
          needsStandard={ncoNeedsStandard}
          onGoSettings={onGoNcoSettings}
          onFillAiFallback={onFillAi}
          fillAiLoading={fillAiLoading}
        />
      )}
    </div>
  )
}
