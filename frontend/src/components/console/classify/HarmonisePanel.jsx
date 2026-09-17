'use client'

import { useEffect } from 'react'
import { AlertTriangle, Check, Minus } from 'lucide-react'
import { isOccupationColumn, rowMapped } from '../../../lib/classifyColumns'

const saveBtnClass = 'h-8 rounded-md border-0 px-3.5 text-[12.5px] font-semibold text-white transition-colors bg-teal hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'
const ghostBtnClass = 'flex h-8 items-center rounded-md border border-line bg-white px-2.5 text-[12px] font-semibold text-ink-soft hover:border-teal/35 hover:text-teal disabled:cursor-default disabled:opacity-50'
const fieldClass = 'box-border h-7 w-full min-w-0 rounded border border-line bg-cream px-1.5 font-sans text-[12px] text-ink placeholder:text-[#c2b8a6] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal'

/**
 * One list row per clubbed column family. Verify once applies codes to every
 * related table; the sidebar shows "+N to be harmonized" instead of N rows.
 */
export default function HarmonisePanel({
  classifiedColumns,
  columnCodes,
  harmoniseClubs,
  harmRows,
  savedCodes,
  openRule,
  onSelectEntry,
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
  const rowsFor = (club) => harmRows[club.id] || columnCodes[club.sourceName] || []
  const clubMeta = (club) => {
    const rows = rowsFor(club)
    const skipped = ruleState[club.id] === 'skip'
    const verified = Boolean(aliasVerified[club.id])
    const mappedCount = rows.filter(rowMapped).length
    const fullyMapped = rows.length > 0 && mappedCount === rows.length
    const occ = isOccupationColumn(club.sourceName) || isOccupationColumn(club.name)
    const ncoOpen = occ && columnNeedsNcoReview(club.sourceName) && !verified
    const pendingVerify = !verified && !skipped
    const done = skipped || (verified && fullyMapped)
    const ready = done && !pendingVerify
    const status = skipped ? 'Skipped' : pendingVerify || ncoOpen || !done ? 'Needs review' : 'Ready'
    return {
      rows,
      skipped,
      verified,
      mappedCount,
      fullyMapped,
      occ,
      ncoOpen,
      reviewCount: ncoOpen ? ncoReviewCount(club.sourceName) : 0,
      pendingVerify,
      done,
      ready,
      status,
      relatedCount: club.relatedCount || (club.members || []).length,
      rowsDirty: JSON.stringify(rows) !== JSON.stringify(savedCodes[club.sourceName]),
    }
  }

  const mappedLists = classifiedColumns.filter((c) => columnMapped(c.name)).length
  const pendingCount = harmoniseClubs.filter((c) => {
    const m = clubMeta(c)
    return !m.ready && !m.skipped
  }).length

  const verifiableClubs = harmoniseClubs.filter((c) => {
    const m = clubMeta(c)
    return !m.skipped && m.fullyMapped && (m.pendingVerify || m.rowsDirty || harmDirty[c.id])
  })

  useEffect(() => {
    if (!harmoniseClubs.length) return
    if (openRule && harmoniseClubs.some((c) => c.id === openRule)) return
    const firstPending = harmoniseClubs.find((c) => {
      const m = clubMeta(c)
      return !m.ready && !m.skipped
    })
    onSelectEntry((firstPending || harmoniseClubs[0]).id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [harmoniseClubs, openRule])

  const active = harmoniseClubs.find((c) => c.id === openRule) || null
  const activeMeta = active ? clubMeta(active) : null

  const verifyAllReady = () => {
    verifiableClubs.forEach((club) => {
      onVerifyAndSave(club, rowsFor(club))
    })
  }

  return (
    <div className="overflow-hidden rounded-[10px] border border-line bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-[18px] py-2.5">
        <span className="text-[14px] font-semibold text-ink">Harmonisation</span>
        <span className="rounded-full bg-cream px-2 py-0.5 text-[11px] font-semibold tabular-nums text-ink-soft">
          {mappedLists}/{classifiedColumns.length} mapped
        </span>
        {harmoniseClubs.length > 0 && (
          <span className="text-[12px] text-[#8E9398]">
            · {pendingCount} club{pendingCount === 1 ? '' : 's'} to review
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {verifiableClubs.length > 0 && (
            <button type="button" className={saveBtnClass} onClick={verifyAllReady}>
              Verify all ready ({verifiableClubs.length})
            </button>
          )}
        </div>
      </div>

      {harmoniseClubs.length === 0 && (
        <div className="px-[18px] py-3 text-[12.5px] text-ink-soft">
          No other classification columns besides the chips above.
        </div>
      )}

      {harmoniseClubs.length > 0 && (
        <div className="grid min-h-[320px] grid-cols-1 md:grid-cols-[minmax(220px,280px)_1fr]">
          <div className="max-h-[min(520px,60vh)] overflow-y-auto border-b border-line md:border-b-0 md:border-r md:border-line">
            {harmoniseClubs.map((club) => {
              const m = clubMeta(club)
              const selected = club.id === openRule
              return (
                <button
                  key={club.id}
                  type="button"
                  className={`flex w-full items-center gap-2 border-b border-[#f1ebdf] px-3 py-2.5 text-left transition-all duration-dhara ease-dhara last:border-b-0 ${
                    selected ? 'bg-sage/60' : 'bg-white hover:bg-[#FBF7EF]'
                  }`}
                  onClick={() => onSelectEntry(club.id)}
                >
                  <span className={`h-1.5 w-1.5 flex-none rounded-full ${m.ready ? 'bg-green' : 'bg-[rgba(242,194,48,0.85)]'}`} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12.5px] font-semibold text-ink">{club.name}</div>
                    <div className="truncate text-[10.5px] text-[#8E9398]">
                      {m.relatedCount > 0
                        ? `+${m.relatedCount} to be harmonized`
                        : `${m.mappedCount}/${m.rows.length} mapped`}
                    </div>
                  </div>
                  <span
                    className={`flex-none rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                      m.ready
                        ? 'bg-sage text-[#3d7a3d]'
                        : m.skipped
                          ? 'bg-cream text-ink-soft'
                          : 'bg-[rgba(242,194,48,0.22)] text-[#9a7413]'
                    }`}
                  >
                    {m.status === 'Needs review' ? 'Review' : m.status}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="flex min-w-0 flex-col px-[18px] py-3">
            {!active || !activeMeta ? (
              <div className="py-8 text-[12.5px] text-ink-soft">Select a column family to review.</div>
            ) : (
              <div key={active.id} className="dhara-group-panel flex min-w-0 flex-col">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold text-ink">
                      {active.name}
                      {activeMeta.relatedCount > 0 && (
                        <span className="ml-1.5 text-[11.5px] font-semibold text-ink-soft">
                          +{activeMeta.relatedCount} to be harmonized
                        </span>
                      )}
                    </div>
                  </div>
                  <span
                    className={`flex-none rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${
                      activeMeta.ready
                        ? 'bg-sage text-[#3d7a3d]'
                        : activeMeta.skipped
                          ? 'bg-cream text-ink-soft'
                          : 'bg-[rgba(242,194,48,0.22)] text-[#9a7413]'
                    }`}
                  >
                    {activeMeta.status}
                  </span>
                  <button
                    type="button"
                    className={ghostBtnClass}
                    onClick={() => onToggleSkip(active.id)}
                  >
                    {activeMeta.skipped ? 'Unskip' : 'Skip'}
                  </button>
                  <button
                    type="button"
                    className={saveBtnClass}
                    disabled={activeMeta.verified && !harmDirty[active.id] && !activeMeta.rowsDirty}
                    onClick={() => onVerifyAndSave(active, activeMeta.rows)}
                  >
                    {activeMeta.verified && !harmDirty[active.id]
                      ? 'Verified'
                      : activeMeta.relatedCount > 1
                        ? `Verify & save all ${activeMeta.relatedCount}`
                        : 'Verify & save'}
                  </button>
                  {!activeMeta.pendingVerify && activeMeta.rowsDirty && (
                    <button
                      type="button"
                      className={ghostBtnClass}
                      onClick={() => onSaveChanges(active, activeMeta.rows)}
                    >
                      Save changes
                    </button>
                  )}
                </div>
                <div className="mb-2 text-[11.5px] text-ink-soft">
                  {activeMeta.mappedCount}/{activeMeta.rows.length} mapped · value fixed · one verify updates all related tables
                </div>

                <div className="max-h-[min(320px,45vh)] overflow-auto rounded-md border border-[#cfc6b4]">
                  <table className="w-full min-w-[560px] table-fixed border-collapse text-left">
                    <thead className="sticky top-0 z-[1]">
                      <tr className="bg-[#F4EFE3] text-[10.5px] uppercase tracking-wide text-[#8E9398]">
                        <th className="w-8 border-b border-[#d7cdb9] px-1.5 py-1.5 text-center font-semibold">#</th>
                        <th className="w-[34%] border-b border-[#d7cdb9] px-2 py-1.5 font-semibold">
                          Value
                          <span className="ml-1 font-semibold normal-case tracking-normal text-[#c36637]">fixed</span>
                        </th>
                        <th className="w-[22%] border-b border-[#d7cdb9] px-2 py-1.5 font-semibold">Code</th>
                        <th className="w-[34%] border-b border-[#d7cdb9] px-2 py-1.5 font-semibold">Definition</th>
                        <th className="w-10 border-b border-[#d7cdb9] px-1 py-1.5 text-center font-semibold">Ok</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeMeta.rows.map((row, i) => {
                        const m = activeMeta.occ
                          ? (ncoMatchesByCol[active.sourceName] || {})[row.value]
                          : null
                        const filled = rowMapped(row)
                        const rowReview = Boolean(m?.needs_manual_review) && !activeMeta.verified
                        return (
                          <tr className="border-b border-[#f1ebdf] bg-white last:border-b-0" key={row.value || i}>
                            <td className="bg-[#FBF7EF] px-1.5 py-0.5 text-center text-[11px] tabular-nums text-[#a49c8e]">
                              {i + 1}
                            </td>
                            <td className="bg-[#FBF7EF] px-2 py-0.5 align-middle" title="From the data — not editable">
                              <div className="truncate text-[12.5px] font-medium text-ink">{row.value}</div>
                              {m && (
                                <div className="truncate text-[10px] leading-tight text-[#a49c8e]">
                                  {m.level}
                                  {rowReview ? ' · review' : ''}
                                  {m.codes?.length > 1 ? ' · both valid' : ''}
                                </div>
                              )}
                            </td>
                            <td className="px-1 py-0.5 align-middle">
                              <input
                                className={fieldClass}
                                type="text"
                                value={row.code}
                                placeholder="Code"
                                title="Editable"
                                onChange={(e) => onFieldChange(active, i, 'code', e.target.value)}
                              />
                            </td>
                            <td className="px-1 py-0.5 align-middle">
                              <input
                                className={fieldClass}
                                type="text"
                                value={row.definition}
                                placeholder="Definition"
                                title="Editable"
                                onChange={(e) => onFieldChange(active, i, 'definition', e.target.value)}
                              />
                            </td>
                            <td className={`px-1 py-0.5 text-center ${rowReview ? 'text-[#9a7413]' : ''}`}>
                              {rowReview ? (
                                <AlertTriangle className="mx-auto h-3.5 w-3.5 text-[#c45c4a]" strokeWidth={2.25} aria-hidden />
                              ) : filled ? (
                                <Check className="mx-auto h-3.5 w-3.5 text-[#3d7a3d]" strokeWidth={2.5} aria-hidden />
                              ) : (
                                <Minus className="mx-auto h-3.5 w-3.5 text-ink-soft" strokeWidth={2} aria-hidden />
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
