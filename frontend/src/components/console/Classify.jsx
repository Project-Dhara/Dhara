'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import { useApp } from '../../context/AppContext'
import {
  isLgdColumn,
  isOccupationColumn,
  rowMapped,
  cloneCodeRows,
  collapseEquivalentColumns,
  flattenForHarmonise,
  clubHarmoniseEntries,
} from '../../lib/classifyColumns'
import {
  clearClassifyDraft,
  loadClassifyDraft,
  metadataIdsMatch,
  overlayClassifyDraft,
  saveClassifyDraft,
} from '../../lib/classifyDraft'
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
  const [aliasVerified, setAliasVerified] = useState({})
  const [harmRows, setHarmRows] = useState({})
  const [harmDirty, setHarmDirty] = useState({})
  const [ncoMatchesByCol, setNcoMatchesByCol] = useState({})
  const [ncoLoading, setNcoLoading] = useState(false)
  const [ncoError, setNcoError] = useState('')
  const [ncoRetrievalMode, setNcoRetrievalMode] = useState('')
  const [ncoPanelOpen, setNcoPanelOpen] = useState(false)
  const [ncoStandardReady, setNcoStandardReady] = useState(false)
  const [ncoNeedsStandard, setNcoNeedsStandard] = useState(false)
  const [ncoStage, setNcoStage] = useState('')
  const [ncoProgress, setNcoProgress] = useState(null)
  const [ncoWaitingMessage, setNcoWaitingMessage] = useState('')
  const [ncoJobId, setNcoJobId] = useState('')
  const [ncoAttachToken, setNcoAttachToken] = useState('')
  const [classifyHydrated, setClassifyHydrated] = useState(false)
  const ncoPollRef = useRef(null)
  const ncoBudgetRef = useRef({ startedAt: 0, maxWaitSec: 600, claimed: false })
  const draftFlushRef = useRef({})

  const ncoSessionKey = (col) => `dhara:nco-job:${col || ''}`

  const clearNcoPoll = () => {
    if (ncoPollRef.current) {
      clearTimeout(ncoPollRef.current)
      ncoPollRef.current = null
    }
  }

  const stopWaitingNco = () => {
    const jobId = ncoJobId
    const token = ncoAttachToken
    const col = selectedCol
    clearNcoPoll()
    setNcoLoading(false)
    setNcoStage('')
    setNcoWaitingMessage('')
    if (jobId && token) {
      fetch(
        `/api/catalogue/match-nco/${encodeURIComponent(jobId)}?attach_token=${encodeURIComponent(token)}`,
        withAuthHeaders({ method: 'DELETE' }),
      ).catch(() => {})
    }
    if (col) {
      try { sessionStorage.removeItem(ncoSessionKey(col)) } catch { /* ignore */ }
    }
    setNcoJobId('')
    setNcoAttachToken('')
  }

  const applyNcoMatches = (occName, data) => {
    const matches = data.matches || {}
    // Keep mode internal for any future use; never surface keyword/semantic to users.
    const mode = data.retrieval_mode === 'semantic' ? 'semantic' : 'keyword-only'
    setNcoRetrievalMode(mode)
    setNcoMatchesByCol((prev) => ({ ...prev, [occName]: matches }))
    if (!isOccupationColumn(occName)) return
    const rows = columnCodes[occName] || []
    const isAggregateValue = (v) => {
      const s = String(v || '').trim().toLowerCase().replace(/\s+/g, ' ')
      return /^(all|total|grand total|sub ?total|overall|sum)(\s+(occupations|categories|workers|persons|people))?$/.test(s)
    }
    const nextRows = rows.map((row) => {
      if (isAggregateValue(row.value)) {
        return { ...row, code: '-', definition: '-' }
      }
      const m = matches[row.value]
      if (!m || m.status === 'not_an_occupation') {
        const def = m?.reason
          ? String(m.reason)
          : (m?.status === 'not_an_occupation' ? 'Not an occupation' : '-')
        return { ...row, code: '-', definition: def }
      }
      if (m.status === 'unmatched') {
        return {
          ...row,
          code: '-',
          definition: m.reason != null && m.reason !== '' ? String(m.reason) : '-',
        }
      }
      // Multi-choice / needs_review: leave blank for Confirm — do not invent '-'.
      if (!m.auto_fill) return row
      if (m.code == null || m.code === '') {
        return {
          ...row,
          code: '-',
          definition: m.reason != null && m.reason !== '' ? String(m.reason) : '-',
        }
      }
      const code = String(m.code).trim()
      if (!/^\d{1,4}(?:\.\d+)*$/.test(code)) {
        return {
          ...row,
          code: '-',
          definition: m.reason != null && m.reason !== '' ? String(m.reason) : '-',
        }
      }
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
  }
  const [lgdMatchesByCol, setLgdMatchesByCol] = useState({})
  const [lgdLoading, setLgdLoading] = useState(false)
  const [lgdError, setLgdError] = useState('')
  const [lgdPanelOpen, setLgdPanelOpen] = useState(false)
  const [fillAiLoading, setFillAiLoading] = useState(false)
  const [fillAllAiLoading, setFillAllAiLoading] = useState(false)
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
    setClassifyHydrated(false)
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
      const serverCodes = Object.fromEntries(columns.map((c) => [c.name, cloneCodeRows(c.codes)]))
      let nextSelected = columns[0]?.name ?? null
      let nextCodes = serverCodes
      let nextNco = {}
      let nextLgd = {}
      let nextAlias = {}
      let nextHarmDirty = {}
      let nextRule = {}
      let nextOpenRule = null
      const nextHarm = {}
      clubHarmoniseEntries(columns).forEach((club) => {
        nextHarm[club.id] = cloneCodeRows(serverCodes[club.sourceName] || club.column?.codes)
      })

      // Server state first, then overlay a matching draft (never the reverse).
      const draft = loadClassifyDraft()
      if (draft && metadataIdsMatch(draft.metadataIds, ids)) {
        const over = overlayClassifyDraft({
          selectedCol: nextSelected,
          columnCodes: nextCodes,
          ncoMatchesByCol: nextNco,
          lgdMatchesByCol: nextLgd,
          harmRows: nextHarm,
          harmDirty: nextHarmDirty,
          aliasVerified: nextAlias,
          ruleState: nextRule,
          openRule: nextOpenRule,
        }, draft, ids)
        if (over) {
          nextSelected = over.selectedCol
          nextCodes = over.columnCodes
          nextNco = over.ncoMatchesByCol
          nextLgd = over.lgdMatchesByCol
          Object.assign(nextHarm, over.harmRows || {})
          nextHarmDirty = over.harmDirty
          nextAlias = over.aliasVerified
          nextRule = over.ruleState
          nextOpenRule = over.openRule
        }
      } else if (draft) {
        clearClassifyDraft()
      }

      setClassifiedColumns(columns)
      setColumnCodes(nextCodes)
      setSavedCodes(serverCodes)
      setSelectedCol(nextSelected)
      setNcoMatchesByCol(nextNco)
      setLgdMatchesByCol(nextLgd)
      setHarmRows(nextHarm)
      setHarmDirty(nextHarmDirty)
      setAliasVerified(nextAlias)
      setRuleState(nextRule)
      setOpenRule(nextOpenRule)
      setClassifyHydrated(true)
    }

    const start = ids.length ? loadFromGroups() : loadRecent()

    start
      .then(apply)
      .catch((e) => {
        if (!cancelled) {
          setLoadError(e.message)
          setClassifyHydrated(false)
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [metadataIds])

  // Keep a ref payload for pagehide flush without stale closures.
  useEffect(() => {
    const ids = Array.isArray(metadataIds) ? metadataIds.filter(Boolean) : [metadataIds].filter(Boolean)
    draftFlushRef.current = {
      metadataIds: ids,
      selectedCol,
      columnCodes,
      ncoMatchesByCol,
      lgdMatchesByCol,
      harmRows,
      harmDirty,
      aliasVerified,
      ruleState,
      openRule,
    }
  }, [
    metadataIds, selectedCol, columnCodes, ncoMatchesByCol, lgdMatchesByCol,
    harmRows, harmDirty, aliasVerified, ruleState, openRule,
  ])

  const flushClassifyDraft = () => {
    if (!classifyHydrated) return
    const payload = draftFlushRef.current
    if (!payload?.metadataIds?.length) return
    saveClassifyDraft(payload)
  }

  // Debounced persist — gated until server apply + draft overlay complete.
  useEffect(() => {
    if (!classifyHydrated || loading) return undefined
    const t = setTimeout(() => flushClassifyDraft(), 350)
    return () => clearTimeout(t)
  }, [
    classifyHydrated, loading, metadataIds, selectedCol, columnCodes,
    ncoMatchesByCol, lgdMatchesByCol, harmRows, harmDirty, aliasVerified, ruleState, openRule,
  ])

  useEffect(() => {
    if (!classifyHydrated) return undefined
    const onPageHide = () => flushClassifyDraft()
    const onVis = () => {
      if (document.visibilityState === 'hidden') flushClassifyDraft()
    }
    window.addEventListener('pagehide', onPageHide)
    document.addEventListener('visibilitychange', onVis)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [classifyHydrated])

  const activeColumn = classifiedColumns.find((c) => c.name === selectedCol)
  const activeCodes = columnCodes[selectedCol] || []
  const ncoMatches = (selectedCol && ncoMatchesByCol[selectedCol]) || null
  const lgdMatches = (selectedCol && lgdMatchesByCol[selectedCol]) || null
  const columnDirty = JSON.stringify(columnCodes[selectedCol]) !== JSON.stringify(savedCodes[selectedCol])

  useEffect(() => {
    setNcoPanelOpen(Boolean(selectedCol && ncoMatchesByCol[selectedCol]))
    setNcoError('')
    setLgdPanelOpen(Boolean(selectedCol && lgdMatchesByCol[selectedCol]))
    setLgdError('')
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
          // Align draft for saved column(s); keep other columns' unsaved draft values.
          setColumnCodes((prev) => {
            const next = { ...prev, [markSavedName]: codes }
            draftFlushRef.current = {
              ...draftFlushRef.current,
              columnCodes: next,
            }
            if (classifyHydrated) {
              saveClassifyDraft({
                ...draftFlushRef.current,
                columnCodes: next,
              })
            }
            return next
          })
        }
      })
      .catch(() => {
        // Failed save: leave draft unchanged.
      })
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

  const persistHarmoniseEntry = (entry, rows, { learnAliases = false } = {}) => {
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
    // Learn aliases only from explicit Verify — never from ordinary Save / auto-fill.
    if (
      learnAliases
      && (isOccupationColumn(entry.sourceName) || isOccupationColumn(entry.name))
    ) {
      const matches = ncoMatchesByCol[entry.sourceName] || {}
      const aliases = (rows || []).map((row) => {
        const m = matches[row.value]
        const level = m?.level || 'division'
        return {
          value: row.value,
          code: String(row.code || '').trim(),
          title: String(row.definition || m?.title || '').trim() || null,
          level,
          ambiguous: Boolean(m?.ambiguous),
        }
      }).filter((a) => {
        if (!a.value || !a.code) return false
        if (a.ambiguous) return false
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
        }))
          .then(async (res) => {
            const data = await res.json().catch(() => ({}))
            if (Array.isArray(data.conflicts) && data.conflicts.length) {
              console.warn('NCO alias conflicts (existing mappings kept):', data.conflicts)
            }
          })
          .catch(() => {})
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
    // Ordinary Save must not learn aliases (auto-fill / LLM rows would poison memory).
    persistColumnCodes(activeColumn, columnCodes[selectedCol])
  }

  const applyAiDefinitions = (byCol, columnNames, { clearNcoGate = false, overwrite = false } = {}) => {
    // Default: only fill blank definitions so steward/manual text is preserved.
    // Pass overwrite=true only for an explicit "refill all" request.
    let applied = 0
    for (const name of columnNames) {
      const defs = byCol[name] || {}
      for (const row of (columnCodes[name] || [])) {
        const value = String(row.value ?? '')
        const existing = String(row.definition ?? '').trim()
        if (existing && !overwrite) continue
        const raw = defs[row.value]
          || (row.code ? defs[row.code] : undefined)
          || Object.entries(defs).find(([k]) => k.trim().toLowerCase() === value.trim().toLowerCase())?.[1]
        if (typeof raw === 'string' && raw.trim()) applied += 1
        else if (raw && typeof raw === 'object' && String(raw.definition || '').trim()) applied += 1
      }
    }
    setColumnCodes((prev) => {
      const next = { ...prev }
      for (const name of columnNames) {
        const defs = byCol[name] || {}
        next[name] = (prev[name] || []).map((row) => {
          const value = String(row.value ?? '')
          const existing = String(row.definition ?? '').trim()
          if (existing && !overwrite) {
            return row
          }
          const raw = defs[row.value]
            || (row.code ? defs[row.code] : undefined)
            || Object.entries(defs).find(([k]) => k.trim().toLowerCase() === value.trim().toLowerCase())?.[1]
          let definition = row.definition
          if (typeof raw === 'string' && raw.trim()) {
            definition = raw
          } else if (raw && typeof raw === 'object' && String(raw.definition || '').trim()) {
            definition = String(raw.definition)
          }
          // Fill with AI only writes definitions. Code stays manual except when
          // Suggest NCO codes auto-fills a high-confidence NCO digit code.
          return {
            ...row,
            definition: definition ?? '',
          }
        })
      }
      return next
    })
    if (clearNcoGate) {
      setNcoNeedsStandard(false)
      setNcoError('')
    }
    return applied
  }

  const valuesNeedingDefinitions = (colName) => (
    (columnCodes[colName] || [])
      .filter((r) => !String(r.definition || '').trim())
      .map((r) => r.value || r.code)
      .filter(Boolean)
  )

  const summarizeFillErrors = (errors, filledCount) => {
    const list = Array.isArray(errors) ? errors : []
    if (!list.length) return ''
    const sample = list[0]?.error || list[0]?.column || 'unknown'
    if (filledCount > 0) {
      return `Filled ${filledCount} definition${filledCount !== 1 ? 's' : ''}; ${list.length} batch${list.length !== 1 ? 'es' : ''} failed (${sample}).`
    }
    return list.length === 1
      ? `Could not fill definitions (${sample}).`
      : `Could not fill definitions (${list.length} errors). ${sample}`
  }

  const requestFillDefinitions = (columns, { allowOccupation = false } = {}) => (
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
  )

  const fillDefinitionsWithAi = ({ allowOccupation = false } = {}) => {
    if (!activeColumn) return
    if (!allowOccupation && isOccupationColumn(selectedCol)) return
    if (!hasLlmKey) {
      setFillAiError('LLM key not configured — add your API key in Settings to fill definitions with AI.')
      return
    }
    // Retries only request values that still lack a definition.
    const columns = [{
      name: activeColumn.name,
      metadata_id: activeColumn._metadataId || activeColumn.aliases?.[0]?._metadataId || null,
      values: valuesNeedingDefinitions(activeColumn.name),
    }].filter((c) => c.values.length)
    if (!columns.length) {
      setFillAiError('All definitions are already filled for this column.')
      return
    }
    setFillAiLoading(true)
    setFillAiError('')
    requestFillDefinitions(columns, { allowOccupation })
      .then((data) => {
        const applied = applyAiDefinitions(data.definitions || {}, [activeColumn.name], {
          clearNcoGate: allowOccupation,
        })
        const errMsg = summarizeFillErrors(data.errors, applied)
        if (errMsg) setFillAiError(errMsg)
        else if (applied === 0) setFillAiError('AI returned no definitions for the remaining values.')
      })
      .catch((e) => setFillAiError(e.message))
      .finally(() => setFillAiLoading(false))
  }

  const fillAllDefinitionsWithAi = () => {
    if (!hasLlmKey) {
      setFillAiError('LLM key not configured — add your API key in Settings to fill definitions with AI.')
      return
    }
    const columns = classifiedColumns.map((col) => ({
      name: col.name,
      metadata_id: col._metadataId || col.aliases?.[0]?._metadataId || null,
      values: valuesNeedingDefinitions(col.name),
    })).filter((c) => c.values.length)
    if (!columns.length) {
      setFillAiError('All definitions are already filled.')
      return
    }
    setFillAiLoading(true)
    setFillAllAiLoading(true)
    setFillAiError('')
    requestFillDefinitions(columns, { allowOccupation: true })
      .then((data) => {
        const names = columns.map((c) => c.name)
        const applied = applyAiDefinitions(
          data.definitions || {},
          names,
          { clearNcoGate: true },
        )
        const errMsg = summarizeFillErrors(data.errors, applied)
        if (errMsg) setFillAiError(errMsg)
        else if (applied === 0) setFillAiError('AI returned no definitions for the remaining values.')
      })
      .catch((e) => setFillAiError(e.message))
      .finally(() => {
        setFillAiLoading(false)
        setFillAllAiLoading(false)
      })
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
      clearClassifyDraft()
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

  const pollNcoJob = (occName, jobId, attachToken) => {
    clearNcoPoll()
    const tick = () => {
      fetch(`/api/catalogue/match-nco/${encodeURIComponent(jobId)}`, withAuthHeaders())
        .then(async (res) => {
          if (res.status === 404) {
            try { sessionStorage.removeItem(ncoSessionKey(occName)) } catch { /* ignore */ }
            setNcoJobId('')
            setNcoAttachToken('')
            setNcoLoading(false)
            setNcoStage('')
            setNcoError('')
            return null
          }
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'NCO poll failed' }))
            throw new Error(err.detail || 'NCO poll failed')
          }
          return res.json()
        })
        .then((data) => {
          if (!data) return
          setNcoStage(data.stage || data.status || '')
          setNcoProgress(data.progress || null)
          setNcoWaitingMessage(data.worker_message || '')
          const status = String(data.status || '')
          const claimedAt = data.claimed_at
          const maxWait = Number(data.max_wait_sec) || ncoBudgetRef.current.maxWaitSec || 600
          ncoBudgetRef.current.maxWaitSec = maxWait
          if (claimedAt && !ncoBudgetRef.current.claimed) {
            ncoBudgetRef.current.claimed = true
            ncoBudgetRef.current.startedAt = Date.now()
          }
          if (ncoBudgetRef.current.claimed) {
            const elapsed = (Date.now() - ncoBudgetRef.current.startedAt) / 1000
            if (elapsed > maxWait && status !== 'done' && status !== 'error') {
              setNcoError('Timed out waiting for NCO match. You can Suggest again — a finished job may still be cached briefly.')
              setNcoLoading(false)
              clearNcoPoll()
              return
            }
          }
          if (status === 'done') {
            applyNcoMatches(occName, data)
            try { sessionStorage.removeItem(ncoSessionKey(occName)) } catch { /* ignore */ }
            setNcoJobId('')
            setNcoAttachToken('')
            setNcoLoading(false)
            setNcoStage('')
            clearNcoPoll()
            return
          }
          if (status === 'error' || status === 'cancelled') {
            setNcoError(data.error || 'NCO matching failed')
            try { sessionStorage.removeItem(ncoSessionKey(occName)) } catch { /* ignore */ }
            setNcoJobId('')
            setNcoAttachToken('')
            setNcoLoading(false)
            clearNcoPoll()
            return
          }
          ncoPollRef.current = setTimeout(tick, 1500)
        })
        .catch((e) => {
          setNcoError(e.message)
          setNcoLoading(false)
          clearNcoPoll()
        })
    }
    tick()
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
      const occName = selectedCol
      clearNcoPoll()
      setNcoLoading(true)
      setNcoError('')
      setNcoRetrievalMode('')
      setNcoStage('queued')
      setNcoProgress(null)
      setNcoWaitingMessage('')
      ncoBudgetRef.current = { startedAt: Date.now(), maxWaitSec: 600, claimed: false }
      fetch('/api/catalogue/match-nco', withAuthHeaders(withLlmKeyHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values }),
      })))
        .then(async (res) => {
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'NCO matching failed' }))
            throw new Error(typeof err.detail === 'string' ? err.detail : 'NCO matching failed')
          }
          return res.json()
        })
        .then((data) => {
          // Desktop async: job_id. Docker sync: matches object.
          if (data.job_id) {
            const jobId = String(data.job_id)
            const token = String(data.attach_token || '')
            setNcoJobId(jobId)
            setNcoAttachToken(token)
            setNcoStage(data.stage || data.status || 'queued')
            if (data.max_wait_sec) {
              ncoBudgetRef.current.maxWaitSec = Number(data.max_wait_sec) || 600
            }
            try {
              sessionStorage.setItem(
                ncoSessionKey(occName),
                JSON.stringify({ job_id: jobId, attach_token: token }),
              )
            } catch { /* ignore */ }
            if (String(data.status || '') === 'done' && data.matches) {
              applyNcoMatches(occName, data)
              try { sessionStorage.removeItem(ncoSessionKey(occName)) } catch { /* ignore */ }
              setNcoLoading(false)
              return
            }
            pollNcoJob(occName, jobId, token)
            return
          }
          applyNcoMatches(occName, data)
          setNcoLoading(false)
        })
        .catch((e) => {
          setNcoError(e.message)
          setNcoLoading(false)
        })
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

  // Re-attach in-flight job from sessionStorage (refresh / remount). Never DELETE on unmount.
  useEffect(() => {
    if (!selectedCol || !isOccupationColumn(selectedCol)) return undefined
    let raw = null
    try { raw = sessionStorage.getItem(ncoSessionKey(selectedCol)) } catch { return undefined }
    if (!raw) return undefined
    let parsed
    try { parsed = JSON.parse(raw) } catch { return undefined }
    const jobId = parsed?.job_id
    const token = parsed?.attach_token
    if (!jobId || !token) return undefined
    setNcoPanelOpen(true)
    setNcoLoading(true)
    setNcoJobId(jobId)
    setNcoAttachToken(token)
    ncoBudgetRef.current = { startedAt: Date.now(), maxWaitSec: 600, claimed: false }
    pollNcoJob(selectedCol, jobId, token)
    return () => { clearNcoPoll() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCol])

  const pickLgdCandidate = (value, candidate) => {
    const targetCol = selectedCol
    if (!targetCol || !candidate) return
    const code = String(candidate.code || candidate.lgd_code || '').trim()
    if (!code) return
    const title = candidate.title != null && candidate.title !== ''
      ? String(candidate.title)
      : (candidate.name_english != null && candidate.name_english !== ''
        ? String(candidate.name_english)
        : '')
    setColumnCodes((prev) => {
      const rows = prev[targetCol] || []
      return {
        ...prev,
        [targetCol]: rows.map((row) => (
          row.value === value
            ? { ...row, code, definition: title || row.definition }
            : row
        )),
      }
    })
    setLgdMatchesByCol((prev) => {
      const colMatches = { ...(prev[targetCol] || {}) }
      const existing = colMatches[value]
      if (!existing) return prev
      colMatches[value] = {
        ...existing,
        code,
        lgd_code: code,
        title: title || existing.title,
        name_english: title || existing.name_english,
        entity_type: candidate.entity_type || existing.entity_type,
        level: candidate.entity_type || existing.level,
        hierarchy: candidate.hierarchy ?? existing.hierarchy,
        hierarchy_parts: candidate.hierarchy_parts ?? existing.hierarchy_parts,
        ambiguous: false,
        auto_fill: false,
        needs_manual_review: false,
        confidence: 'high',
        chosen: true,
      }
      return { ...prev, [targetCol]: colMatches }
    })
  }

  const confirmNcoPicks = (picks) => {
    const targetCol = selectedCol
    if (!targetCol || !picks || typeof picks !== 'object') return
    const entries = Object.entries(picks).filter(([, candidate]) => candidate)
    if (!entries.length) return

    const applied = new Map()
    for (const [value, candidate] of entries) {
      const code = String(candidate.code || '').trim()
      if (!code || !/^\d{1,4}(?:\.\d+)*$/.test(code)) continue
      const title = candidate.title != null && candidate.title !== ''
        ? String(candidate.title)
        : ''
      const level = candidate.level || 'division'
      applied.set(value, {
        code,
        title,
        level,
        division_code: candidate.division_code ?? null,
        division_title: candidate.division_title ?? null,
        subdivision_code: candidate.subdivision_code ?? null,
        subdivision_title: candidate.subdivision_title ?? null,
        group_code: candidate.group_code ?? null,
        group_title: candidate.group_title ?? null,
        family_code: candidate.family_code ?? null,
        family_title: candidate.family_title ?? null,
      })
    }
    if (!applied.size) return

    setColumnCodes((prev) => {
      const rows = prev[targetCol] || []
      return {
        ...prev,
        [targetCol]: rows.map((row) => {
          const pick = applied.get(row.value)
          if (!pick) return row
          return {
            ...row,
            code: pick.code,
            definition: pick.title || row.definition,
          }
        }),
      }
    })
    setNcoMatchesByCol((prev) => {
      const colMatches = { ...(prev[targetCol] || {}) }
      let changed = false
      for (const [value, pick] of applied) {
        const existing = colMatches[value]
        if (!existing) continue
        changed = true
        colMatches[value] = {
          ...existing,
          code: pick.code,
          title: pick.title || existing.title,
          level: pick.level,
          division_code: pick.division_code ?? existing.division_code,
          division_title: pick.division_title ?? existing.division_title,
          subdivision_code: pick.subdivision_code ?? existing.subdivision_code,
          subdivision_title: pick.subdivision_title ?? existing.subdivision_title,
          group_code: pick.group_code ?? existing.group_code,
          group_title: pick.group_title ?? existing.group_title,
          family_code: pick.family_code ?? existing.family_code,
          family_title: pick.family_title ?? existing.family_title,
          ambiguous: false,
          auto_fill: false,
          needs_manual_review: false,
          confidence: 'high',
          status: 'steward_pick',
          chosen: true,
        }
      }
      if (!changed) return prev
      return { ...prev, [targetCol]: colMatches }
    })
    setNcoPanelOpen(false)
  }

  const closeNcoPreview = () => {
    setNcoPanelOpen(false)
  }

  const suggestLgdCodes = () => {
    const targetCol = selectedCol
    if (!targetCol || !isLgdColumn(targetCol) || isOccupationColumn(targetCol)) return
    const rows = columnCodes[targetCol] || []
    const values = rows.map((r) => r.value || r.code).filter(Boolean)
    if (!values.length) return

    setLgdPanelOpen(true)
    setLgdLoading(true)
    setLgdError('')
    fetch('/api/catalogue/match-lgd', withAuthHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    }))
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'LGD matching failed' }))
          const detail = err.detail
          throw new Error(
            typeof detail === 'string'
              ? detail
              : (Array.isArray(detail) ? detail.map((d) => d.msg || d).join('; ') : 'LGD matching failed'),
          )
        }
        return res.json()
      })
      .then((data) => {
        const matches = data.matches || {}
        setLgdMatchesByCol((prev) => ({ ...prev, [targetCol]: matches }))
        if (!isLgdColumn(targetCol)) return
        // Fill Code/Definition only when the steward clicks Suggest.
        setColumnCodes((prev) => {
          const current = prev[targetCol] || rows
          const nextRows = current.map((row) => {
            const m = matches[row.value]
            // No directory hit → mark as not found (do not leave blank).
            if (!m) {
              return { ...row, code: '-', definition: '-' }
            }
            // Ambiguous / review-only: leave for steward pick; do not invent a code.
            if (!m.auto_fill) return row
            const code = String(m.code || m.lgd_code || '').trim()
            if (!code || !/^\d+$/.test(code)) {
              return { ...row, code: '-', definition: '-' }
            }
            return {
              ...row,
              code,
              definition: m.title != null && m.title !== ''
                ? String(m.title)
                : (m.name_english != null && m.name_english !== '' ? String(m.name_english) : row.definition),
            }
          })
          return { ...prev, [targetCol]: nextRows }
        })
      })
      .catch((e) => setLgdError(e.message))
      .finally(() => setLgdLoading(false))
  }

  const selectHarmoniseEntry = (id) => setOpenRule(id)
  const toggleHarmoniseSkip = (id) => setRuleState((prev) => ({ ...prev, [id]: prev[id] === 'skip' ? undefined : 'skip' }))
  const verifyAndSaveHarmoniseEntry = (entry, rows) => {
    persistHarmoniseEntry(entry, rows, { learnAliases: true })
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
            fillAllAiLoading={fillAllAiLoading}
            fillAiBusy={fillAiLoading}
            fillAllAiError={fillAiError}
            canFillAll={classifiedColumns.some((c) => (columnCodes[c.name] || []).length > 0)}
            onFillAllAi={fillAllDefinitionsWithAi}
          />
          {activeColumn && (
            <CodeListEditor
              column={activeColumn}
              codes={activeCodes}
              dirty={columnDirty}
              fillAiLoading={fillAiLoading}
              fillAiError={fillAllAiLoading ? '' : fillAiError}
              onFillAi={() => fillDefinitionsWithAi({
                allowOccupation: isOccupationColumn(activeColumn.name),
              })}
              ncoLoading={ncoLoading}
              ncoError={ncoError}
              ncoRetrievalMode={ncoRetrievalMode}
              ncoMatches={ncoMatches}
              ncoStage={ncoStage}
              ncoProgress={ncoProgress}
              ncoWaitingMessage={ncoWaitingMessage}
              ncoPanelOpen={ncoPanelOpen}
              onSuggestNco={suggestNcoCodes}
              onStopWaitingNco={stopWaitingNco}
              lgdLoading={lgdLoading}
              lgdError={lgdError}
              lgdMatches={lgdMatches}
              lgdPanelOpen={lgdPanelOpen}
              onSuggestLgd={suggestLgdCodes}
              onPickLgdCandidate={pickLgdCandidate}
              onConfirmNcoPicks={confirmNcoPicks}
              onNcoPreviewClose={closeNcoPreview}
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
          lgdMatchesByCol={lgdMatchesByCol}
          onVerifyAndSave={verifyAndSaveHarmoniseEntry}
          onSaveChanges={persistHarmoniseEntry}
          onFieldChange={setHarmField}
        />
      )}

      <div className="flex items-center justify-between gap-3.5">
        {onClassificationPage ? (
          <>
            <span className="min-w-0 text-[13px] text-[#8E9398]">
              {classifiedColumns.length === 0
                ? (loading
                  ? 'Loading classification columns…'
                  : 'No columns to harmonise for this dataset.')
                : classificationComplete
                  ? 'All codes and definitions are filled — continue to verify related tables.'
                  : 'You can continue anytime. Empty codes or definitions will ask for confirmation.'}
            </span>
            <Button
              className="flex-none"
              disabled={!canOpenHarmonisation}
              onClick={attemptGoToHarmonisation}
            >
              <span className="inline-flex items-center gap-1.5">
                Continue to harmonisation
                <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
              </span>
            </Button>
          </>
        ) : (
          <>
            <span className="min-w-0 text-[13px] text-[#8E9398]">
              {publishError
                ? publishError
                : classReady
                  ? 'Catalogue already saved — continue to the publication confirmation.'
                  : ''}
            </span>
            <Button className="flex-none" disabled={publishing} onClick={publishRelease}>
              {publishing ? 'Continuing…' : (
                <span className="inline-flex items-center gap-1.5">
                  Continue to publish
                  <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
                </span>
              )}
            </Button>
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