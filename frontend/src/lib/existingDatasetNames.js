/**
 * Build a deduped list of dataset filenames for "Already extracted" UI.
 * Skips batch summary labels like "3 files" or "a.xlsx; +b.pdf".
 */

function looksLikeBatchSummaryLabel(name) {
  const s = String(name || '').trim()
  if (!s) return true
  if (/^\d+\s+files?$/i.test(s)) return true
  // Append-mode job labels: "a.xlsx; +b.pdf" or "a.xlsx; +b.pdf, +c.pdf"
  if (/;\s*\+/.test(s)) return true
  if (s.includes(';') && /\+\S/.test(s)) return true
  return false
}

/** True for real upload names (report.pdf); false for PDF group display titles. */
function looksLikeDatasetFilename(name) {
  const s = String(name || '').trim()
  if (!s || looksLikeBatchSummaryLabel(s)) return false
  if (/^(pdf|xlsx|xls|csv|sql|data)$/i.test(s)) return false
  return /\.(pdf|xlsx|xls|csv)$/i.test(s)
}

function addName(set, name) {
  const s = String(name || '').trim()
  if (!s || looksLikeBatchSummaryLabel(s)) return
  set.add(s)
}

function addTableFilename(set, table) {
  const candidates = [
    table?.filename,
    table?.source_filename,
    table?.source_file,
  ]
  for (const c of candidates) {
    if (looksLikeDatasetFilename(c)) {
      addName(set, c)
      return
    }
  }
}

/** From PdfReview tables + optional job filename. */
export function namesFromReviewTables(tables, jobFilename) {
  const names = new Set()
  for (const t of tables || []) {
    addTableFilename(names, t)
  }
  // Only use job filename when we have no per-table names yet (single-file jobs).
  if (names.size === 0) addName(names, jobFilename)
  return [...names]
}

/** From catalogue matchResult groups + optional job filename.
 *
 * PDF groups store the group *title* in `file_name` (not the upload name).
 * Prefer per-table source filenames; only use `file_name` when it looks like
 * a real dataset file (Excel/SQL workbooks).
 */
export function namesFromMatchResult(matchResult, jobFilename) {
  const names = new Set()
  for (const g of matchResult?.groups || []) {
    for (const mt of g.matched_tables || []) {
      addTableFilename(names, mt?.table)
    }
    if (looksLikeDatasetFilename(g?.file_name)) addName(names, g.file_name)
  }
  for (const u of matchResult?.unmatched_tables || []) {
    addTableFilename(names, u?.table)
  }
  if (names.size === 0) addName(names, jobFilename)
  return [...names]
}

/** Prefer explicit list; otherwise fall back to preview dataset chips. */
export function namesFromPreviewDatasets(previewDatasets) {
  const names = new Set()
  for (const n of previewDatasets || []) addName(names, n)
  return [...names]
}
