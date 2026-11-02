/** Parent levels for an NCO suggestion. Empty when the match has no code. */
export function ncoHierarchyLines(match) {
  if (!match?.code) return []
  const assigned = String(match.level || '').toLowerCase()
  const levels = [
    ['division', 'Division', match.division_code, match.division_title],
    ['subdivision', 'Subdivision', match.subdivision_code, match.subdivision_title],
    ['family', 'Family', match.family_code, match.family_title],
  ]
  return levels.flatMap(([level, label, code, title]) => {
    const codeText = code != null && String(code).trim() ? String(code).trim() : ''
    const titleText = title != null && String(title).trim() ? String(title).trim() : ''
    if (!codeText && !titleText) return []
    if (level === assigned && codeText === String(match.code).trim()) return []
    return [`${label} ${[codeText, titleText].filter(Boolean).join(' · ')}`]
  })
}

export default function NcoHierarchy({ match }) {
  const lines = ncoHierarchyLines(match)
  if (!lines.length) return null
  return (
    <div className="mt-1 space-y-0.5 text-[11px] leading-snug text-ink-soft">
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  )
}
