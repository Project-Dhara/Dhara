/**
 * Shared post-preview flow for Excel / PDF / SQL.
 *
 * After format-specific extract + preview, every upload type uses the same
 * catalogue matchResult shape for: grouping → metadata → classify → publish.
 */

/** Preview review status for Source Table ID / Title. */
export function previewReviewStatus(t, savedIds) {
  const saved = savedIds?.has?.(t._uid)
  if (t.id_title_mismatch && !saved) return 'fix'
  if ((t.title_repaired_by_llm || t.table_id_repaired_by_llm) && !saved) return 'ai'
  return 'ok'
}

// Short government table code for a tab button — e.g. "Table : D-12 & D-13"
// → "D12, D13" — pulled from the source's own table-label row (`table.title`,
// which the extractor sets to that raw label, not a display title; see
// backend/extraction/extractor.py's _build_ddi_id for the same
// "letter-digits" pattern).
export function tableCode(table) {
  const src = table.title || ''
  const matches = [...src.matchAll(/\b([A-Za-z])-?(\d+(?:\.\d+)?)\b/g)]
  if (matches.length > 0) {
    const codes = [...new Set(matches.map((m) => `${m[1].toUpperCase()}${m[2]}`))]
    return codes.join(', ')
  }
  const sheet = String(table.sheet || '').trim()
  const genericSheet = !sheet || /^(catalogue|query|table|view|data|base table)$/i.test(sheet)
  if (!genericSheet) return sheet
  const title = String(table.title || '').trim()
  if (title) return title.length > 56 ? `${title.slice(0, 56)}…` : title
  return table.table_id || table.id || 'Table'
}

export function tablePickerLabel(table) {
  const code = tableCode(table)
  const rows = table.row_count != null ? `${table.row_count} rows` : ''
  return rows ? `${code} — ${rows}` : code
}

// Ports of backend title-base helpers — needed client-side so a title
// correction on preview can re-home tables into shared grouping buckets.
export function baseTitle(title) {
  const base = (title || '').replace(/\s*\([^)]*\)\s*$/, '').trim().replace(/\s+/g, ' ').toUpperCase()
  return base || (title || '').trim().toUpperCase()
}

const GROUP_NAME_NOISE = new Set(['sl', 'no'])

export function buildGroupName(base) {
  const title = (base || '').replace(/\s+/g, ' ').trim()
  if (!title) return 'Untitled group'
  const words = title.split(' ')
  while (words.length && GROUP_NAME_NOISE.has(words[0].replace(/[.,]+$/, '').toLowerCase())) {
    words.shift()
  }
  const cleaned = words.join(' ').trim().replace(/^[\s.,-]+|[\s.,-]+$/g, '') || title
  return cleaned.replace(/\S+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
}

export const EMPTY_GROUP_METADATA = {
  title: '', product: '', category: '', geography: '', frequency: '',
  time_period: '', data_source: '', description: '', last_updated: '',
  future_release: '', key_statistics: '', remarks: '',
}

/** PDF job grouping → catalogue matchResult (Excel/SQL shape). */
export function pdfGroupingToMatchResult(grouping, sourceFile = 'pdf', pdfJobId = null) {
  const groups = (grouping?.groups || []).map((g, wi) => ({
    workbook_index: wi,
    file_name: g.name || `Group ${wi + 1}`,
    metadata: { ...EMPTY_GROUP_METADATA },
    concepts: [],
    classifications: {},
    matched_tables: (g.tables || []).map((t) => ({
      table: {
        ...t,
        _uid: t.id || t._uid || t.table_id,
        id: t.id || t._uid || t.table_id,
        source_file: sourceFile || t.source_file || 'pdf',
        source_type: t.source_type || 'pdf',
        sheet: t.sheet || t.title || t.table_id || 'data',
      },
      inventory_item: null,
      confidence: 'pdf',
    })),
  }))
  const unmatched_tables = (grouping?.unmatched_tables || grouping?.unmatched || []).map((t) => ({
    table: {
      ...t,
      _uid: t.id || t._uid || t.table_id,
      id: t.id || t._uid || t.table_id,
      source_file: sourceFile || t.source_file || 'pdf',
      source_type: t.source_type || 'pdf',
      sheet: t.sheet || t.title || t.table_id || 'data',
    },
    confidence: 'none',
  }))
  return {
    groups,
    unmatched_tables,
    unmatched_inventory: [],
    method: grouping?.method || null,
    pdf_job_id: pdfJobId || null,
  }
}

/** Catalogue matchResult → PDF PUT /api/pdf/jobs/.../grouping payload. */
export function matchResultToPdfSavePayload(matchResult) {
  return {
    groups: (matchResult?.groups || []).map((g) => ({
      name: g.file_name,
      table_pks: (g.matched_tables || []).map((mt) => mt.table.id || mt.table._uid),
    })),
  }
}

export function allTablesFromMatchResult(matchResult) {
  if (!matchResult) return []
  return (matchResult.groups || [])
    .flatMap((g) => (g.matched_tables || []).map((mt) => mt.table))
    .concat((matchResult.unmatched_tables || []).map((u) => u.table))
}

export function renameMatchGroup(matchResult, index, newName) {
  if (!matchResult) return matchResult
  return {
    ...matchResult,
    groups: matchResult.groups.map((g, i) => (i === index ? { ...g, file_name: newName } : g)),
  }
}

export function deleteMatchGroup(matchResult, index) {
  if (!matchResult) return matchResult
  const removed = matchResult.groups[index]
  const returned = (removed.matched_tables || []).map((mt) => ({
    table: mt.table,
    inventory_item: null,
    confidence: 'manual',
  }))
  return {
    ...matchResult,
    groups: matchResult.groups.filter((_, i) => i !== index),
    unmatched_tables: [...(matchResult.unmatched_tables || []), ...returned],
  }
}

export function moveMatchTable(matchResult, tableId, dest) {
  if (!matchResult) return matchResult
  let movedEntry = null
  const groups = matchResult.groups.map((g) => {
    const keep = []
    const take = []
    ;(g.matched_tables || []).forEach((mt) => {
      const id = mt.table.id || mt.table._uid
      ;(id === tableId ? take : keep).push(mt)
    })
    if (take.length > 0) movedEntry = take[0]
    return { ...g, matched_tables: keep }
  })
  let unmatched_tables = matchResult.unmatched_tables || []
  if (!movedEntry) {
    const idx = unmatched_tables.findIndex((u) => (u.table.id || u.table._uid) === tableId)
    if (idx === -1) return matchResult
    movedEntry = unmatched_tables[idx]
    unmatched_tables = unmatched_tables.filter((_, i) => i !== idx)
  } else {
    unmatched_tables = unmatched_tables.filter((u) => (u.table.id || u.table._uid) !== tableId)
  }
  const table = movedEntry.table
  if (dest === 'unmatched') {
    unmatched_tables = [...unmatched_tables, { table, confidence: 'none' }]
  } else {
    const copy = [...groups]
    if (dest < 0 || dest >= copy.length) return matchResult
    copy[dest] = {
      ...copy[dest],
      matched_tables: [
        ...(copy[dest].matched_tables || []),
        { table, inventory_item: null, confidence: 'manual' },
      ],
    }
    return { ...matchResult, groups: copy, unmatched_tables }
  }
  return { ...matchResult, groups, unmatched_tables }
}

export function finishEditingMatchGroups(matchResult) {
  if (!matchResult) return matchResult
  return {
    ...matchResult,
    groups: matchResult.groups.filter((g) => (g.matched_tables || []).length > 0),
  }
}

export function createMatchGroup(matchResult, name, tableIds) {
  if (!matchResult) return matchResult
  const idSet = new Set(tableIds)
  const pulled = []
  const groups = matchResult.groups
    .map((g) => {
      const keep = []
      ;(g.matched_tables || []).forEach((mt) => {
        const id = mt.table.id || mt.table._uid
        if (idSet.has(id)) pulled.push({ table: mt.table, inventory_item: null, confidence: 'manual' })
        else keep.push(mt)
      })
      return { ...g, matched_tables: keep }
    })
    .filter((g) => (g.matched_tables || []).length > 0)
  const unmatchedKeep = []
  ;(matchResult.unmatched_tables || []).forEach((u) => {
    const id = u.table.id || u.table._uid
    if (idSet.has(id)) pulled.push({ table: u.table, inventory_item: null, confidence: 'manual' })
    else unmatchedKeep.push(u)
  })
  groups.push({
    workbook_index: groups.length,
    file_name: name,
    metadata: { ...EMPTY_GROUP_METADATA },
    concepts: [],
    classifications: {},
    matched_tables: pulled,
  })
  return { ...matchResult, groups, unmatched_tables: unmatchedKeep }
}

export function startManualMatchGrouping(matchResult, allTables) {
  if (!matchResult) return matchResult
  return {
    ...matchResult,
    groups: [],
    unmatched_tables: (allTables || []).map((t) => ({ table: t, confidence: 'none' })),
  }
}

/**
 * Call /api/catalogue/fill-group-metadata and merge patches into matchResult.
 * Returns { matchResult, toast, ok }.
 */
export async function fillGroupMetadataForMatchResult(matchResult, {
  withAuthHeaders,
  withLlmKeyHeaders,
  getMetadataStandard,
}) {
  const res = await fetch(
    '/api/catalogue/fill-group-metadata',
    withAuthHeaders(withLlmKeyHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groups: matchResult.groups, standard: getMetadataStandard() }),
    })),
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Metadata autofill failed' }))
    const detail = typeof err.detail === 'string' ? err.detail : 'Metadata autofill failed'
    return {
      ok: false,
      toast: `${detail} — fill metadata in manually below.`,
      matchResult: {
        ...matchResult,
        llm_autofill_skipped_no_key: false,
        kyds_missing: false,
        autofill_errors: [{ group: 'all', error: detail }],
      },
    }
  }
  const data = await res.json()
  const autofillErrors = Array.isArray(data.autofill_errors) ? data.autofill_errors : []
  const metaPatches = Array.isArray(data.group_metadata) ? data.group_metadata : null
  let nextGroups = matchResult.groups
  if (metaPatches) {
    nextGroups = matchResult.groups.map((g, i) => {
      const patch = metaPatches.find((p) => p.index === i) || metaPatches[i]
      if (!patch) return g
      const next = { ...g }
      if (patch.file_name) next.file_name = patch.file_name
      if (patch.filled && patch.metadata) {
        next.metadata = { ...(g.metadata || {}), ...patch.metadata }
      }
      if (patch.concept_metadata && Object.keys(patch.concept_metadata).length) {
        next.concept_metadata = { ...(g.concept_metadata || {}), ...patch.concept_metadata }
      }
      if (patch.catalogue_metadata && Object.keys(patch.catalogue_metadata).length) {
        next.catalogue_metadata = { ...(g.catalogue_metadata || {}), ...patch.catalogue_metadata }
      }
      return next
    })
  } else if (Array.isArray(data.groups) && data.groups.length === matchResult.groups.length) {
    nextGroups = matchResult.groups.map((g, i) => ({
      ...g,
      file_name: data.groups[i]?.file_name || g.file_name,
      metadata: data.groups[i]?.metadata && Object.keys(data.groups[i].metadata).length
        ? { ...(g.metadata || {}), ...data.groups[i].metadata }
        : g.metadata,
    }))
  }
  const filledCount = Number(data.autofill_filled_count) || 0
  let toast = null
  if (data.kyds_missing) {
    toast = 'Fill in Know Your Dataset first so metadata can be auto-mapped — or fill fields manually on the next step.'
  } else if (data.llm_autofill_skipped_no_key) {
    toast = 'Add an LLM API key in Settings to auto-fill metadata, or fill fields manually on the next step.'
  } else if (autofillErrors.length > 0) {
    const sample = autofillErrors[0]?.group || autofillErrors[0]?.error || 'unknown'
    toast = filledCount > 0
      ? `Auto-filled ${filledCount} group${filledCount !== 1 ? 's' : ''}; ${autofillErrors.length} need manual entry (${sample}).`
      : autofillErrors.length === 1
        ? `Auto-fill failed for 1 group (${sample}). Fill that group in manually.`
        : `Auto-fill failed for ${autofillErrors.length} groups. Fill those groups in manually.`
  }
  return {
    ok: true,
    toast,
    matchResult: {
      ...matchResult,
      groups: nextGroups,
      llm_autofill_skipped_no_key: Boolean(data.llm_autofill_skipped_no_key),
      kyds_missing: Boolean(data.kyds_missing),
      autofill_errors: autofillErrors,
      autofill_filled_count: filledCount,
    },
  }
}
