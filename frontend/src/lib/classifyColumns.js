// Pure (no-React) helpers for Classify.jsx: collapsing/aliasing classification
// columns across metadata groups, code-row shape helpers, and the initial
// catalogue-placement taxonomy. Extracted verbatim from Classify.jsx so the
// component file holds only UI/state — no logic here changed.
import { STATISTICS_OPTIONS, getDatasetIdConfig } from './settingsConfig'

// The classified columns (name/concept/note + code list) come from the real
// metadata-excel classification sheets, fetched by Classify.jsx — see
// backend/catalogue/classifications.py::get_metadata_group_classifications and
// backend/metadata/metadata_excel.py::parse_classifications. Code and
// definition are editable (a steward may want to rename/annotate them);
// value is what was actually found in the source data, so it stays fixed.

export function delhiProductForTheme(theme) {
  return `Delhi ${theme}`
}

export function initialTaxonomy() {
  const theme = getDatasetIdConfig().statistics || STATISTICS_OPTIONS[0]
  return {
    sector: 'Demography',
    theme,
    product: delhiProductForTheme(theme),
  }
}

export function isOccupationColumn(name) {
  return /occupat/i.test(name || '')
}

export function rowMapped(row) {
  return Boolean(String(row?.code || '').trim()) && Boolean(String(row?.definition || '').trim())
}

export function cloneCodeRows(codes) {
  return (codes || []).map((row) => ({
    code: row.code ?? '',
    value: row.value ?? '',
    definition: row.definition ?? '',
  }))
}

export function codesFingerprint(codes) {
  return JSON.stringify(
    [...(codes || [])]
      .map((r) => String(r.value ?? r.code ?? '').trim().toLowerCase())
      .filter(Boolean)
      .sort()
  )
}

export function normalizeColumnName(name) {
  return String(name || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
}

export function pickCanonicalName(names) {
  return [...names].sort((a, b) => a.length - b.length || a.localeCompare(b))[0]
}

/** Union code lists by value; keep the first filled code/definition for each. */
export function mergeCodeLists(lists) {
  const byValue = new Map()
  for (const list of lists || []) {
    for (const row of list || []) {
      const key = String(row?.value ?? row?.code ?? '').trim().toLowerCase()
      if (!key) continue
      const prev = byValue.get(key)
      if (!prev) {
        byValue.set(key, {
          code: row.code ?? '',
          value: row.value ?? '',
          definition: row.definition ?? '',
        })
        continue
      }
      if (!String(prev.code || '').trim() && row.code) prev.code = row.code
      if (!String(prev.definition || '').trim() && row.definition) prev.definition = row.definition
    }
  }
  return [...byValue.values()]
}

export function aliasKey(a) {
  return `${a?._metadataId || ''}::${a?.name || ''}`
}

/**
 * Club classification columns for the chip list:
 *  1) same value set (even if names differ) → one chip, aliases for harmonise
 *  2) same column name across metadata groups → one chip (union values), extras in harmonise
 */
export function collapseEquivalentColumns(columns) {
  // Pass 1 — identical value fingerprints
  const byFp = new Map()
  ;(columns || []).forEach((c) => {
    const fp = codesFingerprint(c.codes)
    const key = isOccupationColumn(c.name)
      ? `occ:${fp || normalizeColumnName(c.name)}`
      : (fp ? `fp:${fp}` : `solo:${c._metadataId || ''}::${normalizeColumnName(c.name)}`)
    const list = byFp.get(key) || []
    list.push(c)
    byFp.set(key, list)
  })

  const fpCollapsed = [...byFp.values()].map((list) => {
    const names = list.map((c) => c.name)
    const occNames = names.filter(isOccupationColumn)
    const name = pickCanonicalName(occNames.length ? occNames : names)
    const primary = list.find((c) => c.name === name) || list[0]
    return {
      ...primary,
      name: primary.name,
      codes: mergeCodeLists(list.map((c) => c.codes)),
      aliases: list.map((c) => ({
        name: c.name,
        _metadataId: c._metadataId,
        _groupIndex: c._groupIndex,
      })),
    }
  })

  // Pass 2 — same normalized name across groups (even if value sets differ)
  const byName = new Map()
  fpCollapsed.forEach((c) => {
    const key = `${isOccupationColumn(c.name) ? 'occ' : 'col'}:${normalizeColumnName(c.name)}`
    const list = byName.get(key) || []
    list.push(c)
    byName.set(key, list)
  })

  return [...byName.values()].map((list) => {
    const primary = [...list].sort((a, b) => (b.codes?.length || 0) - (a.codes?.length || 0))[0]
    const aliases = []
    const seen = new Set()
    list.forEach((c) => {
      const parts = c.aliases?.length
        ? c.aliases
        : [{ name: c.name, _metadataId: c._metadataId, _groupIndex: c._groupIndex }]
      parts.forEach((a) => {
        const k = aliasKey(a)
        if (!a?.name || seen.has(k)) return
        seen.add(k)
        aliases.push(a)
      })
    })
    const aliasNames = [...new Set(aliases.map((a) => a.name).filter((n) => n !== primary.name))]
    return {
      ...primary,
      name: primary.name,
      codes: mergeCodeLists(list.map((c) => c.codes)),
      aliases,
      aliasNames,
    }
  })
}

export function relatedAliasCount(column) {
  const primaryKey = aliasKey({
    name: column.name,
    _metadataId: column._metadataId,
  })
  return (column.aliases || []).filter((a) => aliasKey(a) !== primaryKey).length
}

export function isPrimaryHarmoniseAlias(column, alias) {
  return (alias.name || column.name) === column.name
    && (alias._metadataId || null) === (column._metadataId || null)
}

export function flattenForHarmonise(columns) {
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
