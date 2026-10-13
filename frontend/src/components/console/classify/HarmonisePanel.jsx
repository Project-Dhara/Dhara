'use client'

import { useEffect } from 'react'
import { isOccupationColumn, rowMapped } from '../../../lib/classifyColumns'

const primaryBtn =
  'inline-flex h-9 items-center justify-center rounded-md bg-teal px-4 text-[13px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'
const ghostBtn =
  'inline-flex h-9 items-center justify-center rounded-md border border-line bg-white px-3.5 text-[13px] font-semibold text-ink-soft transition-colors hover:border-teal/35 hover:text-teal disabled:cursor-default disabled:opacity-50'
const fieldClass =
  'box-border h-9 w-full min-w-0 border-0 bg-transparent px-3 font-sans text-[13px] text-ink placeholder:text-[#c2b8a6] focus:bg-white focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal'

/**
 * One list row per clubbed column family. Verify once applies codes to every
 * related table; the sidebar shows related-table count instead of N rows.
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

  const relatedLabel = (count) => {
    if (!count || count <= 1) return null
    return `${count} related tables`
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-white">
      {/* Page chrome — one quiet summary row */}
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-6 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-[15px] font-semibold tracking-tight text-ink">Harmonisation</h2>
          <p className="m-0 mt-1 text-[12.5px] leading-snug text-ink-soft">
            {mappedLists}/{classifiedColumns.length} columns mapped
            {harmoniseClubs.length > 0 && pendingCount > 0
              ? ` · ${pendingCount} left to review`
              : harmoniseClubs.length > 0
                ? ' · all clubs reviewed'
                : ''}
          </p>
        </div>
        {verifiableClubs.length > 0 && (
          <button type="button" className={primaryBtn} onClick={verifyAllReady}>
            Verify all ({verifiableClubs.length})
          </button>
        )}
      </header>

      {harmoniseClubs.length === 0 && (
        <div className="px-6 py-10 text-center text-[13px] text-ink-soft">
          Nothing left to harmonise — all classification columns are covered above.
        </div>
      )}

      {harmoniseClubs.length > 0 && (
        <div className="grid min-h-[420px] grid-cols-1 md:grid-cols-[minmax(200px,240px)_1fr]">
          {/* Club list — name + quiet meta; status via dot only */}
          <nav
            className="flex max-h-[min(560px,65vh)] flex-col gap-0.5 overflow-y-auto border-b border-line bg-[#FBF9F4] p-3 md:border-b-0 md:border-r md:border-line"
            aria-label="Column families"
          >
            {harmoniseClubs.map((club) => {
              const m = clubMeta(club)
              const selected = club.id === openRule
              const related = relatedLabel(m.relatedCount)
              return (
                <button
                  key={club.id}
                  type="button"
                  aria-current={selected ? 'true' : undefined}
                  className={`flex w-full items-start gap-3 rounded-lg px-3 py-3 text-left transition-colors duration-dhara ease-dhara ${
                    selected
                      ? 'bg-sage/70 shadow-[inset_0_0_0_1px_rgba(23,107,107,0.28)]'
                      : 'hover:bg-sage/50'
                  }`}
                  onClick={() => onSelectEntry(club.id)}
                >
                  <span
                    className={`mt-1.5 h-2 w-2 flex-none rounded-full ${
                      m.ready ? 'bg-green' : m.skipped ? 'bg-[#cfc6b4]' : 'bg-[rgba(242,194,48,0.9)]'
                    }`}
                    title={m.status}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold capitalize text-ink">
                      {club.name}
                    </span>
                    <span className="mt-0.5 block truncate text-[11.5px] text-[#8E9398]">
                      {related || `${m.mappedCount} of ${m.rows.length} mapped`}
                      {m.skipped ? ' · skipped' : m.ready ? ' · ready' : ''}
                    </span>
                  </span>
                </button>
              )
            })}
          </nav>

          {/* Active club */}
          <section className="flex min-w-0 flex-col px-6 py-5">
            {!active || !activeMeta ? (
              <div className="flex flex-1 items-center justify-center py-12 text-[13px] text-ink-soft">
                Select a column family to review.
              </div>
            ) : (
              <div key={active.id} className="dhara-group-panel flex min-h-0 flex-1 flex-col gap-4">
                <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
                  <div className="min-w-0 max-w-xl">
                    <h3 className="m-0 truncate text-[17px] font-semibold capitalize tracking-tight text-ink">
                      {active.name}
                    </h3>
                    <p className="m-0 mt-1.5 text-[12.5px] leading-relaxed text-ink-soft">
                      {activeMeta.mappedCount} of {activeMeta.rows.length} values mapped
                      {relatedLabel(activeMeta.relatedCount)
                        ? ` · verify once for ${relatedLabel(activeMeta.relatedCount)}`
                        : ''}
                      {activeMeta.skipped ? ' · skipped' : activeMeta.ready ? ' · verified' : ''}
                    </p>
                  </div>
                  <div className="flex flex-none flex-wrap items-center gap-2">
                    <button
                      type="button"
                      className={ghostBtn}
                      onClick={() => onToggleSkip(active.id)}
                    >
                      {activeMeta.skipped ? 'Unskip' : 'Skip'}
                    </button>
                    {!activeMeta.pendingVerify && activeMeta.rowsDirty && (
                      <button
                        type="button"
                        className={ghostBtn}
                        onClick={() => onSaveChanges(active, activeMeta.rows)}
                      >
                        Save changes
                      </button>
                    )}
                    <button
                      type="button"
                      className={primaryBtn}
                      disabled={activeMeta.verified && !harmDirty[active.id] && !activeMeta.rowsDirty}
                      onClick={() => onVerifyAndSave(active, activeMeta.rows)}
                    >
                      {activeMeta.verified && !harmDirty[active.id]
                        ? 'Verified'
                        : activeMeta.relatedCount > 1
                          ? `Verify & save (${activeMeta.relatedCount})`
                          : 'Verify & save'}
                    </button>
                  </div>
                </div>

                <div className="max-h-[min(420px,52vh)] overflow-auto rounded-lg border border-line">
                  <table className="w-full min-w-[560px] table-fixed border-separate border-spacing-0 text-left">
                    <thead className="sticky top-0 z-[1]">
                      <tr className="bg-[#F4EFE3] text-[11px] uppercase tracking-[0.04em] text-[#8E9398]">
                        <th className="w-11 border-b border-[#d7cdb9] px-3 py-2.5 text-center font-semibold">#</th>
                        <th
                          className="w-[34%] border-b border-[#d7cdb9] border-l border-[#e8e0d0] px-3 py-2.5 font-semibold"
                          title="From the data — not editable"
                        >
                          Value
                        </th>
                        <th className="w-[18%] border-b border-[#d7cdb9] border-l border-[#e8e0d0] px-3 py-2.5 font-semibold">
                          Code
                        </th>
                        <th className="border-b border-[#d7cdb9] border-l border-[#e8e0d0] px-3 py-2.5 font-semibold">
                          Definition
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeMeta.rows.map((row, i) => {
                        const m = activeMeta.occ
                          ? (ncoMatchesByCol[active.sourceName] || {})[row.value]
                          : null
                        const rowReview = Boolean(m?.needs_manual_review) && !activeMeta.verified
                        const cellBorder = 'border-b border-[#ebe4d6]'
                        return (
                          <tr className="bg-white" key={row.value || i}>
                            <td className={`${cellBorder} bg-[#FBF7EF] px-3 py-2 text-center text-[12px] tabular-nums text-[#a49c8e]`}>
                              {i + 1}
                            </td>
                            <td
                              className={`${cellBorder} border-l border-[#ebe4d6] bg-[#FBF7EF] px-3 py-2 align-middle`}
                              title={String(row.value || '')}
                            >
                              <div className="line-clamp-2 text-[13px] font-medium leading-snug text-ink">
                                {row.value}
                              </div>
                              {m && (
                                <div className="mt-0.5 truncate text-[11px] text-[#a49c8e]">
                                  {m.level}
                                  {rowReview ? ' · needs review' : ''}
                                  {m.codes?.length > 1 ? ' · both valid' : ''}
                                </div>
                              )}
                            </td>
                            <td className={`${cellBorder} border-l border-[#ebe4d6] bg-white p-0 align-middle`}>
                              <input
                                className={fieldClass}
                                type="text"
                                value={row.code}
                                placeholder="Code"
                                title="Editable"
                                onChange={(e) => onFieldChange(active, i, 'code', e.target.value)}
                              />
                            </td>
                            <td className={`${cellBorder} border-l border-[#ebe4d6] bg-white p-0 align-middle`}>
                              <input
                                className={fieldClass}
                                type="text"
                                value={row.definition}
                                placeholder="Definition"
                                title="Editable"
                                onChange={(e) => onFieldChange(active, i, 'definition', e.target.value)}
                              />
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
