// Mirrors backend's _GARBLED_RE in backend/sda_india_pdf_extraction.py --
// keep these in sync if that pattern ever changes.
//   - U+E000-U+F8FF: Private Use Area glyphs (icon-font characters with no
//     real Unicode mapping, render as tofu/boxes -- e.g. trend-arrow icons)
//   - U+FFFD: Unicode replacement character
//   - A Latin-1-supplement letter (U+00C0-U+00FF) immediately followed by a
//     UTF-8 continuation-byte-range character (U+0080-U+00BF): classic
//     mojibake from double-decoded UTF-8 (e.g. "Ã©" for "é")
const GARBLED_RE = /[-�]|[À-ÿ][-¿]/

export function isGarbled(value: unknown) {
  if (value === null || value === undefined) return false
  return GARBLED_RE.test(String(value))
}
