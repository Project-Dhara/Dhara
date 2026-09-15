'use client'

import { AlertTriangle, Check, ChevronDown, Minus } from 'lucide-react'
import { isOccupationColumn, rowMapped } from '../../../lib/classifyColumns'

const saveBtnClass = 'h-11 rounded-lg border-0 px-5 text-[15px] font-semibold text-white transition-colors bg-teal hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'
const cardHeadClass = 'flex items-center gap-2.5 border-b border-line px-[18px] py-3 text-[15px] font-semibold text-ink'
const cardNoteClass = 'text-xs font-normal text-[#8E9398]'

/**
 * "Harmonisation" card: every classification column aliased across metadata
 * groups (or an occupation column needing NCO review) as a collapsible
 * verify-and-save row. All state lives in Classify.jsx; this component only
 * renders it and forwards the same callbacks the inline JSX used to call.
 */
export default function HarmonisePanel({
  classifiedColumns,
  columnCodes,
  harmoniseEntries,
  harmRows,
  savedCodes,
  openRule,
  onToggleOpen,
  ruleState,
  onToggleSkip,
  aliasVerified,
  harmDirty,
  ncoMatchesByCol,
  onVerifyAndSave,
  onSaveChanges,
  onFieldChange,
}) {
  const columnMapped = (name) => {
    const rows = columnCodes[name] || []
    return rows.length > 0 && rows.every(rowMapped)
  }
  const columnNeedsNcoReview = (sourceName) => {
    const matches = ncoMatchesByCol[sourceName]
    if (!matches) return false
    return Object.values(matches).some((m) => m && (m.needs_manual_review || m.auto_fill === false || m.confidence !== 'high'))
  }
  const ncoReviewCount = (sourceName) => {
    const matches = ncoMatchesByCol[sourceName] || {}
    const rows = columnCodes[sourceName] || []
    return rows.filter((row) => {
      const m = matches[row.value]
      return m && (m.needs_manual_review || m.auto_fill === false || m.confidence !== 'high')
    }).length
  }
  const entryReady = (entry) => {
    if (ruleState[entry.id] === 'skip') return true
    if (!aliasVerified[entry.id]) return false
    const rows = harmRows[entry.id] || columnCodes[entry.sourceName] || []
    return rows.length > 0 && rows.every(rowMapped)
  }
  const entryNeedsVerify = () => true

  return (
    <div className="overflow-hidden rounded-[10px] border border-line bg-white">
      <div className={cardHeadClass}>
        <span>Harmonisation</span>
        <span className={cardNoteClass}>
          {classifiedColumns.filter((c) => columnMapped(c.name)).length} of {classifiedColumns.length} lists mapped
          {harmoniseEntries.length
            ? ` · ${harmoniseEntries.length} other column${harmoniseEntries.length === 1 ? '' : 's'} to verify`
            : ''}
        </span>
      </div>
      {harmoniseEntries.length === 0 && (
        <div className="border-b border-[#f1ebdf] last:border-b-0">
          <div className="flex items-center gap-3 px-[18px] py-3.5" style={{ cursor: 'default' }}>
            <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
              <div className="text-[13px] text-ink-soft">No other classification columns besides the chips above.</div>
            </div>
          </div>
        </div>
      )}
      {harmoniseEntries.map((entry) => {
        const { id, name, sourceName, isAlias } = entry
        const rows = harmRows[id] || columnCodes[sourceName] || []
        const open = openRule === id
        const skipped = ruleState[id] === 'skip'
        const mappedCount = rows.filter(rowMapped).length
        const occ = isOccupationColumn(sourceName) || isOccupationColumn(name)
        const needsVerify = entryNeedsVerify(entry)
        const verified = Boolean(aliasVerified[id])
        const pendingVerify = needsVerify && !verified && !skipped
        const ncoOpen = occ && columnNeedsNcoReview(sourceName) && !verified
        const reviewCount = ncoOpen ? ncoReviewCount(sourceName) : 0
        const rowsDirty = JSON.stringify(rows) !== JSON.stringify(savedCodes[sourceName])
        const done = entryReady(entry)
        const detail = isAlias
          ? (name === sourceName
            ? `Same column in another group — review and verify`
            : `Related to ${sourceName} — review and verify`)
          : occ
            ? 'Suggested NCO codes — review and verify'
            : 'Value → code and definition from classification'
        const status = skipped ? 'Skipped' : pendingVerify || ncoOpen || !done ? 'Needs review' : 'Ready'
        const countLabel = occ && reviewCount > 0
          ? `${reviewCount} needs review`
          : `${mappedCount} of ${rows.length} mapped`
        return (
          <div className="border-b border-[#f1ebdf] last:border-b-0" key={id}>
            <div className="flex cursor-pointer items-center gap-3 px-[18px] py-[13px] transition-colors hover:bg-[#FBF7EF]" onClick={() => onToggleOpen(id)}>
              <span className={`h-2 w-2 flex-none rounded-full ${done && !pendingVerify ? 'bg-green' : 'bg-[rgba(242,194,48,0.7)]'}`} />
              <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
                <div className="text-sm font-semibold text-ink">{name}</div>
                <div className="text-[13px] text-ink-soft">{detail}</div>
              </div>
              <span className={`whitespace-nowrap text-xs font-semibold ${done && !pendingVerify ? 'text-[#3d7a3d]' : 'text-[#9a7413]'}`}>
                {status}
              </span>
              <span className="whitespace-nowrap text-xs text-[#8E9398]">{countLabel}</span>
              <span className={`text-[#8E9398] transition-transform duration-300 ${open ? 'rotate-180' : ''}`}>
                <ChevronDown className="h-4 w-4" strokeWidth={2} aria-hidden />
              </span>
            </div>
            <div className="grid transition-[grid-template-rows] duration-300 ease-in-out" style={{ gridTemplateRows: open ? '1fr' : '0fr' }}>
              <div
                className={`min-h-0 overflow-hidden px-[18px] pb-4 transition-[opacity,transform] duration-300 ease-in-out ${open ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1.5 opacity-0'}`}
              >
                <div className="flex items-center gap-2 pb-2.5">
                  <button
                    type="button"
                    className="flex h-8 items-center rounded-[5px] border border-line bg-white px-3 text-[13px] font-semibold text-ink-soft"
                    onClick={() => onToggleSkip(id)}
                  >
                    {skipped ? 'Unskip' : 'Skip this column'}
                  </button>
                  {needsVerify ? (
                    <button
                      type="button"
                      className={`${saveBtnClass} h-11 !text-sm`}
                      disabled={verified && !harmDirty[id]}
                      onClick={() => onVerifyAndSave(entry, rows)}
                    >
                      {verified && !harmDirty[id] ? 'Verified' : 'Verify & save'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className={`${saveBtnClass} h-11 !text-sm`}
                      disabled={!rowsDirty}
                      onClick={() => onSaveChanges(entry, rows)}
                    >
                      Save changes
                    </button>
                  )}
                </div>
                <p className="m-0 mb-2.5 text-[13px] leading-tight text-ink-soft">
                  Value in file comes from the data and cannot be changed. Code and definition are editable.
                </p>
                <div className="overflow-hidden rounded-lg border border-[#cfc6b4]">
                  <div className="grid grid-cols-[38px_1.2fr_0.7fr_1.4fr_64px] items-stretch border-b border-[#cfc6b4] bg-[#F4EFE3] [&>div]:border-l [&>div]:border-[#e0d7c4] [&>div]:px-3 [&>div]:py-2 [&>div]:font-label [&>div]:text-[11px] [&>div]:uppercase [&>div]:tracking-wide [&>div]:text-[#6E7378] [&>div:first-child]:border-l-0 [&>div:first-child]:text-center [&>div:last-child]:px-1 [&>div:last-child]:text-center">
                    <div>#</div>
                    <div>
                      Value in file
                      <span className="mt-0.5 block text-[10px] font-semibold tracking-wide text-[#c36637]">Fixed</span>
                    </div>
                    <div>
                      Code
                      <span className="mt-0.5 block text-[10px] font-semibold tracking-wide text-[#3d7a3d]">Editable</span>
                    </div>
                    <div>
                      Definition
                      <span className="mt-0.5 block text-[10px] font-semibold tracking-wide text-[#3d7a3d]">Editable</span>
                    </div>
                    <div>Match</div>
                  </div>
                  {rows.map((row, i) => {
                    const m = occ ? (ncoMatchesByCol[sourceName] || {})[row.value] : null
                    const filled = rowMapped(row)
                    const rowReview = Boolean(m?.needs_manual_review) && !verified
                    return (
                      <div className="grid grid-cols-[38px_1.2fr_0.7fr_1.4fr_64px] items-stretch border-b border-[#f1ebdf] last:border-b-0" key={row.value || i}>
                        <div className="flex items-center justify-center self-stretch bg-[#FBF7EF] text-[11px] text-[#a49c8e]">{i + 1}</div>
                        <div className="flex cursor-default flex-col justify-center gap-0.5 border-l border-[#f1ebdf] bg-[#FBF7EF] px-3 py-2" title="From the data — not editable">
                          <div>{row.value}</div>
                          {m && (
                            <div className="text-[11.5px] text-[#a49c8e]">
                              {m.level}
                              {rowReview ? ' · review' : ''}
                              {m.codes?.length > 1 ? ' · both valid' : ''}
                            </div>
                          )}
                        </div>
                        <input
                          className="box-border h-full min-h-[40px] w-full border-0 border-l border-[#f1ebdf] bg-white px-3 py-2 font-sans text-[13px] text-ink placeholder:text-[#c2b8a6] focus:relative focus:z-[1] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                          type="text"
                          value={row.code}
                          placeholder="Edit code"
                          title="Editable"
                          onChange={(e) => onFieldChange(entry, i, 'code', e.target.value)}
                        />
                        <input
                          className="box-border h-full min-h-[40px] w-full border-0 border-l border-[#f1ebdf] bg-white px-3 py-2 font-sans text-[13px] text-ink placeholder:text-[#c2b8a6] focus:relative focus:z-[1] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                          type="text"
                          value={row.definition}
                          placeholder="Edit definition"
                          title="Editable"
                          onChange={(e) => onFieldChange(entry, i, 'definition', e.target.value)}
                        />
                        <div className={`flex items-center justify-center border-l border-[#f1ebdf] text-center text-sm leading-none ${rowReview ? 'text-[#9a7413]' : ''}`}>
                          {rowReview ? (
                            <AlertTriangle className="h-3.5 w-3.5 text-[#c45c4a]" strokeWidth={2.25} aria-hidden />
                          ) : filled ? (
                            <Check className="h-3.5 w-3.5 text-[#3d7a3d]" strokeWidth={2.5} aria-hidden />
                          ) : (
                            <Minus className="h-3.5 w-3.5 text-ink-soft" strokeWidth={2} aria-hidden />
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
