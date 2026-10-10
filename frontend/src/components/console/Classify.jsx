'use client'

import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import { useApp } from '../../context/AppContext'
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

function ConfirmDialog({ title, body, onCancel, onContinue, continueLabel = 'Continue anyway' }) {
  if (typeof document === 'undefined') return null
  return createPortal(
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true">
      <div className="flex max-h-[min(560px,85vh)] w-full max-w-lg flex-col gap-3.5 rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">{title}</div>
        <div className="min-h-0 overflow-y-auto text-[14px] leading-snug text-ink-soft">{body}</div>
        <div className="flex flex-none items-center justify-end gap-2.5">
          <Button variant="secondary" onClick={onCancel}>Go back</Button>
          <Button variant="primary" onClick={onContinue}>{continueLabel}</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export default function Classify({
  metadataIds,
  datasetLabel,
  phase = 'classification',
  hasKey = false,
  onGoSettings,
  onPhaseChange,
  onClassificationCompleteChange,
  onRegisterGoToHarmonisation,
  onContinue,
}) {
  const { keySaved } = useApp()
  const router = useRouter()
  const hasLlmKey = hasKey || keySaved
  const [loading, setLoading] = useState(true)
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
  const [ncoStandardReady, setNcoStandardReady] = useState(false)
  const [ncoNeedsStandard, setNcoNeedsStandard] = useState(false)
  const [fillAiLoading, setFillAiLoading] = useState(false)
  const [fillAiError, setFillAiError] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState('')
  const [publishConfirm, setPublishConfirm] = useState(null)
  const [harmoniseConfirm, setHarmoniseConfirm] = useState(null)
  const [highlightIncomplete, setHighlightIncomplete] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch('/api/catalogue/classification-standards', withAuthHeaders())
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || 'Failed to load standards')
        return Array.isArray(data.standards) ? data.standards : []
      })
      .then((standards) => {
        if (cancelled) return
        setNcoStandardReady(standards.some((s) => s.is_selected))
      })
      .catch(() => {
        if (!cancelled) setNcoStandardReady(false)
      })
    return () => { cancelled = true }
  }, [])

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
      }).filter((a) => {
        if (!a.value || !a.code) return false
        // Only persist real NCO digit codes — never identity label→label maps.
        if (!/^\d{1,4}(?:\.\d+)*$/.test(a.code)) return false
        if (a.code.toLowerCase() === String(a.value).trim().toLowerCase()) return false
        return true
      })
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
      }).filter((a) => {
        if (!a.value || !a.code) return false
        if (!/^\d{1,4}(?:\.\d+)*$/.test(a.code)) return false
        if (a.code.toLowerCase() === String(a.value).trim().toLowerCase()) return false
        return true
      })
      if (aliases.length) {
        fetch('/api/catalogue/nco-aliases', withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ aliases }),
        })).catch(() => {})
      }
    }
  }

  const fillDefinitionsWithAi = ({ allowOccupation = false } = {}) => {
    if (!activeColumn) return
    if (!allowOccupation && isOccupationColumn(selectedCol)) return
    if (!hasLlmKey) {
      setFillAiError('LLM key not configured — add your API key in Settings to fill definitions with AI.')
      return
    }
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
      body: JSON.stringify({ columns, allow_occupation: Boolean(allowOccupation) }),
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
          const value = String(row.value ?? '')
          const raw = defs[row.value]
            || (row.code ? defs[row.code] : undefined)
            || Object.entries(defs).find(([k]) => k.trim().toLowerCase() === value.trim().toLowerCase())?.[1]
          let definition = row.definition
          if (typeof raw === 'string' && raw.trim()) {
            definition = raw
          } else if (raw && typeof raw === 'object' && String(raw.definition || '').trim()) {
            definition = String(raw.definition)
          }
          // On Fill with AI: copy value → code (no AI). Definition comes from AI above.
          return {
            ...row,
            code: value,
            definition: definition ?? '',
          }
        })
        setColumnCodes((prev) => ({ ...prev, [activeColumn.name]: nextRows }))
        if (allowOccupation) {
          setNcoNeedsStandard(false)
          setNcoError('')
        }
      })
      .catch((e) => setFillAiError(e.message))
      .finally(() => setFillAiLoading(false))
  }

  const goClassificationSettings = () => {
    router.push('/settings?tab=classification')
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
  const classReady = !loading && !loadError && classifiedColumns.length > 0
    && classifiedColumns.every((c) => columnMapped(c.name))
    && harmoniseClubs.every(clubReady)

  // Classification page is complete when every column has code + definition.
  const classificationComplete = !loading && !loadError
    && classifiedColumns.length > 0
    && classifiedColumns.every((c) => columnMapped(c.name))

  // Unlock Harmonisation navigation once columns are loaded (incomplete codes warn first).
  const canOpenHarmonisation = !loading && !loadError && classifiedColumns.length > 0

  useEffect(() => {
    onClassificationCompleteChange?.(canOpenHarmonisation)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canOpenHarmonisation])

  const buildIncompleteSummary = () => {
    let unfilledRows = 0
    let incompleteColumns = 0
    const columnDetails = []
    for (const col of classifiedColumns) {
      const rows = columnCodes[col.name] || []
      const gaps = []
      rows.forEach((row, index) => {
        const missingCode = !String(row?.code || '').trim()
        const missingDefinition = !String(row?.definition || '').trim()
        if (!missingCode && !missingDefinition) return
        const fields = []
        if (missingCode) fields.push('code')
        if (missingDefinition) fields.push('definition')
        gaps.push({
          index,
          value: String(row?.value || '').trim() || `Row ${index + 1}`,
          fields,
        })
      })
      if (gaps.length > 0 || rows.length === 0) {
        incompleteColumns += 1
        unfilledRows += gaps.length || (rows.length === 0 ? 1 : 0)
        columnDetails.push({
          name: col.name,
          emptyList: rows.length === 0,
          gaps,
        })
      }
    }
    const pendingHarmonise = harmoniseClubs.filter((club) => !clubReady(club)).length
    return {
      unfilledRows,
      incompleteColumns,
      pendingHarmonise,
      columnDetails,
      noColumns: !loading && !loadError && classifiedColumns.length === 0,
    }
  }

  // Always track incomplete columns for the locator strip; field highlight in
  // the editor still waits until the user dismisses the incomplete dialog.
  const incompleteColumnNames = useMemo(() => new Set(
    classifiedColumns
      .filter((c) => {
        const rows = columnCodes[c.name] || []
        return rows.length === 0 || rows.some((row) => !rowMapped(row))
      })
      .map((c) => c.name),
  ), [classifiedColumns, columnCodes])

  useEffect(() => {
    if (highlightIncomplete && incompleteColumnNames.size === 0) {
      setHighlightIncomplete(false)
    }
  }, [highlightIncomplete, incompleteColumnNames])

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
    if (summary.noColumns) {
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
    if (!hasLlmKey) {
      setNcoLoading(false)
      setNcoNeedsStandard(false)
      setNcoError('NCO matching key not configured — add your LLM API key in Settings to suggest NCO codes.')
      return
    }

    const runMatch = () => {
      setNcoNeedsStandard(false)
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
          const isAggregateValue = (v) => {
            const s = String(v || '').trim().toLowerCase().replace(/\s+/g, ' ')
            return /^(all|total|grand total|sub ?total|overall|sum)(\s+(occupations|categories|workers|persons|people))?$/.test(s)
          }
          const nextRows = rows.map((row) => {
            // Aggregates must not keep a suggested NCO code.
            if (isAggregateValue(row.value)) {
              return { ...row, code: '', definition: '' }
            }
            const m = matches[row.value]
            if (!m || !m.auto_fill) return row
            if (m.code == null || m.code === '') return row
            const code = String(m.code).trim()
            // Never auto-fill occupation labels into the Code column.
            if (!/^\d{1,4}(?:\.\d+)*$/.test(code)) return row
            return {
              ...row,
              code,
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

    // Re-check so a standard uploaded in Settings is picked up without remount.
    setNcoLoading(true)
    setNcoError('')
    fetch('/api/catalogue/classification-standards', withAuthHeaders())
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || 'Failed to load standards')
        return Array.isArray(data.standards) ? data.standards : []
      })
      .then((standards) => {
        const ready = standards.some((s) => s.is_selected)
        setNcoStandardReady(ready)
        if (!ready) {
          setNcoLoading(false)
          setNcoNeedsStandard(true)
          setNcoError('No classification standard selected. Upload a file in Settings, or fill definitions with AI instead.')
          return
        }
        runMatch()
      })
      .catch(() => {
        if (ncoStandardReady) {
          runMatch()
          return
        }
        setNcoLoading(false)
        setNcoNeedsStandard(true)
        setNcoError('No classification standard selected. Upload a file in Settings, or fill definitions with AI instead.')
      })
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
  const showClassifyBody = canOpenHarmonisation
  const onClassificationPage = phase === 'classification'
  const onHarmonisationPage = phase === 'harmonisation'

  const proceedToHarmonisation = () => {
    setHarmoniseConfirm(null)
    setHighlightIncomplete(false)
    onPhaseChange?.('harmonisation')
  }

  const dismissHarmoniseConfirm = () => {
    const summary = buildIncompleteSummary()
    const firstIncomplete = summary.columnDetails[0]?.name
    if (firstIncomplete) setSelectedCol(firstIncomplete)
    setHighlightIncomplete(true)
    setHarmoniseConfirm(null)
  }

  const attemptGoToHarmonisation = () => {
    if (!canOpenHarmonisation) return
    if (classificationComplete) {
      proceedToHarmonisation()
      return
    }
    const summary = buildIncompleteSummary()
    const n = summary.incompleteColumns
    setHarmoniseConfirm({
      title: 'Classification is incomplete',
      body: (
        <div className="flex flex-col gap-2">
          <p className="m-0">
            You can still continue to harmonisation, but{' '}
            <span className="font-semibold text-ink">
              {n} column{n === 1 ? '' : 's'}
            </span>
            {' '}{n === 1 ? 'is' : 'are'} not completely filled.
          </p>
          <p className="m-0 text-[13px] text-[#8E9398]">
            Go back to highlight those columns.
          </p>
        </div>
      ),
    })
  }

  useEffect(() => {
    onRegisterGoToHarmonisation?.(attemptGoToHarmonisation)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canOpenHarmonisation, classificationComplete, columnCodes, classifiedColumns])

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-4">
      {!hasLlmKey && (
        <div className="rounded-lg border border-[#f3c98b] bg-[#fffaf1] px-4 py-3 text-sm leading-relaxed text-[#8a5a12]">
          <strong>LLM key not configured</strong>
          <div className="mt-1">
            Add your API key in Settings for Fill with AI and NCO matching suggestions. Classification still works without it.
          </div>
          {onGoSettings && (
            <div className="mt-3">
              <Button type="button" onClick={onGoSettings}>Open Settings</Button>
            </div>
          )}
        </div>
      )}

      {loading && (
        <div className={`${cardClass} p-[18px]`}>Loading classified columns…</div>
      )}

      {!loading && loadError && (
        <div className={`${cardClass} p-[18px]`}>Couldn't load classifications: {loadError}</div>
      )}

      {!loading && !loadError && classifiedColumns.length === 0 && (
        <div className={`${cardClass} p-[18px]`}>No classification columns found for this dataset.</div>
      )}

      {onClassificationPage && showClassifyBody && (
        <div className={cardClass}>
          <ColumnChipGrid
            columns={classifiedColumns}
            selectedCol={selectedCol}
            onSelect={setSelectedCol}
            saving={saving}
            incompleteNames={incompleteColumnNames}
            highlightIncomplete={highlightIncomplete}
          />
          {activeColumn && (
            <CodeListEditor
              column={activeColumn}
              codes={activeCodes}
              dirty={columnDirty}
              fillAiLoading={fillAiLoading}
              fillAiError={fillAiError}
              onFillAi={() => fillDefinitionsWithAi({
                allowOccupation: isOccupationColumn(activeColumn.name),
              })}
              ncoLoading={ncoLoading}
              ncoError={ncoError}
              ncoMatches={ncoMatches}
              ncoPanelOpen={ncoPanelOpen}
              onSuggestNco={suggestNcoCodes}
              onCodeFieldChange={setCodeField}
              onSave={saveColumnCodes}
              highlightIncomplete={highlightIncomplete}
              ncoNeedsStandard={ncoNeedsStandard}
              onGoNcoSettings={goClassificationSettings}
            />
          )}
        </div>
      )}

      {onHarmonisationPage && showClassifyBody && (
        <>
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
        {onClassificationPage ? (
          <>
            <Button
              disabled={!canOpenHarmonisation}
              onClick={attemptGoToHarmonisation}
            >
              <span className="inline-flex items-center gap-1.5">
                Continue to harmonisation
                <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
              </span>
            </Button>
            <span className="text-[13px] text-[#8E9398]">
              {classifiedColumns.length === 0
                ? (loading
                  ? 'Loading classification columns…'
                  : 'No columns to harmonise for this dataset.')
                : classificationComplete
                  ? 'All codes and definitions are filled — continue to verify related tables.'
                  : 'You can continue anytime. Empty codes or definitions will ask for confirmation.'}
            </span>
          </>
        ) : (
          <>
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
                : classReady
                  ? 'Catalogue already saved — continue to the publication confirmation.'
                  : 'You can continue anytime. Incomplete codes or harmonisation will ask for confirmation.'}
            </span>
          </>
        )}
      </div>

      {harmoniseConfirm && (
        <ConfirmDialog
          title={harmoniseConfirm.title}
          body={harmoniseConfirm.body}
          continueLabel="Continue anyway"
          onCancel={dismissHarmoniseConfirm}
          onContinue={proceedToHarmonisation}
        />
      )}

      {publishConfirm && (
        <ConfirmDialog
          title={publishConfirm.title}
          body={publishConfirm.body}
          continueLabel="Publish anyway"
          onCancel={() => setPublishConfirm(null)}
          onContinue={runPublish}
        />
      )}
    </div>
  )
}