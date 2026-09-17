'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight } from 'lucide-react'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import { STATISTICS_OPTIONS } from '../../lib/settingsConfig'
import {
  delhiProductForTheme,
  initialTaxonomy,
  isOccupationColumn,
  rowMapped,
  cloneCodeRows,
  collapseEquivalentColumns,
  flattenForHarmonise,
  clubHarmoniseEntries,
} from '../../lib/classifyColumns'
import Button from '../ui/Button'
import ColumnChipGrid from './classify/ColumnChipGrid'
import CodeListEditor from './classify/CodeListEditor'
import HarmonisePanel from './classify/HarmonisePanel'

// The classified columns (name/concept/note + code list) come from the real
// metadata-excel classification sheets, fetched below — see
// backend/catalogue/classifications.py::get_metadata_group_classifications and
// backend/metadata/metadata_excel.py::parse_classifications. Code and
// definition are editable (a steward may want to rename/annotate them);
// value is what was actually found in the source data, so it stays fixed.
//
// Pure column-collapsing/aliasing helpers live in ../lib/classifyColumns.js.

function PublishConfirmDialog({ title, body, onCancel, onContinue }) {
  if (typeof document === 'undefined') return null
  return createPortal(
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true">
      <div className="flex max-w-md flex-col gap-3.5 rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">{title}</div>
        <div className="text-[14px] leading-snug text-ink-soft">{body}</div>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" onClick={onCancel}>Go back</Button>
          <Button variant="primary" onClick={onContinue}>Publish anyway</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
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
  const [ncoPanelOpen, setNcoPanelOpen] = useState(false)
  const [fillAiLoading, setFillAiLoading] = useState(false)
  const [fillAiError, setFillAiError] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState('')
  const [publishConfirm, setPublishConfirm] = useState(null)

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
      clubHarmoniseEntries(columns).forEach((club) => {
        harm[club.id] = cloneCodeRows(codes[club.sourceName] || club.column?.codes)
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

  useEffect(() => {
    setNcoPanelOpen(Boolean(selectedCol && ncoMatchesByCol[selectedCol]))
    setNcoError('')
  }, [selectedCol])

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
    const targets = entry.isClub
      ? (entry.members || []).map((m) => ({
          name: m.name,
          _metadataId: m.metadataId || m.column?._metadataId,
        }))
      : [{ name: entry.name, _metadataId: entry.metadataId || entry.column?._metadataId }]
    persistTargets(
      targets,
      rows,
      { markSavedName: entry.sourceName },
    )
    // Learn steward-verified occupation → NCO mappings for future Suggest runs.
    if (isOccupationColumn(entry.sourceName) || isOccupationColumn(entry.name)) {
      const matches = ncoMatchesByCol[entry.sourceName] || {}
      const aliases = (rows || []).map((row) => {
        const m = matches[row.value]
        const level = m?.level || 'division'
        return {
          value: row.value,
          code: String(row.code || '').trim(),
          title: String(row.definition || m?.title || '').trim() || null,
          level,
        }
      }).filter((a) => a.value && a.code)
      if (aliases.length) {
        fetch('/api/catalogue/nco-aliases', withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ aliases }),
        })).catch(() => {})
      }
    }
  }

  const setHarmField = (entry, rowIndex, field, value) => {
    setHarmDirty((prev) => ({ ...prev, [entry.id]: true }))
    setHarmRows((prev) => ({
      ...prev,
      [entry.id]: (prev[entry.id] || columnCodes[entry.sourceName] || []).map((row, i) => (
        i === rowIndex ? { ...row, [field]: value } : row
      )),
    }))
    setCodeFieldFor(entry.sourceName, rowIndex, field, value)
  }

  useEffect(() => {
    setHarmRows((prev) => {
      const next = { ...prev }
      clubHarmoniseEntries(classifiedColumns).forEach((club) => {
        if (harmDirty[club.id] || aliasVerified[club.id]) return
        const source = columnCodes[club.sourceName]
        if (source) next[club.id] = cloneCodeRows(source)
      })
      return next
    })
  }, [columnCodes, classifiedColumns, harmDirty, aliasVerified])

  const saveColumnCodes = () => {
    persistColumnCodes(activeColumn, columnCodes[selectedCol])
    if (activeColumn && isOccupationColumn(activeColumn.name)) {
      const matches = ncoMatchesByCol[activeColumn.name] || {}
      const aliases = (columnCodes[activeColumn.name] || []).map((row) => {
        const m = matches[row.value]
        return {
          value: row.value,
          code: String(row.code || '').trim(),
          title: String(row.definition || m?.title || '').trim() || null,
          level: m?.level || 'division',
        }
      }).filter((a) => a.value && a.code)
      if (aliases.length) {
        fetch('/api/catalogue/nco-aliases', withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ aliases }),
        })).catch(() => {})
      }
    }
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
  const harmoniseClubs = clubHarmoniseEntries(classifiedColumns)
  const clubReady = (club) => {
    if (ruleState[club.id] === 'skip') return true
    if (!aliasVerified[club.id]) return false
    const rows = harmRows[club.id] || columnCodes[club.sourceName] || []
    return rows.length > 0 && rows.every(rowMapped)
  }
  const classReady = classified && classifiedColumns.length > 0
    && classifiedColumns.every((c) => columnMapped(c.name))
    && harmoniseClubs.every(clubReady)

  const buildIncompleteSummary = () => {
    let unfilledRows = 0
    let incompleteColumns = 0
    for (const col of classifiedColumns) {
      const rows = columnCodes[col.name] || []
      const missing = rows.filter((row) => !rowMapped(row)).length
      if (missing > 0 || rows.length === 0) {
        incompleteColumns += 1
        unfilledRows += missing || (rows.length === 0 ? 1 : 0)
      }
    }
    const pendingHarmonise = harmoniseClubs.filter((club) => !clubReady(club)).length
    return {
      unfilledRows,
      incompleteColumns,
      pendingHarmonise,
      notClassified: !classified,
      noColumns: classified && classifiedColumns.length === 0,
    }
  }

  const runPublish = async () => {
    if (publishing) return
    setPublishing(true)
    setPublishError('')
    setPublishConfirm(null)
    try {
      await Promise.resolve(onContinue?.())
    } catch (e) {
      setPublishError(e.message || 'Could not continue to publish')
    } finally {
      setPublishing(false)
    }
  }

  const publishRelease = () => {
    if (publishing) return
    setPublishError('')
    const summary = buildIncompleteSummary()
    const issues = []
    if (summary.notClassified) {
      issues.push('Classification has not been run yet.')
    } else if (summary.noColumns) {
      issues.push('No classification columns were found for this dataset.')
    }
    if (summary.unfilledRows > 0) {
      issues.push(
        `${summary.unfilledRows} code/definition row${summary.unfilledRows === 1 ? '' : 's'} ` +
        `${summary.unfilledRows === 1 ? 'is' : 'are'} still empty across ` +
        `${summary.incompleteColumns} column${summary.incompleteColumns === 1 ? '' : 's'}.`,
      )
    }
    if (summary.pendingHarmonise > 0) {
      issues.push(
        `${summary.pendingHarmonise} harmonisation club${summary.pendingHarmonise === 1 ? '' : 's'} ` +
        `${summary.pendingHarmonise === 1 ? 'has' : 'have'} not been verified or skipped.`,
      )
    }
    if (issues.length === 0) {
      runPublish()
      return
    }
    setPublishConfirm({
      title: 'Classification is incomplete',
      body: (
        <div className="flex flex-col gap-2">
          <p className="m-0">You can still publish, but the following is unfinished:</p>
          <ul className="m-0 list-disc space-y-1 pl-5">
            {issues.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </div>
      ),
    })
  }

  const suggestNcoCodes = () => {
    setNcoPanelOpen(true)
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
        // Only auto-fill Code/Definition for high-confidence hits.
        const rows = columnCodes[occName] || []
        const nextRows = rows.map((row) => {
          const m = matches[row.value]
          if (!m || !m.auto_fill) return row
          if (m.code == null || m.code === '') return row
          return {
            ...row,
            code: String(m.code),
            definition: m.title != null && m.title !== '' ? String(m.title) : row.definition,
          }
        })
        setColumnCodes((prev) => ({ ...prev, [occName]: nextRows }))
        setAliasVerified((prev) => {
          const next = { ...prev }
          delete next[`club:${occName}`]
          flattenForHarmonise(classifiedColumns)
            .filter((e) => e.sourceName === occName)
            .forEach((e) => { delete next[e.id] })
          return next
        })
        setHarmDirty((prev) => {
          const next = { ...prev }
          delete next[`club:${occName}`]
          flattenForHarmonise(classifiedColumns)
            .filter((e) => e.sourceName === occName)
            .forEach((e) => { delete next[e.id] })
          return next
        })
      })
      .catch((e) => setNcoError(e.message))
      .finally(() => setNcoLoading(false))
  }

  const selectHarmoniseEntry = (id) => setOpenRule(id)
  const toggleHarmoniseSkip = (id) => setRuleState((prev) => ({ ...prev, [id]: prev[id] === 'skip' ? undefined : 'skip' }))
  const verifyAndSaveHarmoniseEntry = (entry, rows) => {
    persistHarmoniseEntry(entry, rows)
    setAliasVerified((prev) => {
      const next = { ...prev, [entry.id]: true }
      // Club verify covers every related table in one action.
      ;(entry.members || []).forEach((m) => { next[m.id] = true })
      const remaining = clubHarmoniseEntries(classifiedColumns).filter((club) => {
        if (club.id === entry.id) return false
        if (ruleState[club.id] === 'skip') return false
        if (next[club.id]) return false
        return true
      })
      if (remaining[0]) setOpenRule(remaining[0].id)
      return next
    })
    setHarmDirty((prev) => ({ ...prev, [entry.id]: false }))
  }

  const cardClass = 'overflow-hidden rounded-[10px] border border-line bg-white'

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-4">
      <div className="flex items-center justify-between gap-6 rounded-[10px] border border-line bg-white px-[22px] py-[18px]">
        <div>
          <div className="text-base font-semibold text-ink">Classify columns and harmonise values</div>
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
            <ColumnChipGrid
              columns={classifiedColumns}
              selectedCol={selectedCol}
              onSelect={setSelectedCol}
              saving={saving}
            />
            {activeColumn && (
              <CodeListEditor
                column={activeColumn}
                codes={activeCodes}
                dirty={columnDirty}
                fillAiLoading={fillAiLoading}
                fillAiError={fillAiError}
                onFillAi={fillDefinitionsWithAi}
                ncoLoading={ncoLoading}
                ncoError={ncoError}
                ncoMatches={ncoMatches}
                ncoPanelOpen={ncoPanelOpen}
                onSuggestNco={suggestNcoCodes}
                onCodeFieldChange={setCodeField}
                onSave={saveColumnCodes}
              />
            )}
          </div>

          <HarmonisePanel
            classifiedColumns={classifiedColumns}
            columnCodes={columnCodes}
            harmoniseClubs={harmoniseClubs}
            harmRows={harmRows}
            savedCodes={savedCodes}
            openRule={openRule}
            onSelectEntry={selectHarmoniseEntry}
            ruleState={ruleState}
            onToggleSkip={toggleHarmoniseSkip}
            aliasVerified={aliasVerified}
            harmDirty={harmDirty}
            ncoMatchesByCol={ncoMatchesByCol}
            onVerifyAndSave={verifyAndSaveHarmoniseEntry}
            onSaveChanges={persistHarmoniseEntry}
            onFieldChange={setHarmField}
          />

          <div className={`${cardClass} flex flex-col gap-4 p-[22px]`}>
            <div className="text-[15px] font-semibold text-ink">Catalogue placement</div>
            <div className="grid grid-cols-3 gap-3.5">
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Sector</label>
                <select className="h-10 rounded-md border border-line bg-white px-2.5 text-sm text-ink" value={taxonomy.sector} onChange={(e) => setTaxonomy((p) => ({ ...p, sector: e.target.value }))}>
                  {['Demography', 'Labour and Employment', 'Health', 'Agriculture'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Theme</label>
                <select className="h-10 rounded-md border border-line bg-white px-2.5 text-sm text-ink" value={taxonomy.theme} onChange={(e) => {
                  const theme = e.target.value
                  setTaxonomy((p) => ({ ...p, theme, product: delhiProductForTheme(theme) }))
                }}>
                  {STATISTICS_OPTIONS.map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Data product</label>
                <select className="h-10 rounded-md border border-line bg-white px-2.5 text-sm text-ink" value={taxonomy.product} onChange={(e) => setTaxonomy((p) => ({ ...p, product: e.target.value }))}>
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
        <Button disabled={publishing} onClick={publishRelease}>
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
              ? (classReady
                ? 'Catalogue already saved — continue to the publication confirmation.'
                : 'You can continue anytime. Incomplete codes or harmonisation will ask for confirmation.')
              : 'Run classification when ready, or continue and confirm if details are still incomplete.'}
        </span>
      </div>

      {publishConfirm && (
        <PublishConfirmDialog
          title={publishConfirm.title}
          body={publishConfirm.body}
          onCancel={() => setPublishConfirm(null)}
          onContinue={runPublish}
        />
      )}
    </div>
  )
}