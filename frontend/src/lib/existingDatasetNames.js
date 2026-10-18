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

function addName(set, name) {
  const s = String(name || '').trim()
  if (!s || looksLikeBatchSummaryLabel(s)) return
  set.add(s)
}

/** From PdfReview tables + optional job filename. */
export function namesFromReviewTables(tables, jobFilename) {
  const names = new Set()
  for (const t of tables || []) {
    addName(names, t?.filename || t?.source_filename)
  }
  // Only use job filename when we have no per-table names yet (single-file jobs).
  if (names.size === 0) addName(names, jobFilename)
  return [...names]
}

/** From catalogue matchResult groups + optional job filename. */
export function namesFromMatchResult(matchResult, jobFilename) {
  const names = new Set()
  for (const g of matchResult?.groups || []) {
    addName(names, g?.file_name)
    for (const mt of g.matched_tables || []) {
      addName(names, mt?.table?.filename || mt?.table?.source_filename)
    }
  }
  for (const u of matchResult?.unmatched_tables || []) {
    addName(names, u?.table?.filename || u?.table?.source_filename)
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
