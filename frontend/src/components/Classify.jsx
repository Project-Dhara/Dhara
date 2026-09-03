import { useEffect, useState } from 'react'
import { withAuthHeaders } from '../auth'
import { withLlmKeyHeaders } from '../llmKey'
import { STATISTICS_OPTIONS, getDatasetIdConfig } from '../settingsConfig'

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

function columnsFromPendingGroups(groups) {
  return (groups || []).flatMap((g, gi) =>
    Object.entries(g.classifications || {})
      .filter(([, codes]) => Array.isArray(codes) && codes.length)
      .map(([name, codes]) => ({
        name,
        concept: name,
        note: '',
        codes: (codes || []).map((e) => (
          e && typeof e === 'object'
            ? { code: e.code ?? '', value: e.value ?? e.code ?? '', definition: e.definition ?? '' }
            : { code: String(e ?? ''), value: String(e ?? ''), definition: '' }
        )),
        _metadataId: `pending-${gi}`,
        _groupIndex: gi,
      })),
  )
}

export default function Classify({ metadataIds, datasetLabel, groups, onContinue }) {
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
      fetch(`/api/catalogue/metadata-groups/${id}/classifications`, withAuthHeaders())
        .then(async (res) => {
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Failed to load classifications' }))
            throw new Error(err.detail || 'Failed to load classifications')
          }
          return res.json()
        })
        .then((data) => (data.columns || []).map((c) => ({ ...c, _metadataId: id })))
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

    const pendingCols = columnsFromPendingGroups(groups)
    const start = pendingCols.length
      ? Promise.resolve(pendingCols)
      : (ids.length ? loadFromGroups() : loadRecent())

    start
      .then(apply)
      .catch((e) => { if (!cancelled) setLoadError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [metadataIds, groups])

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
    const nextGroups = (groups || []).map((g) => ({
      ...g,
      catalogue_placement: taxonomy,
      metadata: { ...(g.metadata || {}) },
      classifications: { ...(g.classifications || {}) },
    }))
    flattenForHarmonise(classifiedColumns).forEach((e) => {
      const gi = e.groupIndex ?? e.column._groupIndex
      if (gi == null || !nextGroups[gi]) return
      const rows = harmRows[e.id] || columnCodes[e.sourceName] || []
      nextGroups[gi].classifications[e.name] = rows.map((row) => ({
        code: row.code ?? '',
        value: row.value ?? '',
        definition: row.definition ?? '',
      }))
    })
    classifiedColumns.forEach((c) => {
      const gi = c._groupIndex
      const rows = columnCodes[c.name]
      if (gi == null || !nextGroups[gi] || !rows) return
      nextGroups[gi].classifications[c.name] = rows.map((row) => ({
        code: row.code ?? '',
        value: row.value ?? '',
        definition: row.definition ?? '',
      }))
    })
    try {
      if (!nextGroups.length) {
        throw new Error('No metadata groups to publish. Return to metadata and continue to classification again.')
      }
      await onContinue({ groups: nextGroups, taxonomy })
    } catch (e) {
      setPublishError(e.message || 'Could not publish to the catalogue')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="classify-step">
      <div className="classify-run-card">
        <div>
          <div className="classify-run-eyebrow">{datasetLabel}</div>
          <div className="classify-run-title">Classify columns and harmonise values</div>
          <div className="classify-run-blurb">DHARA reads every column, proposes a standard concept and drafts code-list mappings for review.</div>
        </div>
        <button
          className="classify-run-btn"
          disabled={classified}
          onClick={() => setClassified(true)}
        >
          {classified ? 'Classified' : 'Run classification'}
        </button>
      </div>

      {classified && loading && (
        <div className="classify-card classcols-card">Loading classified columns…</div>
      )}

      {classified && !loading && loadError && (
        <div className="classify-card classcols-card">Couldn't load classifications: {loadError}</div>
      )}

      {classified && !loading && !loadError && classifiedColumns.length === 0 && (
        <div className="classify-card classcols-card">No classification columns found for this dataset.</div>
      )}

      {classified && !loading && !loadError && classifiedColumns.length > 0 && (
        <>
          <div className="classify-card classcols-card">
            <div className="classify-card-head">
              <span>Classified columns</span>
              <span className="classify-card-note">
                {classifiedColumns.length} columns · pick one to check its code list
                {saving ? ' · saving…' : ''}
                {fillAiError && !isOccupationColumn(selectedCol) ? ` · ${fillAiError}` : ''}
              </span>
              {!isOccupationColumn(selectedCol) && (
              <button
                type="button"
                className="classcols-fill-ai-btn"
                disabled={fillAiLoading || !activeCodes.length}
                onClick={fillDefinitionsWithAi}
              >
                {fillAiLoading ? 'Filling…' : 'Fill with AI'}
              </button>
              )}
            </div>

            <div className="classcols-chips">
              {classifiedColumns.map((c) => (
                <div
                  key={`${c._metadataId || ''}:${c.name}`}
                  className={`classcols-chip${c.name === selectedCol ? ' classcols-chip-active' : ''}`}
                  onClick={() => setSelectedCol(c.name)}
                >
                  <div className="classcols-chip-name">{c.name}</div>
                  <div className="classcols-chip-count">
                    {c.codes.length} codes{c.aliasNames?.length ? ` · +${c.aliasNames.length} same list` : ''}
                  </div>
                </div>
              ))}
            </div>

            {activeColumn && (
              <>
                <div className="classcols-detail-head">
                  <div>
                    <span className="classcols-detail-name">{activeColumn.name}</span>
                    <span className="classcols-detail-concept">{activeColumn.concept}</span>
                  </div>
                  <div className="classcols-detail-meta">
                    {activeCodes.length} values
                    {activeColumn.aliasNames?.length
                      ? ` · also ${activeColumn.aliasNames.join(', ')}`
                      : activeColumn.note ? ` · ${activeColumn.note}` : ''}
                  </div>
                </div>

                <div className="classcols-table">
                  <div className="classcols-table-head">
                    <div>Code</div><div>Value</div><div>Definition</div>
                  </div>
                  {activeCodes.map((row, i) => (
                    <div className="classcols-row" key={i}>
                      <input
                        className="classcols-input"
                        type="text"
                        value={row.code}
                        onChange={(e) => setCodeField(i, 'code', e.target.value)}
                      />
                      <div className="classcols-value">{row.value}</div>
                      <input
                        className="classcols-input"
                        type="text"
                        value={row.definition}
                        onChange={(e) => setCodeField(i, 'definition', e.target.value)}
                      />
                    </div>
                  ))}
                </div>

                <div className="classcols-footer">
                  <span className="classcols-footer-hint">Code and definition can be edited. Values come from the data and stay fixed.</span>
                  <button className="classcols-save-btn" disabled={!columnDirty} onClick={saveColumnCodes}>Save changes</button>
                </div>

                {isOccupationColumn(activeColumn.name) && (
                  <div className="classcols-nco">
                    <div className="classcols-nco-head">
                      <div>
                        <div className="classcols-nco-title">NCO 2015 level suggestion</div>
                        <div className="classcols-nco-blurb">
                          Fills Code and Definition above from the suggested NCO code and title. Harmonisation still asks you to verify those codes before they are saved.
                        </div>
                      </div>
                      <button
                        type="button"
                        className="classcols-save-btn"
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
                        {ncoLoading ? 'Matching…' : 'Suggest NCO levels'}
                      </button>
                    </div>
                    {ncoError && <div className="classcols-nco-error">{ncoError}</div>}
                    {ncoMatches && (
                      <div className="classcols-table classcols-nco-table">
                        <div className="classcols-table-head classcols-nco-head-row">
                          <div>Value</div><div>Level</div><div>Suggested code</div><div>Title</div>
                        </div>
                        {activeCodes.map((row) => {
                          const m = ncoMatches[row.value]
                          return (
                            <div className="classcols-row classcols-nco-head-row" key={row.value || row.code}>
                              <div className="classcols-value">{row.value}</div>
                              <div className="classcols-value">{m ? m.level : '—'}</div>
                              <div className="classcols-value">{m ? m.code : '—'}</div>
                              <div>
                                <div className="classcols-value">{m ? m.title : '—'}</div>
                                {m && (
                                  <div className="classcols-nco-meta">
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

          <div className="classify-card">
            <div className="classify-card-head">
              <span>Harmonisation</span>
              <span className="classify-card-note">
                {classifiedColumns.filter((c) => columnMapped(c.name)).length} of {classifiedColumns.length} lists mapped
                {harmoniseEntries.length
                  ? ` · ${harmoniseEntries.length} other column${harmoniseEntries.length === 1 ? '' : 's'} to verify`
                  : ''}
              </span>
            </div>
            {harmoniseEntries.length === 0 && (
              <div className="classify-rule">
                <div className="classify-rule-head" style={{ cursor: 'default' }}>
                  <div className="classify-rule-text">
                    <div className="classify-rule-detail">No other classification columns besides the chips above.</div>
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
                <div className="classify-rule" key={id}>
                  <div className="classify-rule-head" onClick={() => setOpenRule(open ? null : id)}>
                    <span className={`classify-rule-dot${done && !pendingVerify ? ' classify-rule-dot-done' : ''}`} />
                    <div className="classify-rule-text">
                      <div className="classify-rule-title">{name}</div>
                      <div className="classify-rule-detail">{detail}</div>
                    </div>
                    <span className={`classify-rule-status${done && !pendingVerify ? ' classify-rule-status-done' : ''}`}>
                      {status}
                    </span>
                    <span className="classify-rule-count">{countLabel}</span>
                    <span className={`classify-rule-chev${open ? ' classify-rule-chev-open' : ''}`}>▾</span>
                  </div>
                  <div className={`classify-rule-body-wrap${open ? ' classify-rule-body-wrap-open' : ''}`}>
                    <div className="classify-rule-body">
                      <div className="classify-rule-actions">
                        <button
                          type="button"
                          className="classify-skip-btn"
                          onClick={() => setRuleState((prev) => ({ ...prev, [id]: prev[id] === 'skip' ? undefined : 'skip' }))}
                        >
                          {skipped ? 'Unskip' : 'Skip this column'}
                        </button>
                        {needsVerify ? (
                          <button
                            type="button"
                            className="classcols-save-btn"
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
                            className="classcols-save-btn"
                            disabled={!rowsDirty}
                            onClick={() => persistHarmoniseEntry(entry, rows)}
                          >
                            Save changes
                          </button>
                        )}
                      </div>
                      <p className="classify-harm-hint">
                        Value in file comes from the data and cannot be changed. Code and definition are editable.
                      </p>
                      <div className="classify-map-table classify-map-table-review">
                        <div className="classify-map-head classify-map-head-review">
                          <div>#</div>
                          <div>
                            Value in file
                            <span className="classify-map-col-hint">Fixed</span>
                          </div>
                          <div>
                            Code
                            <span className="classify-map-col-hint classify-map-col-hint-edit">Editable</span>
                          </div>
                          <div>
                            Definition
                            <span className="classify-map-col-hint classify-map-col-hint-edit">Editable</span>
                          </div>
                          <div>Match</div>
                        </div>
                        {rows.map((row, i) => {
                          const m = occ ? (ncoMatchesByCol[sourceName] || {})[row.value] : null
                          const filled = rowMapped(row)
                          const rowReview = Boolean(m?.needs_manual_review) && !verified
                          return (
                            <div className="classify-map-row classify-map-head-review" key={row.value || i}>
                              <div className="classify-map-n">{i + 1}</div>
                              <div className="classify-map-source" title="From the data — not editable">
                                <div>{row.value}</div>
                                {m && (
                                  <div className="classify-map-source-meta">
                                    {m.level}
                                    {rowReview ? ' · review' : ''}
                                    {m.codes?.length > 1 ? ' · both valid' : ''}
                                  </div>
                                )}
                              </div>
                              <input
                                className="classify-map-input"
                                type="text"
                                value={row.code}
                                placeholder="Edit code"
                                title="Editable"
                                onChange={(e) => setHarmField(entry, i, 'code', e.target.value)}
                              />
                              <input
                                className="classify-map-input"
                                type="text"
                                value={row.definition}
                                placeholder="Edit definition"
                                title="Editable"
                                onChange={(e) => setHarmField(entry, i, 'definition', e.target.value)}
                              />
                              <div className={`classify-map-mark${rowReview ? ' classify-map-mark-review' : ''}`}>
                                {rowReview ? '!' : filled ? '✓' : '—'}
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

          <div className="classify-card classify-taxonomy-card">
            <div className="classify-card-title">Catalogue placement</div>
            <div className="classify-taxonomy-grid">
              <div className="classify-field">
                <label className="classify-label">Sector</label>
                <select className="classify-select" value={taxonomy.sector} onChange={(e) => setTaxonomy((p) => ({ ...p, sector: e.target.value }))}>
                  {['Demography', 'Labour and Employment', 'Health', 'Agriculture'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="classify-field">
                <label className="classify-label">Theme</label>
                <select className="classify-select" value={taxonomy.theme} onChange={(e) => {
                  const theme = e.target.value
                  setTaxonomy((p) => ({ ...p, theme, product: delhiProductForTheme(theme) }))
                }}>
                  {STATISTICS_OPTIONS.map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="classify-field">
                <label className="classify-label">Data product</label>
                <select className="classify-select" value={taxonomy.product} onChange={(e) => setTaxonomy((p) => ({ ...p, product: e.target.value }))}>
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

      <div className="classify-continue-row">
        <button className="console-primary-btn" disabled={!classReady || publishing} onClick={publishRelease}>
          {publishing ? 'Publishing…' : 'Continue to publish →'}
        </button>
        <span className="classify-continue-hint">
          {publishError
            ? publishError
            : classified
              ? (classReady ? 'Writes this release to the catalogue, then opens publication.' : 'Map the classified columns, then verify or skip the remaining columns below.')
              : 'Run classification to continue.'}
        </span>
      </div>
    </div>
  )
}
