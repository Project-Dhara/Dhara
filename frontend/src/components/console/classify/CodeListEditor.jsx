'use client'

import { useEffect, useRef, useState } from 'react'
import { isLgdColumn, isOccupationColumn, relatedAliasCount } from '../../../lib/classifyColumns'
import NcoSuggestPanel from './NcoSuggestPanel'
import LgdSuggestPanel from './LgdSuggestPanel'

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
  ncoRetrievalMode = '',
  ncoMatches,
  ncoStage = '',
  ncoProgress = null,
  ncoWaitingMessage = '',
  ncoPanelOpen,
  onSuggestNco,
  onStopWaitingNco,
  lgdLoading = false,
  lgdError = '',
  lgdMatches = null,
  lgdPanelOpen = false,
  onSuggestLgd,
  onPickLgdCandidate,
  onConfirmNcoPicks,
  onNcoPreviewClose,
  onCodeFieldChange,
  onSave,
  highlightIncomplete = false,
  ncoNeedsStandard = false,
  onGoNcoSettings,
}) {
  const occupation = isOccupationColumn(column.name)
  const geography = !occupation && isLgdColumn(column.name)
  const panelKey = `${column._metadataId || ''}:${column.name}`
  const [previewOpen, setPreviewOpen] = useState(false)
  const wasNcoLoading = useRef(false)
  const previewDismissedRef = useRef(false)

  const openPreview = () => {
    previewDismissedRef.current = false
    setPreviewOpen(true)
  }

  const closePreview = () => {
    previewDismissedRef.current = true
    setPreviewOpen(false)
  }

  const fieldFillCounts = (field) => {
    let filled = 0
    for (const row of codes || []) {
      if (String(row?.[field] ?? '').trim()) filled += 1
    }
    const total = (codes || []).length
    return { filled, notFilled: Math.max(0, total - filled) }
  }
  const codeCounts = fieldFillCounts('code')
  const definitionCounts = fieldFillCounts('definition')
  const fillLabel = (counts) => (
    `Filled: ${counts.filled}, Not filled: ${counts.notFilled}`
  )

  const canPreview = occupation
    ? Boolean(ncoMatches || ncoNeedsStandard || ncoError || ncoLoading || ncoPanelOpen)
    : geography
      ? Boolean(lgdMatches || lgdError || lgdLoading || lgdPanelOpen)
      : false

  // Open on Suggest start/finish / needs Settings — never reopen solely because
  // Confirm updated ncoMatches while the steward already closed the modal.
  useEffect(() => {
    if (!occupation) return
    if (ncoNeedsStandard) {
      previewDismissedRef.current = false
      setPreviewOpen(true)
      return
    }
    if (ncoLoading) {
      previewDismissedRef.current = false
      setPreviewOpen(true)
    }
    if (wasNcoLoading.current && !ncoLoading && (ncoMatches || ncoError) && !previewDismissedRef.current) {
      setPreviewOpen(true)
    }
    wasNcoLoading.current = Boolean(ncoLoading)
  }, [occupation, ncoNeedsStandard, ncoLoading, ncoMatches, ncoError])

  useEffect(() => {
    if (!geography) return
    if ((lgdMatches && !lgdLoading) || (lgdError && !lgdLoading)) {
      setPreviewOpen(true)
    }
  }, [geography, lgdMatches, lgdLoading, lgdError])

  useEffect(() => {
    previewDismissedRef.current = false
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
        <div className="flex flex-none flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            className="h-8 rounded-md border-0 bg-teal px-3 text-[12.5px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
            disabled={fillAiLoading || !codes.length}
            onClick={onFillAi}
            title="Fill definitions for this column (codes stay manual unless NCO matching fills them)"
          >
            {fillAiLoading ? 'Filling…' : 'Fill with AI'}
          </button>
          {occupation && (
            <>
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
                onClick={openPreview}
              >
                Show results
              </button>
            </>
          )}
          {geography && (
            <>
              <button
                type="button"
                className="h-8 rounded-md border-0 bg-teal px-3 text-[12.5px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
                disabled={lgdLoading || codes.length === 0 || !onSuggestLgd}
                onClick={onSuggestLgd}
              >
                {lgdLoading ? 'Matching…' : 'Suggest LGD codes'}
              </button>
              <button
                type="button"
                className="h-8 rounded-md border border-line bg-white px-2.5 text-[12px] font-semibold text-ink-soft transition-colors hover:border-teal/40 hover:text-teal-deep disabled:cursor-default disabled:opacity-45"
                disabled={!canPreview}
                title={canPreview ? 'Show suggestion results' : 'Run Suggest LGD codes first'}
                onClick={openPreview}
              >
                Show results
              </button>
            </>
          )}
        </div>
      </div>

      <div className="mx-[18px] mb-3 max-h-[min(360px,50vh)] overflow-auto rounded-md border border-[#cfc6b4]">
        <table className="w-full min-w-[520px] table-fixed border-separate border-spacing-0 text-left">
          <thead className="sticky top-0 z-[1]">
            <tr className="bg-[#F4EFE3] text-[11px] uppercase tracking-wide text-[#8E9398]">
              <th
                className={`w-[28%] ${rowRule} ${colRule} px-2.5 py-1.5 font-semibold`}
                title={fillLabel(codeCounts)}
              >
                <span className="flex flex-col items-start gap-0.5 leading-tight">
                  <span>Code</span>
                  <span className="font-semibold normal-case tracking-normal text-ink-soft">
                    ({fillLabel(codeCounts)})
                  </span>
                </span>
              </th>
              <th className={`w-[32%] ${rowRule} ${colRule} px-2.5 py-1.5 font-semibold`} title="From the data — not editable">
                <span className="flex flex-col items-start gap-0.5 leading-tight">
                  <span className="normal-case tracking-normal">{column.name}</span>
                  <span className="font-semibold normal-case tracking-normal text-[#c36637]">fixed</span>
                </span>
              </th>
              <th
                className={`w-[40%] ${rowRule} px-2.5 py-1.5 font-semibold`}
                title={fillLabel(definitionCounts)}
              >
                <span className="flex flex-col items-start gap-0.5 leading-tight">
                  <span>Definition</span>
                  <span className="font-semibold normal-case tracking-normal text-ink-soft">
                    ({fillLabel(definitionCounts)})
                  </span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {codes.map((row, i) => {
              const missingCode = highlightIncomplete && !String(row.code || '').trim()
              const missingDefinition = highlightIncomplete && !String(row.definition || '').trim()
              const lgdMatch = geography ? lgdMatches?.[row.value] : null
              const lgdAmbiguous = Boolean(lgdMatch?.ambiguous) && Number(lgdMatch?.candidate_count || 0) > 1
              const ncoMatch = occupation ? ncoMatches?.[row.value] : null
              const ncoChoiceCodes = new Set()
              if (ncoMatch?.code) ncoChoiceCodes.add(String(ncoMatch.code).trim())
              for (const c of ncoMatch?.candidates || []) {
                const code = String(c?.code || '').trim()
                if (code) ncoChoiceCodes.add(code)
              }
              for (const c of ncoMatch?.alternatives || []) {
                const code = String(c?.code || '').trim()
                if (code) ncoChoiceCodes.add(code)
              }
              const rowCode = String(row.code || '').trim()
              const ncoResolved = Boolean(ncoMatch)
                && (
                  ncoMatch.chosen
                  || ncoMatch.status === 'steward_pick'
                  || (rowCode !== '' && ncoChoiceCodes.has(rowCode))
                )
              const ncoAmbiguous = Boolean(ncoMatch)
                && ncoMatch.status !== 'not_an_occupation'
                && ncoChoiceCodes.size > 1
                && !ncoResolved
              const ncoNotOccupation = ncoMatch?.status === 'not_an_occupation'
              const multiPick = lgdAmbiguous || ncoAmbiguous
              return (
                <tr className={multiPick ? 'bg-[#fff6e4]' : (ncoNotOccupation ? 'bg-[#f7f3ea]' : 'bg-white')} key={i}>
                  <td className={`${rowRule} ${colRule} p-0 align-middle ${missingCode || multiPick ? 'bg-[#fff3d9]' : 'bg-white'}`}>
                    <input
                      className={missingCode || multiPick ? fieldMissingClass : fieldClass}
                      type="text"
                      value={row.code}
                      onChange={(e) => onCodeFieldChange(i, 'code', e.target.value)}
                      title={
                        ncoNotOccupation
                          ? 'Not an occupation'
                          : (lgdAmbiguous
                            ? 'Multiple LGD codes — open Show results to pick one'
                            : (ncoAmbiguous
                              ? 'Multiple NCO codes — open Show results to pick one'
                              : (row.code || (missingCode ? 'Code required' : ''))))
                      }
                      placeholder={
                        ncoNotOccupation
                          ? 'Not an occupation'
                          : (multiPick ? 'Pick code' : (missingCode ? 'Code required' : ''))
                      }
                    />
                  </td>
                  <td className={`${rowRule} ${colRule} ${multiPick || ncoNotOccupation ? 'bg-[#fff6e4]' : 'bg-[#FBF7EF]'} px-2.5 py-2 align-middle text-[12.5px] font-medium leading-snug text-ink`} title="From the data — not editable">
                    <span className="line-clamp-2" title={row.value}>{row.value}</span>
                    {multiPick && (
                      <div className="mt-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-[#9a6700]">
                        Multiple codes
                      </div>
                    )}
                    {ncoNotOccupation && (
                      <div className="mt-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-soft">
                        Not an occupation
                      </div>
                    )}
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
          onClose={() => {
            closePreview()
            onNcoPreviewClose?.()
          }}
          codes={codes}
          ncoError={ncoError}
          ncoRetrievalMode={ncoRetrievalMode}
          ncoLoading={ncoLoading}
          ncoMatches={ncoMatches}
          ncoStage={ncoStage}
          ncoProgress={ncoProgress}
          ncoWaitingMessage={ncoWaitingMessage}
          needsStandard={ncoNeedsStandard}
          onGoSettings={onGoNcoSettings}
          onFillAiFallback={onFillAi}
          fillAiLoading={fillAiLoading}
          onConfirmPicks={(picks) => {
            // Close before parent match updates so the auto-open effect cannot reopen.
            closePreview()
            onNcoPreviewClose?.()
            onConfirmNcoPicks?.(picks)
          }}
          onStopWaiting={onStopWaitingNco}
          showStopWaiting={Boolean(ncoLoading && onStopWaitingNco)}
        />
      )}
      {geography && (
        <LgdSuggestPanel
          open={previewOpen}
          onClose={closePreview}
          codes={codes}
          lgdError={lgdError}
          lgdLoading={lgdLoading}
          lgdMatches={lgdMatches}
          onPickCandidate={onPickLgdCandidate}
        />
      )}
    </div>
  )
}
