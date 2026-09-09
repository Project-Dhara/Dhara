'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, Check, ChevronDown, Minus } from 'lucide-react'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { STATISTICS_OPTIONS, getDatasetIdConfig } from '../lib/settingsConfig'
import Button from './ui/Button'

// The classified columns (name/concept/note + code list) come from the real
// metadata-excel classification sheets, fetched below — see
// backend/catalogue.py::get_metadata_group_classifications and
// backend/metadata_excel.py::parse_classifications. Code and definition are
// editable (a steward may want to rename/annotate them); value is what was
// actually found in the source data, so it stays fixed.

function delhiProductForTheme(theme) {
  return `Delhi ${theme}`
}

function initialTaxonomy() {
  const theme = getDatasetIdConfig().statistics || STATISTICS_OPTIONS[0]
  return {
    sector: 'Demography',
    theme,
    product: delhiProductForTheme(theme),
  }
}

function isOccupationColumn(name) {
  return /occupat/i.test(name || '')
}

function rowMapped(row) {
  return Boolean(String(row?.code || '').trim()) && Boolean(String(row?.definition || '').trim())
}

function cloneCodeRows(codes) {
  return (codes || []).map((row) => ({
    code: row.code ?? '',
    value: row.value ?? '',
    definition: row.definition ?? '',
  }))
}

function codesFingerprint(codes) {
  return JSON.stringify(
    [...(codes || [])]
      .map((r) => String(r.value ?? r.code ?? '').trim().toLowerCase())
      .filter(Boolean)
      .sort()
  )
}

function pickCanonicalName(names) {
  return [...names].sort((a, b) => a.length - b.length || a.localeCompare(b))[0]
}

function collapseEquivalentColumns(columns) {
  const groups = new Map()
  columns.forEach((c) => {
    const fp = codesFingerprint(c.codes)
    const key = isOccupationColumn(c.name)
      ? `occ:${fp}`
      : (fp ? `other:${fp}` : `name:${c.name}`)
    const list = groups.get(key) || []
    list.push(c)
    groups.set(key, list)
  })
  return [...groups.values()].map((list) => {
    const names = list.map((c) => c.name)
    const occNames = names.filter(isOccupationColumn)
    const name = pickCanonicalName(occNames.length ? occNames : names)
    const primary = list.find((c) => c.name === name) || list[0]
    const aliasNames = [...new Set(names)].filter((n) => n !== primary.name)
    return {
      ...primary,
      name: primary.name,
      codes: cloneCodeRows(primary.codes),
        aliases: list.map((c) => ({
        name: c.name,
        _metadataId: c._metadataId,
        _groupIndex: c._groupIndex,
      })),
      aliasNames,
    }
  })
}

function isPrimaryHarmoniseAlias(column, alias) {
  return (alias.name || column.name) === column.name
    && (alias._metadataId || null) === (column._metadataId || null)
}

function flattenForHarmonise(columns) {
  const out = []
  columns.forEach((c) => {
    const aliases = c.aliases?.length
      ? c.aliases
      : [{ name: c.name, _metadataId: c._metadataId, _groupIndex: c._groupIndex }]
    const seen = new Set()
    aliases.forEach((a) => {
      const name = a.name || c.name
      const key = `${a._metadataId || ''}::${name}`
      if (seen.has(key)) return
      seen.add(key)
      out.push({
        id: key,
        name,
        metadataId: a._metadataId,
        groupIndex: a._groupIndex ?? c._groupIndex,
        sourceName: c.name,
        isAlias: !isPrimaryHarmoniseAlias(c, a),
        column: c,
      })
    })
  })
  return out
}

export default function Classify({ metadataIds, datasetLabel, onContinue }) {
  const [classified, setClassified] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [classifiedColumns, setClassifiedColumns] = useState([])
  const [selectedCol, setSelectedCol] = useState(null)
  const [columnCodes, setColumnCodes] = useState({})
  const [savedCodes, setSavedCodes] = useState({})
  const [saving, setSaving] = useState(false)
  const [openRule, setOpenRule] = useState(null)
  const [ruleState, setRuleState] = useState({}) // harmonise entry id -> 'skip' | undefined
  const [taxonomy, setTaxonomy] = useState(initialTaxonomy)
  const [aliasVerified, setAliasVerified] = useState({})
  const [harmRows, setHarmRows] = useState({})
  const [harmDirty, setHarmDirty] = useState({})
  const [ncoMatchesByCol, setNcoMatchesByCol] = useState({})
  const [ncoLoading, setNcoLoading] = useState(false)
  const [ncoError, setNcoError] = useState('')
  const [fillAiLoading, setFillAiLoading] = useState(false)
  const [fillAiError, setFillAiError] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState('')

  useEffect(() => {
    const ids = Array.isArray(metadataIds) ? metadataIds.filter(Boolean) : [metadataIds].filter(Boolean)
    let cancelled = false
    setLoading(true)
    setLoadError('')

    const loadFromGroups = () => Promise.all(ids.map((id) =>
      fetch(`/api/catalogue/metadata-groups/${encodeURIComponent(id)}/classifications`, withAuthHeaders())
        .then(async (res) => {
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Failed to load classifications' }))
            const detail = err.detail
            const msg = typeof detail === 'string'
              ? detail
              : (Array.isArray(detail) ? detail.map((d) => d.msg || d).join('; ') : 'Failed to load classifications')
            throw new Error(msg)
          }
          return res.json()
        })
        .then((data) => (data.columns || []).map((c) => ({ ...c, _metadataId: id })))
        .catch((e) => {
          // One bad group should not blank the whole Classify step when others work.
          console.warn('classifications load failed for', id, e)
          return []
        })
    )).then((perGroup) => perGroup.flat())

    const loadRecent = () =>
      fetch('/api/catalogue/classifications/recent', withAuthHeaders())
        .then(async (res) => {
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Failed to load classifications' }))
            throw new Error(err.detail || 'Failed to load classifications')
          }
          return res.json()
        })
        .then((data) => data.columns || [])

    const apply = (raw) => {
      if (cancelled) return
      const columns = collapseEquivalentColumns(raw)
      setClassifiedColumns(columns)
      const codes = Object.fromEntries(columns.map((c) => [c.name, cloneCodeRows(c.codes)]))
      setColumnCodes(codes)
      setSavedCodes(codes)
      setSelectedCol(columns[0]?.name ?? null)
      setAliasVerified({})
      setHarmDirty({})
      setRuleState({})
      const harm = {}
      flattenForHarmonise(columns).forEach((e) => {
        harm[e.id] = cloneCodeRows(codes[e.sourceName] || e.column.codes)
      })
      setHarmRows(harm)
    }

    const start = ids.length ? loadFromGroups() : loadRecent()

    start
      .then(apply)
      .catch((e) => { if (!cancelled) setLoadError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [metadataIds])

  const activeColumn = classifiedColumns.find((c) => c.name === selectedCol)
  const activeCodes = columnCodes[selectedCol] || []
  const ncoMatches = (selectedCol && ncoMatchesByCol[selectedCol]) || null
  const columnDirty = JSON.stringify(columnCodes[selectedCol]) !== JSON.stringify(savedCodes[selectedCol])

  const setCodeFieldFor = (name, rowIndex, field, value) => {
    setColumnCodes((prev) => ({
      ...prev,
      [name]: (prev[name] || []).map((row, i) => (i === rowIndex ? { ...row, [field]: value } : row)),
    }))
  }
  const setCodeField = (rowIndex, field, value) => setCodeFieldFor(selectedCol, rowIndex, field, value)

  const persistTargets = (targets, rows, { markSavedName } = {}) => {
    if (!rows || !targets?.length) return
    const codes = rows.map((row) => ({ ...row }))
    const byGroup = {}
    targets.forEach((t) => {
      if (!t._metadataId || !t.name) return
      if (!byGroup[t._metadataId]) byGroup[t._metadataId] = []
      if (!byGroup[t._metadataId].includes(t.name)) byGroup[t._metadataId].push(t.name)
    })
    const entries = Object.entries(byGroup)
    if (!entries.length) {
      if (markSavedName) setSavedCodes((prev) => ({ ...prev, [markSavedName]: codes }))
      return
    }
    const live = entries.filter(([id]) => id && !String(id).startsWith('pending-'))
    if (!live.length) {
      if (markSavedName) setSavedCodes((prev) => ({ ...prev, [markSavedName]: codes }))
      return
    }
    setSaving(true)
    Promise.all(live.map(([ownerId, names]) =>
      fetch(`/api/catalogue/metadata-groups/${ownerId}/classifications`, withAuthHeaders({
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          column_name: names[0],
          column_names: names,
          codes,
          expand_aliases: false,
        }),
      })).then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Could not save' }))
          throw new Error(typeof err.detail === 'string' ? err.detail : 'Could not save')
        }
      })
    ))
      .then(() => {
        if (markSavedName) {
          setSavedCodes((prev) => ({ ...prev, [markSavedName]: codes }))
        }
      })
      .catch(() => {})
      .finally(() => setSaving(false))
  }

  const persistColumnCodes = (column, rows) => {
    if (!column || !rows) return
    persistTargets(
      [{
        name: column.name,
        _metadataId: column._metadataId || column.aliases?.[0]?._metadataId,
      }],
      rows,
      { markSavedName: column.name },
    )
  }

  const persistHarmoniseEntry = (entry, rows) => {
    persistTargets(
      [{ name: entry.name, _metadataId: entry.metadataId || entry.column._metadataId }],
      rows,
      { markSavedName: entry.isAlias ? undefined : entry.sourceName },
    )
  }

  const setHarmField = (entry, rowIndex, field, value) => {
    setHarmDirty((prev) => ({ ...prev, [entry.id]: true }))
    setHarmRows((prev) => ({
      ...prev,
      [entry.id]: (prev[entry.id] || []).map((row, i) => (i === rowIndex ? { ...row, [field]: value } : row)),
    }))
    if (!entry.isAlias) {
      setCodeFieldFor(entry.sourceName, rowIndex, field, value)
    }
  }

  useEffect(() => {
    setHarmRows((prev) => {
      const next = { ...prev }
      flattenForHarmonise(classifiedColumns).forEach((e) => {
        if (harmDirty[e.id] || aliasVerified[e.id]) return
        const source = columnCodes[e.sourceName]
        if (source) next[e.id] = cloneCodeRows(source)
      })
      return next
    })
  }, [columnCodes, classifiedColumns, harmDirty, aliasVerified])

  const saveColumnCodes = () => {
    persistColumnCodes(activeColumn, columnCodes[selectedCol])
  }

  const fillDefinitionsWithAi = () => {
    if (isOccupationColumn(selectedCol) || !activeColumn) return
    const columns = [{
      name: activeColumn.name,
      metadata_id: activeColumn._metadataId || activeColumn.aliases?.[0]?._metadataId || null,
      values: (columnCodes[activeColumn.name] || []).map((r) => r.value || r.code).filter(Boolean),
    }].filter((c) => c.values.length)
    if (!columns.length) return
    setFillAiLoading(true)
    setFillAiError('')
    fetch('/api/catalogue/fill-definitions', withAuthHeaders(withLlmKeyHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ columns }),
    })))
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Could not fill definitions' }))
          throw new Error(typeof err.detail === 'string' ? err.detail : 'Could not fill definitions')
        }
        return res.json()
      })
      .then((data) => {
        const byCol = data.definitions || {}
        const defs = byCol[activeColumn.name] || {}
        const nextRows = (columnCodes[activeColumn.name] || []).map((row) => {
          const d = defs[row.value] || defs[row.code]
          if (!d) return row
          return { ...row, definition: String(d) }
        })
        setColumnCodes((prev) => ({ ...prev, [activeColumn.name]: nextRows }))
      })
      .catch((e) => setFillAiError(e.message))
      .finally(() => setFillAiLoading(false))
  }

  const columnMapped = (name) => {
    const rows = columnCodes[name] || []
    return rows.length > 0 && rows.every(rowMapped)
  }
  const columnNeedsNcoReview = (sourceName) => {
    const matches = ncoMatchesByCol[sourceName]
    if (!matches) return false
    return Object.values(matches).some((m) => m && m.needs_manual_review)
  }
  const ncoReviewCount = (sourceName) => {
    const matches = ncoMatchesByCol[sourceName] || {}
    const rows = columnCodes[sourceName] || []
    return rows.filter((row) => matches[row.value]?.needs_manual_review).length
  }
  const harmoniseEntries = flattenForHarmonise(classifiedColumns).filter((e) => e.isAlias)
  const entryNeedsVerify = (entry) => true
  const entryReady = (entry) => {
    if (ruleState[entry.id] === 'skip') return true
    if (!aliasVerified[entry.id]) return false
    const rows = harmRows[entry.id] || columnCodes[entry.sourceName] || []
    return rows.length > 0 && rows.every(rowMapped)
  }
  const classReady = classified && classifiedColumns.length > 0
    && classifiedColumns.every((c) => columnMapped(c.name))
    && harmoniseEntries.every(entryReady)

  const publishRelease = async () => {
    if (!classReady || publishing) return
    setPublishing(true)
    setPublishError('')
    try {
      await Promise.resolve(onContinue?.())
    } catch (e) {
      setPublishError(e.message || 'Could not continue to publish')
    } finally {
      setPublishing(false)
    }
  }

  const saveBtnClass = 'h-11 rounded-lg border-0 px-5 text-[15px] font-semibold text-white transition-colors bg-teal hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]'
  const cardClass = 'overflow-hidden rounded-[10px] border border-line bg-white'
  const cardHeadClass = 'flex items-center gap-2.5 border-b border-line px-[18px] py-3 text-[15px] font-semibold text-ink'
  const cardNoteClass = 'text-xs font-normal text-[#8E9398]'

  return (
    <div className="flex max-w-[900px] flex-col gap-4">
      <div className="flex items-center justify-between gap-6 rounded-[10px] border border-line bg-white px-[22px] py-[18px]">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-[#8E9398]">{datasetLabel}</div>
          <div className="text-base font-semibold text-ink">Classify columns and harmonise values</div>
          <div className="text-sm text-ink-soft">DHARA reads every column, proposes a standard concept and drafts code-list mappings for review.</div>
        </div>
        <Button
          disabled={classified || loading}
          onClick={() => setClassified(true)}
        >
          {classified ? 'Classified' : 'Run classification'}
        </Button>
      </div>

      {classified && loading && (
        <div className={`${cardClass} p-[18px]`}>Loading classified columns…</div>
      )}

      {classified && !loading && loadError && (
        <div className={`${cardClass} p-[18px]`}>Couldn't load classifications: {loadError}</div>
      )}

      {classified && !loading && !loadError && classifiedColumns.length === 0 && (
        <div className={`${cardClass} p-[18px]`}>No classification columns found for this dataset.</div>
      )}

      {classified && !loading && !loadError && classifiedColumns.length > 0 && (
        <>
          <div className={cardClass}>
            <div className={cardHeadClass}>
              <span>Classified columns</span>
              <span className={cardNoteClass}>
                {classifiedColumns.length} columns · pick one to check its code list
                {saving ? ' · saving…' : ''}
                {fillAiError && !isOccupationColumn(selectedCol) ? ` · ${fillAiError}` : ''}
              </span>
              {!isOccupationColumn(selectedCol) && (
              <button
                type="button"
                className="ml-auto h-[34px] flex-none rounded-md border-0 bg-teal px-3.5 text-[13px] font-semibold text-white transition-colors hover:enabled:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]"
                disabled={fillAiLoading || !activeCodes.length}
                onClick={fillDefinitionsWithAi}
              >
                {fillAiLoading ? 'Filling…' : 'Fill with AI'}
              </button>
              )}
            </div>

            <div className="flex flex-wrap gap-2.5 border-b border-line p-4 px-[18px]">
              {classifiedColumns.map((c) => (
                <div
                  key={`${c._metadataId || ''}:${c.name}`}
                  className={`flex min-w-[140px] cursor-pointer flex-col gap-[3px] rounded-lg border px-3.5 py-2.5 transition-colors hover:border-[#c9bda6] ${
                    c.name === selectedCol ? 'border-[#b9cfa9] bg-sage' : 'border-line bg-white'
                  }`}
                  onClick={() => setSelectedCol(c.name)}
                >
                  <div className="text-[15px] font-semibold text-ink">{c.name}</div>
                  <div className="text-[12.5px] text-ink-soft">
                    {c.codes.length} codes{c.aliasNames?.length ? ` · +${c.aliasNames.length} same list` : ''}
                  </div>
                </div>
              ))}
            </div>

            {activeColumn && (
              <>
                <div className="flex items-baseline justify-between gap-4 px-[18px] pb-3 pt-[18px]">
                  <div>
                    <span className="text-xl font-bold text-ink">{activeColumn.name}</span>
                    <span className="ml-2.5 text-sm text-ink-soft">{activeColumn.concept}</span>
                  </div>
                  <div className="whitespace-nowrap text-[13px] text-ink-soft">
                    {activeCodes.length} values
                    {activeColumn.aliasNames?.length
                      ? ` · also ${activeColumn.aliasNames.join(', ')}`
                      : activeColumn.note ? ` · ${activeColumn.note}` : ''}
                  </div>
                </div>

                <div className="mx-[18px] mb-4 overflow-hidden rounded-lg border border-[#cfc6b4]">
                  <div className="grid grid-cols-[1fr_1.1fr_1.6fr] items-center gap-3.5 border-b border-[#d7cdb9] bg-[#F4EFE3] px-4 py-2.5 font-sans text-[11.5px] uppercase tracking-wide text-[#8E9398]">
                    <div>Code</div><div>Value</div><div>Definition</div>
                  </div>
                  {activeCodes.map((row, i) => (
                    <div className="grid grid-cols-[1fr_1.1fr_1.6fr] items-center gap-3.5 border-b border-[#f1ebdf] bg-white px-4 py-2.5 last:border-b-0" key={i}>
                      <input
                        className="box-border h-[38px] rounded-md border border-[#ddd3c0] bg-cream px-3 font-sans text-sm text-ink focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                        type="text"
                        value={row.code}
                        onChange={(e) => setCodeField(i, 'code', e.target.value)}
                      />
                      <div className="text-sm font-semibold text-ink">{row.value}</div>
                      <input
                        className="box-border h-[38px] rounded-md border border-[#ddd3c0] bg-cream px-3 font-sans text-sm text-ink focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                        type="text"
                        value={row.definition}
                        onChange={(e) => setCodeField(i, 'definition', e.target.value)}
                      />
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between gap-4 px-[18px] pb-[18px] pt-3.5">
                  <span className="text-sm text-ink-soft">Code and definition can be edited. Values come from the data and stay fixed.</span>
                  <button className={saveBtnClass} disabled={!columnDirty} onClick={saveColumnCodes}>Save changes</button>
                </div>

                {isOccupationColumn(activeColumn.name) && (
                  <div className="border-t border-line px-[18px] pb-[18px]">
                    <div className="flex items-start justify-between gap-4 pb-3 pt-4">
                      <div>
                        <div className="text-[15px] font-bold text-ink">NCO 2015 code suggestion</div>
                        <div className="mt-1 max-w-[520px] text-[13px] leading-snug text-ink-soft">
                          Fills Code and Definition above from the suggested NCO code and title. Harmonisation still asks you to verify those codes before they are saved.
                        </div>
                      </div>
                      <button
                        type="button"
                        className={saveBtnClass}
                        disabled={ncoLoading || activeCodes.length === 0}
                        onClick={() => {
                          const values = activeCodes.map((r) => r.value || r.code).filter(Boolean)
                          setNcoLoading(true)
                          setNcoError('')
                          fetch('/api/catalogue/match-nco', withAuthHeaders(withLlmKeyHeaders({
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ values }),
                          })))
                            .then(async (res) => {
                              if (!res.ok) {
                                const err = await res.json().catch(() => ({ detail: 'NCO matching failed' }))
                                throw new Error(err.detail || 'NCO matching failed')
                              }
                              return res.json()
                            })
                            .then((data) => {
                              const occName = selectedCol
                              const matches = data.matches || {}
                              setNcoMatchesByCol((prev) => ({ ...prev, [occName]: matches }))
                              if (!isOccupationColumn(occName)) return
                              const rows = columnCodes[occName] || []
                              const nextRows = rows.map((row) => {
                                const m = matches[row.value]
                                if (!m || m.code == null || m.code === '') return row
                                return {
                                  ...row,
                                  code: String(m.code),
                                  definition: m.title != null && m.title !== '' ? String(m.title) : row.definition,
                                }
                              })
                              setColumnCodes((prev) => ({ ...prev, [occName]: nextRows }))
                              setAliasVerified((prev) => {
                                const next = { ...prev }
                                flattenForHarmonise(classifiedColumns)
                                  .filter((e) => e.sourceName === occName)
                                  .forEach((e) => { delete next[e.id] })
                                return next
                              })
                              setHarmDirty((prev) => {
                                const next = { ...prev }
                                flattenForHarmonise(classifiedColumns)
                                  .filter((e) => e.sourceName === occName)
                                  .forEach((e) => { delete next[e.id] })
                                return next
                              })
                            })
                            .catch((e) => setNcoError(e.message))
                            .finally(() => setNcoLoading(false))
                        }}
                      >
                        {ncoLoading ? 'Matching…' : 'Suggest NCO codes'}
                      </button>
                    </div>
                    {ncoError && <div className="mb-2.5 text-[13px] text-[#b91c1c]">{ncoError}</div>}
                    {ncoMatches && (
                      <div className="overflow-hidden rounded-lg border border-[#cfc6b4]">
                        <div className="grid grid-cols-[1.2fr_0.7fr_0.8fr_1.4fr] items-start gap-3.5 border-b border-[#d7cdb9] bg-[#F4EFE3] px-4 py-2.5 font-sans text-[11.5px] uppercase tracking-wide text-[#8E9398]">
                          <div>Value</div><div>Level</div><div>Suggested code</div><div>Title</div>
                        </div>
                        {activeCodes.map((row) => {
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
                                    {m.needs_manual_review ? ' · review' : ''}
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
                )}
              </>
            )}
          </div>

          <div className={cardClass}>
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
                ? `Same values as ${sourceName} — review and verify`
                : occ
                  ? 'Suggested NCO codes — review and verify'
                  : 'Value → code and definition from classification'
              const status = skipped ? 'Skipped' : pendingVerify || ncoOpen || !done ? 'Needs review' : 'Ready'
              const countLabel = occ && reviewCount > 0
                ? `${reviewCount} needs review`
                : `${mappedCount} of ${rows.length} mapped`
              return (
                <div className="border-b border-[#f1ebdf] last:border-b-0" key={id}>
                  <div className="flex cursor-pointer items-center gap-3 px-[18px] py-[13px] transition-colors hover:bg-[#FBF7EF]" onClick={() => setOpenRule(open ? null : id)}>
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
                          className="flex h-8 items-center rounded-[5px] border border-[#ddd3c0] bg-white px-3 text-[13px] font-semibold text-ink-soft"
                          onClick={() => setRuleState((prev) => ({ ...prev, [id]: prev[id] === 'skip' ? undefined : 'skip' }))}
                        >
                          {skipped ? 'Unskip' : 'Skip this column'}
                        </button>
                        {needsVerify ? (
                          <button
                            type="button"
                            className={`${saveBtnClass} h-11 !text-sm`}
                            disabled={verified && !harmDirty[id]}
                            onClick={() => {
                              persistHarmoniseEntry(entry, rows)
                              setAliasVerified((prev) => ({ ...prev, [id]: true }))
                              setHarmDirty((prev) => ({ ...prev, [id]: false }))
                            }}
                          >
                            {verified && !harmDirty[id] ? 'Verified' : 'Verify & save'}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className={`${saveBtnClass} h-11 !text-sm`}
                            disabled={!rowsDirty}
                            onClick={() => persistHarmoniseEntry(entry, rows)}
                          >
                            Save changes
                          </button>
                        )}
                      </div>
                      <p className="m-0 mb-2.5 text-[13px] leading-tight text-ink-soft">
                        Value in file comes from the data and cannot be changed. Code and definition are editable.
                      </p>
                      <div className="overflow-hidden rounded-lg border border-[#cfc6b4]">
                        <div className="grid grid-cols-[38px_1.2fr_0.7fr_1.4fr_64px] items-stretch border-b border-[#cfc6b4] bg-[#F4EFE3] [&>div]:border-l [&>div]:border-[#e0d7c4] [&>div]:px-3 [&>div]:py-2 [&>div]:text-[11px] [&>div]:uppercase [&>div]:tracking-wide [&>div]:text-[#6E7378] [&>div:first-child]:border-l-0 [&>div:first-child]:text-center [&>div:last-child]:px-1 [&>div:last-child]:text-center">
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
                                onChange={(e) => setHarmField(entry, i, 'code', e.target.value)}
                              />
                              <input
                                className="box-border h-full min-h-[40px] w-full border-0 border-l border-[#f1ebdf] bg-white px-3 py-2 font-sans text-[13px] text-ink placeholder:text-[#c2b8a6] focus:relative focus:z-[1] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                                type="text"
                                value={row.definition}
                                placeholder="Edit definition"
                                title="Editable"
                                onChange={(e) => setHarmField(entry, i, 'definition', e.target.value)}
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

          <div className={`${cardClass} flex flex-col gap-4 p-[22px]`}>
            <div className="text-[15px] font-semibold text-ink">Catalogue placement</div>
            <div className="grid grid-cols-3 gap-3.5">
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Sector</label>
                <select className="h-10 rounded-md border border-[#ddd3c0] bg-white px-2.5 text-sm text-ink" value={taxonomy.sector} onChange={(e) => setTaxonomy((p) => ({ ...p, sector: e.target.value }))}>
                  {['Demography', 'Labour and Employment', 'Health', 'Agriculture'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Theme</label>
                <select className="h-10 rounded-md border border-[#ddd3c0] bg-white px-2.5 text-sm text-ink" value={taxonomy.theme} onChange={(e) => {
                  const theme = e.target.value
                  setTaxonomy((p) => ({ ...p, theme, product: delhiProductForTheme(theme) }))
                }}>
                  {STATISTICS_OPTIONS.map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Data product</label>
                <select className="h-10 rounded-md border border-[#ddd3c0] bg-white px-2.5 text-sm text-ink" value={taxonomy.product} onChange={(e) => setTaxonomy((p) => ({ ...p, product: e.target.value }))}>
                  {STATISTICS_OPTIONS.map((o) => {
                    const product = delhiProductForTheme(o)
                    return <option key={product}>{product}</option>
                  })}
                </select>
              </div>
            </div>
          </div>
        </>
      )}

      <div className="flex items-center gap-3.5">
        <Button disabled={!classReady || publishing} onClick={publishRelease}>
          {publishing ? 'Continuing…' : (
            <span className="inline-flex items-center gap-1.5">
              Continue to publish
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            </span>
          )}
        </Button>
        <span className="text-[13px] text-[#8E9398]">
          {publishError
            ? publishError
            : classified
              ? (classReady ? 'Catalogue already saved — continue to the publication confirmation.' : 'Map the classified columns, then verify or skip the remaining columns below.')
              : 'Run classification to continue.'}
        </span>
      </div>
    </div>
  )
}