import { ArrowDown, ArrowUp, Minus } from 'lucide-react'
import { isGarbled } from './garbled'

/** Nearest ancestor that actually scrolls (AppShell main pane), else the document. */
export function getScrollParent(el) {
  let node = el?.parentElement
  while (node && node !== document.documentElement) {
    const { overflowY } = getComputedStyle(node)
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') {
      return node
    }
    node = node.parentElement
  }
  return document.scrollingElement || document.documentElement
}


export function isDocumentScroller(el) {
  return !el
    || el === document.documentElement
    || el === document.body
    || el === document.scrollingElement
}


export const CLASSIFICATION_LABELS = {
  domain: 'Domain', subject: 'Subject', entity: 'Entity', table_type: 'Table type',
  geography: 'Geography', time_period: 'Time period', frequency: 'Frequency', unit: 'Unit',
}


/** Canonical review-reason chips shown in the filter bar. Backend may still
 *  emit finer codes (column_alignment_mismatch, uncertain_semantic_role); those
 *  are folded into these labels so overlapping filters aren't duplicated. */
export const REASON_LABELS = {
  garbled_extracted_value: 'Garbled/corrupted value',
  conflicting_extraction: 'Conflicting extraction',
  uncertain_extraction: 'Uncertain extraction',
  ambiguous_column: 'Ambiguous column',
  uncertain_concept: 'Uncertain concept',
  uncertain_title: 'Uncertain title',
}


/** Map backend-specific reasons onto the chip the reviewer actually filters by. */
export const REASON_ALIASES = {
  column_alignment_mismatch: 'uncertain_extraction',
  uncertain_semantic_role: 'ambiguous_column',
  // Prior frontend-only id; keep filtering old sessions.
  missing_title: 'uncertain_title',
}


/**
 * Turn stored extraction-uncertainty notes into steward-facing copy.
 * Keeps already-plain notes unchanged; rewrites legacy internal codes from
 * older jobs (column_alignment_mismatch, pymupdf_*, ADDED guard, …).
 */
export function formatUncertainCellNote(note) {
  const raw = String(note ?? '').trim()
  if (!raw) return raw

  // Compact summaries from the alignment guard — pass through.
  if (/^Blank value columns?\b/i.test(raw)) return raw
  if (/^Too (few|many) columns\b/i.test(raw)) return raw
  if (/^Rebuilt from the PDF ruled grid\b/i.test(raw)) return raw
  if (/^Column\s+\d+\s+\("/i.test(raw) && /:\s*(blank|expected numbers|up\/down|serial)/i.test(raw)) {
    return raw
  }

  const alignmentCol = raw.match(
    /^column_alignment_mismatch:\s*col\s+(-?\d+)\s+'([^']*)'\s*--\s*(.+)$/i,
  )
  if (alignmentCol) {
    const colIndex = Number(alignmentCol[1])
    const name = alignmentCol[2]
    const detail = humanizeAlignmentDetail(alignmentCol[3], colIndex, name)
    if (colIndex < 0 || name === '(table structure)') return detail
    return `Column ${colIndex + 1} ("${name}"): ${detail}`
  }

  // Verbose prior humanized forms — extract the column name for grouping.
  const blankCol = extractBlankColumnName(raw)
  if (blankCol) return `Blank value column: ${blankCol}.`

  const priorNonNumericSimple = raw.match(
    /^Column\s+"([^"]+)":\s+looks like a value column but most cells are not numbers/i,
  )
  if (priorNonNumericSimple) {
    return `Column "${priorNonNumericSimple[1]}": expected numbers.`
  }

  const addedGuardReplace = raw.match(
    /^ADDED guard:\s*replaced LLM rows\/columns with\s+(\S+)\s+candidate after alignment mismatch\s*\(candidate numeric fill\s+(\S+)\s+vs\s+LLM\s+(\S+)\)\.?$/i,
  )
  if (addedGuardReplace) {
    return (
      `Rebuilt from the PDF ruled grid after column layout mismatch `
      + `(grid fill ${addedGuardReplace[2].trim()}; earlier reconstruction ${addedGuardReplace[3].trim()}). `
      + 'Verify values sit under the right headers.'
    )
  }

  if (/^ADDED guard:\s*reconstructed table failed column-alignment checks/i.test(raw)) {
    const count = raw.match(/\((\d+)\s*column/i)
    const n = count ? count[1] : null
    return n
      ? `Column layout check found ${n} issue(s).`
      : 'Column layout check found issues.'
  }

  if (/^Column headers and values did not line up/i.test(raw)) {
    return raw.replace(
      /^Column headers and values did not line up[\s\S]*?\(([^)]+)\)\.?$/i,
      (_, fill) => `Rebuilt from the PDF ruled grid after column layout mismatch (${fill}). Verify values sit under the right headers.`,
    )
  }

  const conflict = raw.match(
    /^row\s+(\d+),\s*col\s+'([^']+)':\s*(\S+)=(.+?)\s+vs\s+(\S+)=(.+?)(?:,\s*kept\s+(\S+))?$/i,
  )
  if (conflict) {
    const kept = conflict[7]
      ? ` Kept ${humanizeExtractionMethod(conflict[7])}.`
      : ''
    return (
      `Row ${conflict[1]}, "${conflict[2]}": `
      + `${humanizeExtractionMethod(conflict[3])}=${conflict[4].trim()} vs `
      + `${humanizeExtractionMethod(conflict[5])}=${conflict[6].trim()}.`
      + kept
    )
  }

  if (/^ADDED:\s*removed Direction\/Trend column/i.test(raw)) {
    return 'Removed a Direction/Trend column that was not in the source PDF.'
  }

  return raw
}


/** Pull the column name out of verbose blank-column uncertainty notes. */
function extractBlankColumnName(note) {
  const raw = String(note ?? '').trim()
  let m = raw.match(/^Column\s+"([^"]+)":\s+every cell in this value column is blank/i)
  if (m) return m[1]
  m = raw.match(/^Column\s+"([^"]+)":\s+looks like a value column but is mostly empty/i)
  if (m) return m[1]
  m = raw.match(/^Column\s+\d+\s+of\s+\d+\s+\("([^"]+)"\):\s+every cell is blank/i)
  if (m) return m[1]
  m = raw.match(/^column_alignment_mismatch:\s*col\s+-?\d+\s+'([^']*)'\s*--\s*measure column mostly empty/i)
  if (m) return m[1]
  m = raw.match(/^Blank value column:\s*(.+)\.?$/i)
  if (m) return m[1].replace(/\.$/, '')
  return null
}


function looksLikeSexAgeHeader(name) {
  const n = String(name || '')
  if (!/\b(male|female)\b/i.test(n)) return false
  return /(<\s*\d|\d+\s*[-–—]\s*\d|>=?\s*\d|not\s*stated|total|age)/i.test(n)
}


function listColumnNames(names, limit = 6) {
  const clean = names.map((n) => String(n || '').trim() || 'unnamed')
  if (clean.length <= limit) return clean.join(', ')
  return `${clean.slice(0, limit - 1).join(', ')}, +${clean.length - (limit - 1)} more`
}


/**
 * Collapse repeated blank-column uncertainty notes into one short line.
 * Keeps unrelated notes intact. Safe for already-stored jobs.
 */
export function summarizeUncertainCellNotes(notes) {
  const list = Array.isArray(notes) ? notes.map((n) => String(n ?? '').trim()).filter(Boolean) : []
  if (!list.length) return []

  const blankNames = []
  const rest = []
  for (const note of list) {
    const name = extractBlankColumnName(note)
    if (name) blankNames.push(name)
    else rest.push(formatUncertainCellNote(note))
  }

  const out = []
  if (blankNames.length === 1) {
    let line = `Blank value column: ${blankNames[0]}.`
    if (looksLikeSexAgeHeader(blankNames[0])) {
      line += ' Sex looks mixed into age headers — use M/F as row labels instead.'
    }
    out.push(line)
  } else if (blankNames.length > 1) {
    let line = `Blank value columns (${blankNames.length}): ${listColumnNames(blankNames)}.`
    if (blankNames.some(looksLikeSexAgeHeader)) {
      line += ' Sex looks mixed into age headers — use M/F as row labels instead.'
    }
    out.push(line)
  }

  // Dedupe remaining notes while preserving order.
  const seen = new Set(out)
  for (const note of rest) {
    if (seen.has(note)) continue
    seen.add(note)
    out.push(note)
  }
  return out
}


function humanizeAlignmentDetail(detail, colIndex, name) {
  const d = String(detail || '').trim()
  const empty = d.match(/^measure column mostly empty\s*\(([^)]+)\)/i)
  if (empty) {
    return `blank (${empty[1]})`
  }
  if (/^measure column values are mostly non-numeric/i.test(d)) {
    return 'expected numbers'
  }
  if (/^measure column contains Direction up\/down tokens/i.test(d)) {
    return 'up/down markers instead of numbers'
  }
  if (/^States\/geo column filled with Direction up\/down values/i.test(d)) {
    return 'up/down markers instead of place names'
  }
  if (/^S\.No\.\/serial values look glued to the next column/i.test(d)) {
    return 'serial stuck to next field'
  }
  if (/^looks like a value column but is mostly empty/i.test(d)) {
    const blank = d.match(/\(([^)]+)\)/)
    return `blank${blank ? ` (${blank[1]})` : ''}`
  }

  const tooMany = d.match(
    /^reconstructed\s+(\d+)\s+columns\s+vs\s+(\d+)\s+in the ruled-border candidate/i,
  )
  if (tooMany || (colIndex < 0 && /title\/caption line misread as headers/i.test(d))) {
    const a = tooMany?.[1]
    const b = tooMany?.[2]
    if (a && b) return `Too many columns (${a} vs ~${b} in the PDF grid).`
  }

  const tooFew = d.match(
    /^reconstructed only\s+(\d+)\s+columns\s+vs\s+(\d+)\s+in the ruled-border candidate/i,
  )
  if (tooFew || (colIndex < 0 && /multi-level header collapsed/i.test(d))) {
    const a = tooFew?.[1]
    const b = tooFew?.[2]
    if (a && b) return `Too few columns (${a} vs ~${b} in the PDF grid).`
    return 'Too few columns vs the PDF grid.'
  }

  return d
}


function humanizeExtractionMethod(method) {
  const m = String(method || '').toLowerCase()
  if (m.includes('lines_strict')) return 'ruled-border'
  if (m.includes('lines')) return 'ruled-border (loose)'
  if (m.includes('text')) return 'text-alignment'
  if (m.includes('llm')) return 'AI reconstruction'
  return method || 'extraction'
}


export function canonicalizeReviewReason(reason) {
  if (!reason) return reason
  return REASON_ALIASES[reason] || reason
}


export const ROLE_OPTIONS = ['identifier', 'dimension', 'measure', 'attribute', 'unknown']


/** Top-level filter chips. Reason-specific chips (uncertain extraction, etc.)
 *  stay nested under "Review needed" and only appear once that filter is active. */
export const PRIMARY_FILTERS = ['needs_review', 'no_review']

export const REASON_FILTER_IDS = Object.keys(REASON_LABELS)


export function looksLikeNumber(value) {
  if (value === null || value === undefined) return true
  const s = String(value).trim().replace(/,/g, '').replace(/%\s*$/, '')
  if (!s) return true
  // Integers, decimals, and percentages (e.g. 36, 0.3, 30.5, 12%)
  return /^-?\d+(\.\d+)?$/.test(s)
}


export const NUMERIC_DATA_TYPES = new Set([
  'integer', 'int', 'decimal', 'float', 'double', 'number', 'numeric',
  'percentage', 'percent', 'pct',
])


/** Numeric columns (integers, decimals, percentages) stay read-only. */
export function isNumericColumn(col, colIndex, rows) {
  const dt = String(col?.data_type || '').toLowerCase().trim()
  if (NUMERIC_DATA_TYPES.has(dt)) return true
  // Also lock when the column name clearly marks a share/rate metric.
  const name = String(col?.name || '').toLowerCase()
  if (/(^|[^a-z])(percent|percentage|pct|%)([^a-z]|$)/i.test(name)) return true
  if (dt && dt !== 'unknown') return false
  const vals = (rows || [])
    .map((row) => row?.[colIndex])
    .filter((v) => v !== null && v !== undefined && String(v).trim() !== '')
  if (vals.length === 0) return false
  return vals.every(looksLikeNumber)
}


export function tableHasGarbledCells(table) {
  return (table.rows || []).some((row) => (row || []).some((v) => isGarbled(v)))
}


export function collectReviewReasons(table) {
  const reasons = new Set()
  const add = (reason) => {
    const canonical = canonicalizeReviewReason(reason)
    if (canonical) reasons.add(canonical)
  }
  if (table.human_review_reason) add(table.human_review_reason)
  for (const field of Object.values(table.classification || {})) {
    if (field?.human_review_reason) add(field.human_review_reason)
  }
  for (const col of table.columns || []) {
    if (col.human_review_reason) add(col.human_review_reason)
  }
  if (tableHasGarbledCells(table)) add('garbled_extracted_value')
  if ((table.uncertain_cells || []).length > 0 && !reasons.has('conflicting_extraction')) {
    add('uncertain_extraction')
  }
  // Missing / unusable title — same signal as "No title — review" in the list.
  if (tableHasMissingTitle(table)) add('uncertain_title')
  return reasons
}


// DEV-ONLY: semantic_status is 'classified' for any table that went through
// the LLM validation step (single-page, batched, or alignment-guard
// fallback), and 'not_classified' for the deterministic no-LLM path. Lets a
// developer isolate AI-classified output to spot-check reconstruction /
// classification quality without wading through the auto-accepted tables.
export function isAiClassified(table) {
  return table.semantic_status === 'classified'
}


export function matchesStatusFilter(table, filter, reviewed) {
  if (filter === 'all') return true
  if (filter === 'reviewed') return reviewed
  if (filter === 'needs_review') {
    if (reviewed) return false
    return (
      Boolean(table.human_review_needed)
      || tableHasMissingTitle(table)
      || collectReviewReasons(table).size > 0
      || tableHasGarbledCells(table)
    )
  }
  if (filter === 'no_review') {
    if (tableHasMissingTitle(table)) return false
    return !table.human_review_needed && !tableHasGarbledCells(table) && collectReviewReasons(table).size === 0
  }
  if (filter === 'dev_ai_classified') return isAiClassified(table)
  if (filter === 'dev_auto_extracted') return !isAiClassified(table)
  return collectReviewReasons(table).has(canonicalizeReviewReason(filter))
}


/** Collapse punctuation/whitespace so "TABLE 10(I)" and "table 10 i" compare equally. */
function normalizeSearchText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
}


function editDistance(a, b) {
  if (a === b) return 0
  if (!a) return b.length
  if (!b) return a.length
  // Keep DP bounded for title tokens; long tokens fall back to substring checks.
  if (a.length > 32 || b.length > 32) return Math.max(a.length, b.length)
  const prev = new Array(b.length + 1)
  const cur = new Array(b.length + 1)
  for (let j = 0; j <= b.length; j += 1) prev[j] = j
  for (let i = 1; i <= a.length; i += 1) {
    cur[0] = i
    const ca = a.charCodeAt(i - 1)
    for (let j = 1; j <= b.length; j += 1) {
      const cost = ca === b.charCodeAt(j - 1) ? 0 : 1
      cur[j] = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
    }
    for (let j = 0; j <= b.length; j += 1) prev[j] = cur[j]
  }
  return prev[b.length]
}


function isCharSubsequence(needle, haystack) {
  let i = 0
  for (let j = 0; j < haystack.length && i < needle.length; j += 1) {
    if (needle[i] === haystack[j]) i += 1
  }
  return i === needle.length
}


function fuzzyTokenMatches(token, haystack, words) {
  if (!token) return true
  if (haystack.includes(token)) return true

  // Digits are exact only — "15" must not fuzzy-match "10" / "12" / "5".
  if (/^\d+$/.test(token)) {
    return words.includes(token)
  }

  const maxDist = token.length <= 4 ? 1 : token.length <= 8 ? 2 : 3
  for (const word of words) {
    if (!word) continue
    // Require a real prefix/stem — avoid "p15".startsWith("p") via short word flips.
    if (word.startsWith(token)) return true
    if (token.startsWith(word) && word.length >= 3) return true
    if (word.includes(token)) return true
    // "p15".includes("1") / .includes("5") was matching pages 1 and 5.
    if (token.length >= 3 && word.length >= 3 && token.includes(word)) return true
    // Typo / rough match: "relgion" ≈ "religion", "birts" ≈ "births".
    if (token.length >= 3 && word.length >= 3 && isCharSubsequence(token, word)) return true
    if (/^\d+$/.test(word)) continue
    if (Math.abs(word.length - token.length) <= maxDist && editDistance(word, token) <= maxDist) {
      return true
    }
  }
  return false
}


/**
 * Fuzzy / rough match against table title and page number.
 * Empty query matches everything so existing filter behaviour is unchanged.
 * Page queries ("15", "p15", "page 15") match that page exactly — no fuzzy spillover.
 */
export function matchesTableSearch(table, query) {
  const raw = String(query || '').trim()
  if (!raw) return true

  const page = String(table?.page ?? '').trim()

  // Page-number queries are exact: "15", "p15", "p.15", "page 15".
  const pageOnly = raw.match(/^(?:p(?:age)?\.?\s*)?(\d+)$/i)
  if (pageOnly) {
    return Boolean(page) && page === pageOnly[1]
  }

  const title = displayTitle(table) || String(table?.title || '').trim()
  const banner = String(table?.banner_table_id || '').trim()
  const tableId = String(table?.table_id ?? '').trim()
  const haystack = normalizeSearchText([title, banner, page ? `page ${page}` : '', tableId].join(' '))
  const words = haystack ? haystack.split(' ') : []

  const tokens = normalizeSearchText(raw).split(' ').filter(Boolean)
  if (tokens.length === 0) return true
  return tokens.every((token) => fuzzyTokenMatches(token, haystack, words))
}


/** Normalize column names for cross-page merge eligibility. */
export function tableHeaderKey(table) {
  return (table?.columns || [])
    .map((c) => String(c?.name ?? c ?? '').trim().toLowerCase().replace(/\s+/g, ' '))
    .join('|')
}


/** Ensure every row has exactly `ncols` cells (LLM often drops Direction). */
export function padRowsToColumns(rows, ncols) {
  return (rows || []).map((row) => {
    const next = Array.isArray(row) ? row.slice(0, ncols) : []
    while (next.length < ncols) next.push(null)
    return next
  })
}


export function cloneColumns(columns) {
  return (columns || []).map((c) => ({
    ...c,
    header_path: Array.isArray(c?.header_path) ? [...c.header_path] : c?.header_path,
  }))
}


export function columnDraftFromTable(columns) {
  return (columns || []).map((c) => ({
    name: c.name || '',
    header_group: c.header_group || '',
    header_path: Array.isArray(c.header_path) ? [...c.header_path] : null,
    role: c.role || 'unknown',
    concept: c.concept || '',
    description: c.description || '',
    data_type: c.data_type || 'unknown',
    human_review_needed: Boolean(c.human_review_needed),
    human_review_reason: c.human_review_reason || null,
    input_type: c.input_type,
    input_options: c.input_options,
    unit: c.unit,
    category: c.category,
  }))
}


export function applyNameToColumnMeta(col, name) {
  const next = { ...col, name }
  const path = Array.isArray(col.header_path) && col.header_path.length
    ? [...col.header_path]
    : (col.header_group ? [col.header_group, name] : [name])
  if (path.length) path[path.length - 1] = name
  next.header_path = path
  if (path.length >= 2) next.header_group = path[path.length - 2]
  else if (!col.header_group) next.header_group = null
  return next
}


export function reshapeRows(rows, mapIndex) {
  return (rows || []).map((row) => {
    const src = Array.isArray(row) ? row : []
    return mapIndex.map((old) => (old == null ? null : (src[old] ?? null)))
  })
}


/** Clamp editor pane zoom (50%–250%). */
export function clampEditorZoom(z) {
  return Math.min(2.5, Math.max(0.5, Math.round(Number(z) * 100) / 100))
}


/**
 * Trackpad pinch (ctrl+wheel on Chrome/macOS) or ⌘/Ctrl+scroll → zoom.
 * Must use a non-passive listener so preventDefault can block browser page zoom.
 */
export function bindPaneWheelZoom(el, setZoom) {
  if (!el) return () => {}
  const onWheel = (e) => {
    if (!(e.ctrlKey || e.metaKey)) return
    e.preventDefault()
    e.stopPropagation()
    const factor = Math.exp(-e.deltaY * 0.008)
    setZoom((z) => clampEditorZoom((Number(z) || 1) * factor))
  }
  el.addEventListener('wheel', onWheel, { passive: false })
  return () => el.removeEventListener('wheel', onWheel)
}


export function columnHeaderGroup(col) {
  const g = col?.header_group
  if (g == null) return null
  const s = String(g).trim()
  if (!s) return null
  // Full-width table captions must never render as a parent header row.
  if (/^table\s*[:.\-–—]?\s*\S/i.test(s)) return null
  if (/^(?:statement|annex(?:ure)?)\s*[:.\-–—]?\s*\S/i.test(s)) return null
  return s
}


/** Full top→leaf header path for a column (supports 1..N levels). */
export function columnHeaderPath(col) {
  const raw = col?.header_path
  if (Array.isArray(raw) && raw.length > 0) {
    const path = raw.map((p) => String(p ?? '').trim()).filter(Boolean)
    if (path.length) {
      // Drop banner-like roots that shouldn't appear as header rows.
      const filtered = path.filter((p, idx) => {
        if (idx === path.length - 1) return true
        if (/^table\s*[:.\-–—]?\s*\S/i.test(p)) return false
        if (/^(?:statement|annex(?:ure)?)\s*[:.\-–—]?\s*\S/i.test(p)) return false
        return true
      })
      return filtered.length ? filtered : [String(col?.name || '')]
    }
  }
  const name = String(col?.name || '')
  const group = columnHeaderGroup(col)
  if (group && group.toLowerCase() !== name.toLowerCase()) return [group, name]
  return name ? [name] : ['']
}


/**
 * Place a column path into a depth-tall grid.
 * Shorter paths get extra rowspan on the top label (stub columns span all levels).
 */
export function placeHeaderPath(path, depth) {
  const cells = Array.from({ length: depth }, () => null)
  if (!path.length) return cells
  const extra = Math.max(0, depth - path.length)
  let row = 0
  path.forEach((label, i) => {
    const rowSpan = i === 0 ? 1 + extra : 1
    const prefix = path.slice(0, i + 1).join('\0')
    cells[row] = { label, rowSpan, prefix }
    for (let k = 1; k < rowSpan; k += 1) cells[row + k] = { covered: true }
    row += rowSpan
  })
  return cells
}


/**
 * Build N header rows with colspan/rowspan for arbitrary header depth.
 * Returns { depth, rows } where rows[r] is an array of visible segments.
 */
export function buildMultiLevelHeaderRows(columns) {
  const cols = columns || []
  const paths = cols.map((c) => columnHeaderPath(c))
  const depth = Math.max(1, ...paths.map((p) => p.length))
  const grid = paths.map((p) => placeHeaderPath(p, depth))

  const rows = []
  for (let r = 0; r < depth; r += 1) {
    const segs = []
    let c = 0
    while (c < cols.length) {
      const cell = grid[c][r]
      if (!cell || cell.covered) {
        c += 1
        continue
      }
      let colSpan = 1
      while (
        c + colSpan < cols.length
        && grid[c + colSpan][r]
        && !grid[c + colSpan][r].covered
        && grid[c + colSpan][r].prefix === cell.prefix
        && grid[c + colSpan][r].rowSpan === cell.rowSpan
      ) {
        colSpan += 1
      }
      segs.push({
        key: `h-${r}-${c}`,
        label: cell.label,
        colSpan,
        rowSpan: cell.rowSpan,
        start: c,
        isLeaf: r + cell.rowSpan === depth,
      })
      c += colSpan
    }
    rows.push(segs)
  }
  return { depth, rows }
}


/**
 * Editor header layout: same rowspan rules as the review preview.
 * Ungrouped columns span the full header height — no empty "Group…" slots.
 * Parent group cells appear only when a column actually has group labels
 * (or the user adds/assigns a group via the toolbar).
 */
export function buildEditorHeaderRows(columns) {
  const cols = columns || []
  const paths = cols.map((c) => columnHeaderPath(c))
  const depth = Math.max(1, ...paths.map((p) => p.length))
  const grid = paths.map((p) => placeHeaderPath(p, depth))

  const rows = []
  for (let r = 0; r < depth; r += 1) {
    const segs = []
    let c = 0
    while (c < cols.length) {
      const cell = grid[c][r]
      if (!cell || cell.covered) {
        c += 1
        continue
      }
      let colSpan = 1
      while (
        c + colSpan < cols.length
        && grid[c + colSpan][r]
        && !grid[c + colSpan][r].covered
        && grid[c + colSpan][r].prefix === cell.prefix
        && grid[c + colSpan][r].rowSpan === cell.rowSpan
      ) {
        colSpan += 1
      }
      segs.push({
        key: `eh-${r}-${c}`,
        label: cell.label,
        colSpan,
        rowSpan: cell.rowSpan,
        start: c,
        isLeaf: r + cell.rowSpan === depth,
        empty: false,
      })
      c += colSpan
    }
    rows.push(segs)
  }
  return { depth, rows }
}


export function isEmptyMergeCell(value) {
  if (value === null || value === undefined) return true
  const s = String(value).trim()
  if (!s) return true
  return s === '—' || s === '–' || s === '-' || s === '−' || s === '‒'
}


export function isNumericishCell(value) {
  if (value === null || value === undefined) return false
  const s = String(value).replace(/,/g, '').replace(/%/g, '').replace(/\*/g, '').trim()
  if (!s || isEmptyMergeCell(s)) return false
  return /^-?\d+(\.\d+)?$/.test(s)
}


/** Label / stub columns where PDF rowspan is common (not measure columns). */
export function isBodyLabelColumn(colIdx, columns, rows) {
  const name = String(columns?.[colIdx]?.name || '').toLowerCase()
  if (
    /^(sl\.?\s*no\.?|s\.?\s*no\.?|sno|item|name|indicator|state|district|disease|particulars|description|category|sector|occupation|education|sex)$/i.test(
      name,
    )
    || name.includes('name of')
    || name.includes('local body')
    || name.includes('disease')
    || name.includes('district')
    || name === 'sex'
  ) {
    return true
  }
  const vals = (rows || [])
    .map((row) => (Array.isArray(row) ? row[colIdx] : null))
    .filter((v) => !isEmptyMergeCell(v))
  if (vals.length < 1) return false
  const numeric = vals.filter((v) => isNumericishCell(v)).length
  // Mostly non-numeric values → treat as a label column eligible for rowspan.
  return numeric <= vals.length * 0.35
}


export function isSummaryLabel(value) {
  if (isEmptyMergeCell(value)) return false
  const s = String(value).trim().toLowerCase()
  // Exact ALL/TOTAL, or "Total (…)" / "ALL (…)" — not "All ages" / "All India".
  if (/^(all|total|overall|aggregate)$/.test(s)) return true
  if (/^grand\s*total$/.test(s)) return true
  if (/^(all|total)\s*[\(:]/.test(s)) return true
  return false
}


/**
 * Reconstruct body cell merges from empty cells under label columns and
 * sparse measure columns (pymupdf leaves rowspan/colspan continuations empty).
 *
 * Returns spans[r][c] = { rowSpan, colSpan } or null when covered by a prior merge.
 *
 * Vertical spans stop when:
 *  - a label column to the left introduces a new value, or
 *  - a sibling group label changes (e.g. Item "Others" → "ALL"), or
 *  - a table-footer summary row (last row with TOTAL/ALL in Sex etc.) would
 *    otherwise absorb blank Sl. No. / District cells from the group above.
 * Measure-column rowspans (e.g. shared population) only stop at the next
 * non-empty cell — they intentionally span different stub labels.
 */
export function buildBodyCellSpans(rows, columns) {
  const nrows = (rows || []).length
  const ncols = (columns || []).length
  const spans = Array.from({ length: nrows }, () => Array.from({ length: ncols }, () => ({ rowSpan: 1, colSpan: 1 })))
  if (!nrows || !ncols) return spans

  const labelCols = []
  for (let c = 0; c < ncols; c += 1) {
    if (isBodyLabelColumn(c, columns, rows)) labelCols.push(c)
  }
  if (!labelCols.length) return spans

  const labelSet = new Set(labelCols)

  // Sparse identity cols (Sl. No. / Name with rowspan empties).
  const sparseIdentityCols = []
  // Dense high-cardinality labels (Item lists) — only break on summary transitions.
  const denseSummaryBreakCols = []
  for (const c of labelCols) {
    const colName = String(columns?.[c]?.name || '').toLowerCase()
    if (/^(sex|gender)$/.test(colName)) continue

    let empty = 0
    const nonEmpty = []
    for (let r = 0; r < nrows; r += 1) {
      const v = rows[r]?.[c]
      if (isEmptyMergeCell(v)) empty += 1
      else nonEmpty.push(String(v).trim().toLowerCase())
    }
    if (empty >= 1 && empty >= nrows * 0.12 && empty < nrows) {
      sparseIdentityCols.push(c)
      continue
    }
    if (nonEmpty.length >= 2) {
      const unique = new Set(nonEmpty)
      if (unique.size >= Math.max(3, Math.ceil(nonEmpty.length * 0.75))) {
        denseSummaryBreakCols.push(c)
      }
    }
  }

  const covered = Array.from({ length: nrows }, () => Array(ncols).fill(false))

  const leftBoundaryAt = (rowIdx, colIdx) => {
    for (const lc of labelCols) {
      if (lc >= colIdx) break
      if (!isEmptyMergeCell(rows[rowIdx]?.[lc])) return true
    }
    return false
  }

  const rowHasSummaryLabel = (rowIdx) => (
    labelCols.some((lc) => isSummaryLabel(rows[rowIdx]?.[lc]))
  )

  const siblingLabelBreakAt = (startRow, rowIdx, colIdx) => {
    // Sparse siblings: any new value ends the span (Name under DCB → Total block).
    for (const lc of sparseIdentityCols) {
      if (lc === colIdx) continue
      const startV = rows[startRow]?.[lc]
      const v = rows[rowIdx]?.[lc]
      if (isEmptyMergeCell(v)) continue
      if (isEmptyMergeCell(startV)) return true
      if (String(startV).trim().toLowerCase() !== String(v).trim().toLowerCase()) return true
    }

    // Dense Item-like cols: only break on summary transitions (Others → ALL),
    // not on normal list changes (South → South West) that would kill Sl. No. rowspan.
    for (const lc of denseSummaryBreakCols) {
      if (lc === colIdx) continue
      const startV = rows[startRow]?.[lc]
      const v = rows[rowIdx]?.[lc]
      if (isEmptyMergeCell(v)) continue
      if (isEmptyMergeCell(startV)) {
        if (isSummaryLabel(v)) return true
        continue
      }
      if (String(startV).trim().toLowerCase() !== String(v).trim().toLowerCase()) {
        if (isSummaryLabel(v) || isSummaryLabel(startV)) return true
      }
    }

    // Footer / grand-total row: blank identity cells must stay unmerged.
    if (rowHasSummaryLabel(rowIdx) && rowIdx === nrows - 1) return true

    return false
  }

  const measureCols = []
  for (let c = 0; c < ncols; c += 1) {
    if (!labelSet.has(c)) measureCols.push(c)
  }

  const isSectionBannerRow = (rowIdx) => {
    if (!measureCols.length) return false
    const measuresEmpty = measureCols.every((c) => isEmptyMergeCell(rows[rowIdx]?.[c]))
    if (!measuresEmpty) return false
    return labelCols.some((c) => {
      const v = rows[rowIdx]?.[c]
      return !isEmptyMergeCell(v) && !isNumericishCell(v)
    })
  }

  // Left → right so horizontal merges (Total across Sl.No + Name) claim cells first.
  for (const c of labelCols) {
    let r = 0
    while (r < nrows) {
      if (covered[r][c]) {
        r += 1
        continue
      }
      if (isEmptyMergeCell(rows[r]?.[c])) {
        spans[r][c] = { rowSpan: 1, colSpan: 1 }
        r += 1
        continue
      }
      let rowSpan = 1
      while (r + rowSpan < nrows && isEmptyMergeCell(rows[r + rowSpan]?.[c])) {
        if (leftBoundaryAt(r + rowSpan, c)) break
        if (siblingLabelBreakAt(r, r + rowSpan, c)) break
        rowSpan += 1
      }
      let colSpan = 1
      // Extend across adjacent empty label cells for the same vertical run (e.g. Total).
      while (labelSet.has(c + colSpan)) {
        let ok = true
        for (let dr = 0; dr < rowSpan; dr += 1) {
          const rr = r + dr
          const cc = c + colSpan
          if (covered[rr][cc] || !isEmptyMergeCell(rows[rr]?.[cc])) {
            ok = false
            break
          }
          if (leftBoundaryAt(rr, c)) {
            ok = false
            break
          }
        }
        if (!ok) break
        colSpan += 1
      }
      // Section banners (Delhi / All India / District wise…) colspan into empty measure cols.
      if (rowSpan === 1 && isSectionBannerRow(r)) {
        while (c + colSpan < ncols && measureCols.includes(c + colSpan)) {
          if (covered[r][c + colSpan] || !isEmptyMergeCell(rows[r]?.[c + colSpan])) break
          colSpan += 1
        }
      }
      spans[r][c] = { rowSpan, colSpan }
      for (let dr = 0; dr < rowSpan; dr += 1) {
        for (let dc = 0; dc < colSpan; dc += 1) {
          if (dr === 0 && dc === 0) continue
          covered[r + dr][c + dc] = true
          spans[r + dr][c + dc] = null
        }
      }
      r += rowSpan
    }
  }

  // Sparse measure columns (e.g. population merged across several local bodies).
  // Do not apply left-label boundary breaks — the merge intentionally spans
  // different stub values (MCD / NDMC / DCB under one population cell).
  for (let c = 0; c < ncols; c += 1) {
    if (labelSet.has(c)) continue
    let empty = 0
    for (let r = 0; r < nrows; r += 1) {
      if (isEmptyMergeCell(rows[r]?.[c])) empty += 1
    }
    if (!(empty >= 1 && empty >= nrows * 0.12 && empty < nrows)) continue

    let r = 0
    while (r < nrows) {
      if (covered[r][c]) {
        r += 1
        continue
      }
      if (isEmptyMergeCell(rows[r]?.[c])) {
        spans[r][c] = { rowSpan: 1, colSpan: 1 }
        r += 1
        continue
      }
      let rowSpan = 1
      while (r + rowSpan < nrows && isEmptyMergeCell(rows[r + rowSpan]?.[c])) {
        rowSpan += 1
      }
      if (rowSpan === 1) {
        r += 1
        continue
      }
      spans[r][c] = { rowSpan, colSpan: 1 }
      for (let dr = 1; dr < rowSpan; dr += 1) {
        covered[r + dr][c] = true
        spans[r + dr][c] = null
      }
      r += rowSpan
    }
  }

  for (let r = 0; r < nrows; r += 1) {
    for (let c = 0; c < ncols; c += 1) {
      if (covered[r][c]) spans[r][c] = null
    }
  }
  return spans
}


/** Collapse fake-bold / doubled-glyph PDF titles (Maaiinn → Main). */
export function collapseDoubledPdfGlyphs(text) {
  const s = String(text || '')
  if (s.length < 4) return s
  const letters = [...s].filter((c) => /[A-Za-z]/.test(c))
  if (letters.length < 6) return s
  let inPair = 0
  for (let i = 0; i < letters.length; ) {
    if (i + 1 < letters.length && letters[i].toLowerCase() === letters[i + 1].toLowerCase()) {
      inPair += 2
      i += 2
    } else {
      i += 1
    }
  }
  if (inPair / letters.length < 0.8) return s
  let out = ''
  for (let i = 0; i < s.length; ) {
    const c = s[i]
    if (
      /[A-Za-z]/.test(c)
      && i + 1 < s.length
      && /[A-Za-z]/.test(s[i + 1])
      && c.toLowerCase() === s[i + 1].toLowerCase()
    ) {
      out += c
      i += 2
    } else {
      out += c
      i += 1
    }
  }
  return out
}


export function stripCaptionLabelPrefix(title) {
  const raw = collapseDoubledPdfGlyphs(String(title || '').trim().replace(/\s+/g, ' '))
  if (!raw) return raw
  // "Statement 4.6: Distribution…" / "Table 2.1 — Foo"
  const withSep = raw.replace(
    /^(?:TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX|FIG(?:URE)?|CHART|BOX)\b\s*(?:[\w]+(?:[./\-][\w]+)*)?\s*[:\-–—]\s*/i,
    '',
  ).replace(/^[:\-–—\s]+/, '').trim()
  if (withSep && withSep.length >= 4 && withSep.toLowerCase() !== raw.toLowerCase()) {
    return withSep
  }
  // "Statement 4.6 Distribution…" (space after number, no colon)
  const withSpace = raw.replace(
    /^(?:TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX|FIG(?:URE)?|CHART|BOX)\b\s+[\w]+(?:[./\-][\w]+)*\s+/i,
    '',
  ).trim()
  if (withSpace && withSpace.length >= 4 && withSpace.toLowerCase() !== raw.toLowerCase()) {
    return withSpace
  }
  return raw
}


export function isUsableTableTitle(title, columns) {
  const t = stripCaptionLabelPrefix(String(title || '').trim())
  if (!t || t.length < 4) return false
  // Truncated PDF wrap leftovers like "Direc-"
  if (/[–—-]$/.test(t)) return false
  // Joined header rows — not a real table title
  if (t.includes(' · ') || (t.match(/\|/g) || []).length >= 2) return false
  const colNames = (columns || [])
    .map((c) => String(c?.name ?? c ?? '').trim().toLowerCase())
    .filter(Boolean)
  const low = t.toLowerCase()
  const stem = low.replace(/[–—-]+$/g, '')
  for (const c of colNames) {
    if (low === c) return false
    if (stem.length <= 16 && (c.startsWith(stem) || c.includes(stem))) return false
  }
  return true
}


function isBareTableIdLabel(value) {
  const s = String(value || '').trim()
  if (!s) return false
  // "TABLE -8", "TABLE: B-15", "TABLE (ii)", "TABLE - (I)" — id only.
  return /^(?:table|tab\.?)\b\s*[:.\-–—]?\s*(?:[a-z0-9][\w.\-–—/]*(?:\s*\([^)]{0,48}\))?|\([^)]{1,48}\))\s*$/i.test(s)
}


export function displayTitle(table) {
  const t = stripCaptionLabelPrefix((table?.title || '').trim())
  const banner = String(table?.banner_table_id || '').trim()
  // Cleared / missing descriptive title → no display title (never fall back to
  // banner_table_id alone; that left "TABLE -…" stuck after the user wiped the field).
  if (!t || isBareTableIdLabel(t) || !isUsableTableTitle(t, table?.columns)) {
    return null
  }
  // When the id lived on its own line (TABLE -8) and the descriptive caption
  // is the stored title, show both for stewards.
  if (
    banner &&
    !t.toLowerCase().includes(banner.toLowerCase()) &&
    /^table\b/i.test(banner) &&
    t.length >= 12
  ) {
    return `${banner} — ${t}`
  }
  return t
}


/** True when the steward sees "No title — review" (no usable descriptive title). */
export function tableHasMissingTitle(table) {
  return !displayTitle(table)
}


export function titleForEdit(table) {
  // Edit the stored descriptive title only — never the composed display string
  // that prefixes banner_table_id (TABLE -8). Saving that back would bake the
  // id into table.title on every blur/open.
  let t = stripCaptionLabelPrefix((table?.title || '').trim())
  const banner = String(table?.banner_table_id || '').trim()
  if (banner && t) {
    // Undo a previously saved "TABLE -8 — descriptive…" composition.
    const escaped = banner.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    t = t.replace(new RegExp(`^${escaped}\\s*[—–\\-]\\s*`, 'i'), '').trim()
  }
  if (!t || isBareTableIdLabel(t)) return ''
  if (isUsableTableTitle(t, table?.columns)) return t
  return t
}


/** Direction / Trend columns store up|down|same; show arrow symbols in the UI. */
export const DIRECTION_SYMBOLS = {
  up: { symbol: '↑', label: 'Up', Icon: ArrowUp, className: 'text-[#2f7a3e]' },
  down: { symbol: '↓', label: 'Down', Icon: ArrowDown, className: 'text-[#c45c4a]' },
  same: { symbol: '–', label: 'Same', Icon: Minus, className: 'text-[#8a8478]' },
}


export function isDirectionLikeColumn(col) {
  const blob = `${col?.name || ''} ${col?.concept || ''}`.toLowerCase()
  return ['direction', 'trend', 'change'].some((k) => blob.includes(k))
}


export function directionDisplay(value) {
  if (value == null || value === '') return null
  const key = String(value).trim().toLowerCase()
  if (DIRECTION_SYMBOLS[key]) return DIRECTION_SYMBOLS[key]
  // Already a symbol from an older extract
  if (key === '↑' || key === '▲' || key === '⬆') return DIRECTION_SYMBOLS.up
  if (key === '↓' || key === '▼' || key === '⬇') return DIRECTION_SYMBOLS.down
  if (key === '–' || key === '—' || key === '−' || key === '‒') return DIRECTION_SYMBOLS.same
  return null
}


export function directionSelectOptions(inputOptions) {
  const base = Array.isArray(inputOptions) && inputOptions.length > 0
    ? inputOptions.map((o) => String(o))
    : ['up', 'down', 'same']
  const seen = new Set()
  const opts = []
  for (const raw of [...base, 'up', 'down', 'same']) {
    const key = raw.trim().toLowerCase()
    if (!DIRECTION_SYMBOLS[key] || seen.has(key)) continue
    seen.add(key)
    opts.push(key)
  }
  return opts
}


export function spansFromExplicitMerges(nrows, ncols, merges) {
  const spans = Array.from({ length: nrows }, () => Array.from({ length: ncols }, () => ({ rowSpan: 1, colSpan: 1 })))
  const covered = Array.from({ length: nrows }, () => Array.from({ length: ncols }, () => false))
  for (const m of merges || []) {
    const r = m.r
    const c = m.c
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    if (r < 0 || c < 0 || r >= nrows || c >= ncols) continue
    if (covered[r][c]) continue
    spans[r][c] = { rowSpan: rs, colSpan: cs }
    for (let dr = 0; dr < rs; dr += 1) {
      for (let dc = 0; dc < cs; dc += 1) {
        const rr = r + dr
        const cc = c + dc
        if (rr >= nrows || cc >= ncols) continue
        if (dr || dc) {
          covered[rr][cc] = true
          spans[rr][cc] = null
        }
      }
    }
  }
  return spans
}


/** Collect multi-cell spans as explicit merge records. */
export function mergesFromSpans(spans) {
  const out = []
  for (let r = 0; r < (spans || []).length; r += 1) {
    for (let c = 0; c < (spans[r] || []).length; c += 1) {
      const s = spans[r][c]
      if (!s) continue
      if ((s.rowSpan || 1) > 1 || (s.colSpan || 1) > 1) {
        out.push({ r, c, rowSpan: s.rowSpan || 1, colSpan: s.colSpan || 1 })
      }
    }
  }
  return out
}


/**
 * Explicit merges (non-empty list, or locked empty after Unmerge) win.
 * Otherwise auto-infer rowspans from empty cells under labels / measures.
 */
export function resolveEditorBodySpans(rows, columns, explicitMerges, mergesExplicit = false) {
  const nrows = (rows || []).length
  const ncols = (columns || []).length
  if (mergesExplicit || (explicitMerges || []).length > 0) {
    return spansFromExplicitMerges(nrows, ncols, explicitMerges || [])
  }
  return buildBodyCellSpans(rows, columns)
}


export function findMergeCovering(merges, r, c) {
  return (merges || []).find((m) => {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    return r >= m.r && r < m.r + rs && c >= m.c && c < m.c + cs
  }) || null
}


/** Find the origin cell of a visible body span covering (r, c). */
export function findBodySpanOrigin(spans, r, c) {
  const direct = spans?.[r]?.[c]
  if (direct) return { r, c, span: direct }
  for (let rr = 0; rr <= r; rr += 1) {
    for (let cc = 0; cc <= c; cc += 1) {
      const s = spans?.[rr]?.[cc]
      if (!s) continue
      const rs = Math.max(1, s.rowSpan || 1)
      const cs = Math.max(1, s.colSpan || 1)
      if (r >= rr && r < rr + rs && c >= cc && c < cc + cs) {
        return { r: rr, c: cc, span: s }
      }
    }
  }
  return null
}


/**
 * Materialize auto-inferred spans if needed, then drop the merge covering (r, c).
 * Always returns an explicit merge list so Unmerge sticks (even when empty).
 */
export function unmergeAt(rows, columns, cellMerges, mergesExplicit, r, c) {
  const spans = resolveEditorBodySpans(rows, columns, cellMerges, mergesExplicit)
  const origin = findBodySpanOrigin(spans, r, c)
  if (!origin || ((origin.span.rowSpan || 1) <= 1 && (origin.span.colSpan || 1) <= 1)) {
    return null
  }
  let base = mergesExplicit || (cellMerges || []).length > 0
    ? (cellMerges || []).map((m) => ({ ...m }))
    : mergesFromSpans(spans)
  base = base.filter((m) => {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    const coversOrigin = origin.r >= m.r && origin.r < m.r + rs && origin.c >= m.c && origin.c < m.c + cs
    return !coversOrigin
  })
  return {
    cellMerges: base,
    mergesExplicit: true,
    flash: {
      axis: 'cells',
      from: {
        r0: origin.r,
        r1: origin.r + Math.max(1, origin.span.rowSpan || 1) - 1,
        c0: origin.c,
        c1: origin.c + Math.max(1, origin.span.colSpan || 1) - 1,
      },
      to: { r0: origin.r, r1: origin.r, c0: origin.c, c1: origin.c },
    },
  }
}


/** Snapshot whatever merges are currently visible (explicit or auto-inferred). */
export function materializeCellMerges(rows, columns, cellMerges, mergesExplicit) {
  if (mergesExplicit || (cellMerges || []).length > 0) {
    return (cellMerges || []).map((m) => ({
      r: m.r,
      c: m.c,
      rowSpan: Math.max(1, Number(m.rowSpan) || 1),
      colSpan: Math.max(1, Number(m.colSpan) || 1),
    }))
  }
  return mergesFromSpans(resolveEditorBodySpans(rows, columns, cellMerges, false))
}


/**
 * Before deleting row `idx`, copy merge-origin values into the next row of the
 * span so rowspan content (e.g. Sl. No. "A") is not discarded with the origin.
 */
export function promoteMergeValuesBeforeRowDelete(rows, merges, idx) {
  const next = (rows || []).map((row) => (Array.isArray(row) ? [...row] : row))
  for (const m of merges || []) {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    if (m.r !== idx || rs <= 1) continue
    const dest = idx + 1
    if (!next[dest]) continue
    for (let dc = 0; dc < cs; dc += 1) {
      const c = m.c + dc
      if (c < 0 || c >= next[dest].length) continue
      if (isEmptyMergeCell(next[dest][c])) {
        next[dest][c] = next[idx]?.[c] ?? null
      }
    }
  }
  return next
}


/**
 * Remap explicit merges after removing row `idx`.
 * Deleting a merge origin keeps the remaining span (value already promoted).
 */
export function adjustMergesAfterRowDelete(merges, idx) {
  return (merges || [])
    .map((m) => {
      const rs = Math.max(1, Number(m.rowSpan) || 1)
      const cs = Math.max(1, Number(m.colSpan) || 1)
      const end = m.r + rs - 1
      if (end < idx) return { r: m.r, c: m.c, rowSpan: rs, colSpan: cs }
      if (m.r > idx) return { r: m.r - 1, c: m.c, rowSpan: rs, colSpan: cs }
      if (m.r === idx) {
        if (rs <= 1) return null
        // After deleting the origin row, the rest of the block starts at `idx`.
        return { r: idx, c: m.c, rowSpan: rs - 1, colSpan: cs }
      }
      // idx is inside the span below the origin.
      return { r: m.r, c: m.c, rowSpan: rs - 1, colSpan: cs }
    })
    .filter(Boolean)
    .filter((m) => m.rowSpan > 1 || m.colSpan > 1)
}


export function adjustMergesAfterRowInsert(merges, idx) {
  return (merges || []).map((m) => {
    const rs = Math.max(1, Number(m.rowSpan) || 1)
    const cs = Math.max(1, Number(m.colSpan) || 1)
    if (m.r >= idx) return { r: m.r + 1, c: m.c, rowSpan: rs, colSpan: cs }
    const end = m.r + rs - 1
    if (idx > m.r && idx <= end) return { r: m.r, c: m.c, rowSpan: rs + 1, colSpan: cs }
    return { r: m.r, c: m.c, rowSpan: rs, colSpan: cs }
  }).filter((m) => m.rowSpan > 1 || m.colSpan > 1)
}


export function selectionRect(sel) {
  if (!sel) return null
  return {
    r0: Math.min(sel.r0, sel.r1),
    r1: Math.max(sel.r0, sel.r1),
    c0: Math.min(sel.c0, sel.c1),
    c1: Math.max(sel.c0, sel.c1),
  }
}


export function setHeaderPathLevel(columns, start, colSpan, levelIdx, label) {
  const text = String(label || '').trim()
  const depth = Math.max(1, ...(columns || []).map((c) => columnHeaderPath(c).length))
  return (columns || []).map((col, i) => {
    if (i < start || i >= start + colSpan) return col
    const current = columnHeaderPath(col)
    const leaf = current[current.length - 1] || col.name || `Column ${i + 1}`
    // Flat pad so short paths expose editable ancestor slots above the leaf.
    const padded = Array.from({ length: depth }, () => '')
    const offset = Math.max(0, depth - current.length)
    current.forEach((p, j) => { padded[offset + j] = p })
    padded[Math.min(levelIdx, depth - 1)] = text
    // Drop leading empty ancestors; keep leaf.
    let startIdx = 0
    while (startIdx < depth - 1 && !String(padded[startIdx] || '').trim()) startIdx += 1
    const path = padded.slice(startIdx).map((p, idx, arr) => {
      const s = String(p || '').trim()
      if (s) return s
      return idx === arr.length - 1 ? leaf : `Level ${idx + 1}`
    })
    const name = path[path.length - 1] || leaf
    const header_group = path.length >= 2 ? path[path.length - 2] : null
    return {
      ...col,
      name,
      header_group,
      header_path: path,
    }
  })
}


/** Unique immediate parent group labels across columns (for the group picker). */
export function listExistingHeaderGroups(columns) {
  const seen = new Set()
  const out = []
  for (const col of columns || []) {
    const path = columnHeaderPath(col)
    if (path.length < 2) continue
    const g = path[path.length - 2]
    if (!g || seen.has(g)) continue
    seen.add(g)
    out.push(g)
  }
  return out
}


/** Parent path (everything above the leaf) for a column. */
export function columnParentPath(col) {
  const path = columnHeaderPath(col)
  return path.length >= 2 ? path.slice(0, -1) : []
}


/** Apply a parent path (above the leaf) to one column. */
export function withParentPath(col, parents) {
  const leaf = col?.name || columnHeaderPath(col).slice(-1)[0] || 'Column'
  const clean = (parents || []).map((p) => String(p || '').trim()).filter(Boolean)
  if (!clean.length) {
    return { ...col, name: leaf, header_group: null, header_path: [leaf] }
  }
  return {
    ...col,
    name: leaf,
    header_group: clean[clean.length - 1],
    header_path: [...clean, leaf],
  }
}


/**
 * Reorder a contiguous column range [from, from+count) so it lands before
 * insertAt in the original index space (insertAt may equal n to append).
 */
export function reorderColumnRange(columns, rows, cellMerges, from, count, insertAt) {
  const n = (columns || []).length
  if (count < 1 || from < 0 || from + count > n) {
    return { columns, rows, cellMerges }
  }
  let dest = Math.max(0, Math.min(insertAt, n))
  if (dest >= from && dest <= from + count) {
    return { columns, rows, cellMerges }
  }
  const cols = [...columns]
  const moved = cols.splice(from, count)
  if (dest > from) dest -= count
  cols.splice(dest, 0, ...moved)

  const order = []
  for (let i = 0; i < n; i += 1) {
    if (i >= from && i < from + count) continue
    order.push(i)
  }
  const movedIdx = Array.from({ length: count }, (_, i) => from + i)
  order.splice(dest, 0, ...movedIdx)
  const remap = (c) => {
    const idx = order.indexOf(c)
    return idx >= 0 ? idx : c
  }
  const nextMerges = (cellMerges || []).map((m) => ({
    ...m,
    c: remap(m.c),
  }))
  return {
    columns: cols,
    rows: reshapeRows(rows, order),
    cellMerges: nextMerges,
  }
}


/** Move contiguous rows [from, from+count) so they land before insertAt. */
export function reorderRowRange(rows, cellMerges, from, count, insertAt) {
  const n = (rows || []).length
  if (count < 1 || from < 0 || from + count > n) {
    return { rows, cellMerges }
  }
  let dest = Math.max(0, Math.min(insertAt, n))
  if (dest >= from && dest <= from + count) {
    return { rows, cellMerges }
  }
  const nextRows = [...rows]
  const moved = nextRows.splice(from, count)
  if (dest > from) dest -= count
  nextRows.splice(dest, 0, ...moved)

  const order = []
  for (let i = 0; i < n; i += 1) {
    if (i >= from && i < from + count) continue
    order.push(i)
  }
  const movedIdx = Array.from({ length: count }, (_, i) => from + i)
  order.splice(dest, 0, ...movedIdx)
  const remap = (r) => {
    const idx = order.indexOf(r)
    return idx >= 0 ? idx : r
  }
  const nextMerges = (cellMerges || []).map((m) => ({
    ...m,
    r: remap(m.r),
  }))
  return { rows: nextRows, cellMerges: nextMerges }
}


/** Snapshot of editable table structure for one-step undo/redo. */
export function cloneEditorStructure(draft) {
  return {
    columns: cloneColumns(draft.columns || []),
    rows: (draft.rows || []).map((row) => (Array.isArray(row) ? [...row] : row)),
    cellMerges: Array.isArray(draft.cellMerges)
      ? draft.cellMerges.map((m) => ({ ...m }))
      : [],
    mergesExplicit: Boolean(draft.mergesExplicit),
  }
}


export function invertActionFlash(flash) {
  if (!flash) return null
  return {
    ...flash,
    from: flash.to ? { ...flash.to } : null,
    to: flash.from ? { ...flash.from } : null,
  }
}


/** Where a moved block lands after reorderColumnRange / reorderRowRange. */
export function movedBlockFlash(axis, from, count, insertAt) {
  if (count < 1) return null
  const end = from + count - 1
  if (insertAt >= from && insertAt <= from + count) return null
  let newStart = from
  if (insertAt <= from) newStart = insertAt
  else if (insertAt > end) newStart = insertAt - count
  else return null
  return {
    axis,
    from: { start: from, end },
    to: { start: newStart, end: newStart + count - 1 },
  }
}


export function flashCovers(flashPart, index) {
  if (!flashPart) return false
  return index >= flashPart.start && index <= flashPart.end
}


export const TABLE_EDIT_CHANNEL = 'dhara-pdf-table-edit'


export function notifyTableEdited(jobId, tableId, edits) {
  try {
    const bc = new BroadcastChannel(TABLE_EDIT_CHANNEL)
    bc.postMessage({ type: 'table-edited', jobId, tableId, edits })
    bc.close()
  } catch {
    /* BroadcastChannel unavailable */
  }
  try {
    localStorage.setItem(
      TABLE_EDIT_CHANNEL,
      JSON.stringify({ jobId, tableId, edits, t: Date.now() }),
    )
  } catch {
    /* ignore */
  }
}


/** Close the editor tab, or fall back to the review page if the browser blocks window.close(). */
export function closeEditorWindow(jobId) {
  if (typeof window === 'undefined') return
  const reviewUrl = `/console/review/${encodeURIComponent(jobId || '')}`
  try {
    window.close()
  } catch {
    /* ignore */
  }
  // noopener / user-opened tabs often ignore window.close(); leave the editor.
  window.setTimeout(() => {
    if (!window.closed) {
      window.location.assign(reviewUrl)
    }
  }, 150)
}

