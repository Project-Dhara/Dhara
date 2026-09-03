import { useEffect, useState } from 'react'
import { withAuthHeaders } from '../auth'
import { withLlmKeyHeaders } from '../llmKey'

// The classified columns (name/concept/note + code list) come from the real
// metadata-excel classification sheets, fetched below — see
// backend/catalogue.py::get_metadata_group_classifications and
// backend/metadata_excel.py::parse_classifications. Code and definition are
// editable (a steward may want to rename/annotate them); value is what was
// actually found in the source data, so it stays fixed.

const TAGS = ['births', 'registration', 'sex', 'age group', 'occupation', 'Delhi', 'CRS', 'annual']

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
    const key = isOccupationColumn(c.name)
      ? `occ:${codesFingerprint(c.codes)}`
      : `name:${c.name}`
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
      aliases: list.map((c) => ({ name: c.name, _metadataId: c._metadataId })),
      aliasNames,
    }
  })
}

function flattenForHarmonise(columns) {
  const out = []
  columns.forEach((c) => {
    const aliases = c.aliases?.length
      ? c.aliases
      : [{ name: c.name, _metadataId: c._metadataId }]
    const seen = new Set()
    aliases.forEach((a) => {
      const name = a.name || c.name
      const key = `${a._metadataId || ''}::${name}`
      if (seen.has(key)) return
      seen.add(key)
      out.push({
        id: key,
        name,
        sourceName: c.name,
        isAlias: name !== c.name,
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
  const [ruleState, setRuleState] = useState({}) // column name -> 'skip' | undefined
  const [taxonomy, setTaxonomy] = useState({ sector: 'Demography', theme: 'Vital Statistics', product: 'Delhi Vital Statistics' })
  const [ncoMatchesByCol, setNcoMatchesByCol] = useState({})
  const [ncoLoading, setNcoLoading] = useState(false)
  const [ncoError, setNcoError] = useState('')
  const [fillAiLoading, setFillAiLoading] = useState(false)
  const [fillAiError, setFillAiError] = useState('')

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
    }

    ;(ids.length ? loadFromGroups() : loadRecent())
      .then(apply)
      .catch((e) => { if (!cancelled) setLoadError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [metadataIds])

  const activeColumn = classifiedColumns.find((c) => c.name === selectedCol)
  const activeCodes = columnCodes[selectedCol] || []
  const ncoMatches = (selectedCol && ncoMatchesByCol[selectedCol]) || null
  const columnDirty = JSON.stringify(columnCodes[selectedCol]) !== JSON.stringify(savedCodes[selectedCol])

  const setCodeField = (rowIndex, field, value) => {
    setColumnCodes((prev) => ({
      ...prev,
      [selectedCol]: prev[selectedCol].map((row, i) => (i === rowIndex ? { ...row, [field]: value } : row)),
    }))
  }
  const persistColumnCodes = (column, rows) => {
    if (!column || !rows) return
    const codes = rows.map((row) => ({ ...row }))
    setSavedCodes((prev) => ({ ...prev, [column.name]: codes }))
    const aliases = column.aliases?.length
      ? column.aliases
      : [{ name: column.name, _metadataId: column._metadataId }]
    const byGroup = {}
    aliases.forEach((a) => {
      if (!a._metadataId || !a.name) return
      if (!byGroup[a._metadataId]) byGroup[a._metadataId] = []
      if (!byGroup[a._metadataId].includes(a.name)) byGroup[a._metadataId].push(a.name)
    })
    const entries = Object.entries(byGroup)
    if (!entries.length) return
    setSaving(true)
    Promise.all(entries.map(([ownerId, names]) =>
      fetch(`/api/catalogue/metadata-groups/${ownerId}/classifications`, withAuthHeaders({
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ column_name: names[0], column_names: names, codes }),
      }))
    ))
      .catch(() => {})
      .finally(() => setSaving(false))
  }

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
        persistColumnCodes(activeColumn, nextRows)
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
  const ruleDone = (name) => ruleState[name] === 'skip' || columnMapped(name)
  const classReady = classified && classifiedColumns.length > 0 && classifiedColumns.every((c) => ruleDone(c.name))
  const harmoniseEntries = flattenForHarmonise(classifiedColumns)

  return (
    <div className="classify-step">
      <div className="classify-run-card">
        <div>
          <div className="classify-run-eyebrow">{datasetLabel}</div>
          <div className="classify-run-title">Classify columns and harmonise values</div>
          <div className="classify-run-blurb">DHARA reads every column, proposes a standard concept and drafts code-list mappings for review.</div>
        </div>
        <button className="classify-run-btn" onClick={() => setClassified(true)}>
          {classified ? 'Re-run classification' : 'Run classification'}
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
                  key={c.name}
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
                          Fills Code and Definition above from the suggested NCO code and title. The table below stays so you can see level and confidence. Edit and Save as needed.
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
                              const col = classifiedColumns.find((c) => c.name === occName)
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
                              persistColumnCodes(col, nextRows)
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
                {classifiedColumns.filter((c) => ruleDone(c.name)).length} of {classifiedColumns.length} lists ready
                {harmoniseEntries.length > classifiedColumns.length
                  ? ` · ${harmoniseEntries.length} columns including duplicates`
                  : ''}
              </span>
            </div>
            {harmoniseEntries.map((entry) => {
              const { id, name, sourceName, isAlias, column: c } = entry
              const rows = columnCodes[sourceName] || []
              const open = openRule === id
              const done = ruleDone(sourceName)
              const skipped = ruleState[sourceName] === 'skip'
              const mappedCount = rows.filter(rowMapped).length
              const occ = isOccupationColumn(sourceName) || isOccupationColumn(name)
              const reviewCount = occ ? ncoReviewCount(sourceName) : 0
              const review = occ && columnNeedsNcoReview(sourceName)
              const detail = isAlias
                ? `Same mapping as ${sourceName}${occ ? ' (NCO applied)' : ''}`
                : occ
                  ? (review ? `${reviewCount} value${reviewCount === 1 ? '' : 's'} need review` : 'Value → NCO code and title')
                  : 'Value → code and definition from classification'
              const status = skipped ? 'Skipped' : review ? 'Needs review' : done ? 'Ready' : 'Needs review'
              const countLabel = occ && reviewCount > 0
                ? `${reviewCount} needs review`
                : `${mappedCount} of ${rows.length} mapped`
              return (
                <div className="classify-rule" key={id}>
                  <div className="classify-rule-head" onClick={() => setOpenRule(open ? null : id)}>
                    <span className={`classify-rule-dot${done && !review ? ' classify-rule-dot-done' : ''}`} />
                    <div className="classify-rule-text">
                      <div className="classify-rule-title">{name}</div>
                      <div className="classify-rule-detail">{detail}</div>
                    </div>
                    <span className={`classify-rule-status${done && !review ? ' classify-rule-status-done' : ''}`}>
                      {status}
                    </span>
                    <span className="classify-rule-count">{countLabel}</span>
                    <span className={`classify-rule-chev${open ? ' classify-rule-chev-open' : ''}`}>▾</span>
                  </div>
                  {open && (
                    <div className="classify-rule-body">
                      <div className="classify-rule-actions">
                        <button
                          type="button"
                          className="classify-skip-btn"
                          onClick={() => setRuleState((prev) => ({ ...prev, [sourceName]: prev[sourceName] === 'skip' ? undefined : 'skip' }))}
                        >
                          {skipped ? 'Unskip' : 'Skip this column'}
                        </button>
                      </div>
                      <div className="classify-map-table classify-map-table-review">
                        <div className="classify-map-head classify-map-head-review">
                          <div>#</div>
                          <div>Value in file</div>
                          <div>Code</div>
                          <div>Definition</div>
                          <div>Match</div>
                        </div>
                        {rows.map((row, i) => {
                          const m = occ ? (ncoMatchesByCol[sourceName] || {})[row.value] : null
                          const filled = rowMapped(row)
                          const rowReview = Boolean(m?.needs_manual_review)
                          return (
                            <div className="classify-map-row classify-map-head-review" key={row.value || i}>
                              <div className="classify-map-n">{i + 1}</div>
                              <div className="classify-map-source">
                                <div>{row.value}</div>
                                {m && (
                                  <div className="classify-map-source-meta">
                                    {m.level}
                                    {rowReview ? ' · review' : ''}
                                    {m.codes?.length > 1 ? ' · both valid' : ''}
                                  </div>
                                )}
                              </div>
                              <div className="classify-map-source">{row.code || '—'}</div>
                              <div className="classify-map-source">{row.definition || '—'}</div>
                              <div className={`classify-map-mark${rowReview ? ' classify-map-mark-review' : ''}`}>
                                {rowReview ? '!' : filled ? '✓' : '—'}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
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
                <select className="classify-select" value={taxonomy.theme} onChange={(e) => setTaxonomy((p) => ({ ...p, theme: e.target.value }))}>
                  {['Vital Statistics', 'Civil Registration', 'Workforce'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="classify-field">
                <label className="classify-label">Data product</label>
                <select className="classify-select" value={taxonomy.product} onChange={(e) => setTaxonomy((p) => ({ ...p, product: e.target.value }))}>
                  {['Delhi Vital Statistics', 'Delhi Labour Statistics', 'New data product'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
            </div>
            <div className="classify-tag-list">
              {TAGS.map((t) => <span className="classify-tag-chip" key={t}>{t}</span>)}
            </div>
          </div>
        </>
      )}

      <div className="classify-continue-row">
        <button className="console-primary-btn" disabled={!classReady} onClick={onContinue}>Continue to publish →</button>
        <span className="classify-continue-hint">
          {classified ? (classReady ? 'All columns ready.' : 'Fill or skip remaining columns to continue.') : 'Run classification to continue.'}
        </span>
      </div>
    </div>
  )
}
