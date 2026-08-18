// Metadata entry, one card per table/metadata group. Field set mirrors what
// the backend's /api/catalogue/push and /api/catalogue/batch-push accept
// (see PushModal.jsx / BatchReview.jsx) — only `title` is actually required.
// Short categorical fields render as compact editable badges that wrap;
// free-text fields get their own full-width row. Everything wraps
// vertically — nothing scrolls horizontally.
export const METADATA_COLUMNS = [
  { key: 'title', label: 'Title', type: 'primary', required: true, placeholder: 'e.g. Population Statistics 2024' },
  { key: 'product', label: 'Product', type: 'badge', placeholder: 'e.g. Population_Data' },
  { key: 'category', label: 'Category', type: 'badge', placeholder: 'e.g. Demographics' },
  { key: 'geography', label: 'Geography', type: 'badge', placeholder: 'e.g. India' },
  { key: 'frequency', label: 'Frequency', type: 'badge', placeholder: 'e.g. Annually' },
  { key: 'time_period', label: 'Time period', type: 'badge', placeholder: 'e.g. 2001–2021' },
  { key: 'data_source', label: 'Source', type: 'badge', placeholder: 'e.g. Census of India' },
  { key: 'last_updated', label: 'Last updated', type: 'date' },
  { key: 'future_release', label: 'Future release', type: 'date' },
  { key: 'description', label: 'Description', type: 'long', placeholder: 'What this dataset covers' },
  { key: 'key_statistics', label: 'Key statistics', type: 'long', placeholder: 'Headline measures worth calling out' },
  { key: 'remarks', label: 'Remarks', type: 'long', placeholder: 'Any additional notes or caveats' },
]

export default function MetadataSheetGrid({
  rows,
  columns = METADATA_COLUMNS,
  onChange,
  enteredByLabel = 'you',
  note = 'Fields marked * are required.',
}) {
  const requiredCols = columns.filter((c) => c.required)
  const totalRequired = Math.max(1, rows.length) * requiredCols.length
  const filledRequired = rows.reduce(
    (n, row) => n + requiredCols.filter((c) => (row.values[c.key] || '').trim()).length,
    0
  )
  const pct = totalRequired ? Math.round((filledRequired / totalRequired) * 100) : 0

  const primaryCol = columns.find((c) => c.type === 'primary')
  const badgeCols = columns.filter((c) => c.type === 'badge' || c.type === 'date')
  const longCols = columns.filter((c) => c.type === 'long')

  return (
    <div className="meta-sheet">
      <div className="meta-sheet-topbar">
        <span className="meta-sheet-entered-pill">Entered by {enteredByLabel}</span>
        <span className="meta-sheet-note">{note}</span>
        <div className="meta-sheet-progress">
          <div className="meta-sheet-progress-track">
            <div className="meta-sheet-progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="meta-sheet-progress-label">{filledRequired}/{totalRequired} required fields</span>
        </div>
      </div>

      <div className="meta-cards">
        {rows.map((row, ri) => (
          <div className="meta-card" key={row.id}>
            <div className="meta-card-head">
              <span className="meta-card-num">{ri + 1}</span>
              <span className="meta-card-label" title={row.label}>{row.label}</span>
            </div>

            {primaryCol && (
              <input
                className={`meta-primary-input${primaryCol.required && !(row.values[primaryCol.key] || '').trim() ? ' meta-field-missing' : ''}`}
                type="text"
                value={row.values[primaryCol.key] || ''}
                placeholder={`${primaryCol.placeholder}${primaryCol.required ? ' *' : ''}`}
                onChange={(e) => onChange(row.id, primaryCol.key, e.target.value)}
              />
            )}

            {badgeCols.length > 0 && (
              <div className="meta-badge-row">
                {badgeCols.map((c) => (
                  <label
                    key={c.key}
                    className={`meta-badge${c.required && !(row.values[c.key] || '').trim() ? ' meta-field-missing' : ''}`}
                  >
                    <span className="meta-badge-label">{c.label}{c.required && ' *'}</span>
                    {c.type === 'date' ? (
                      <input
                        className="meta-badge-input meta-badge-input-date"
                        type="date"
                        value={row.values[c.key] || ''}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                      />
                    ) : (
                      <input
                        className="meta-badge-input"
                        type="text"
                        value={row.values[c.key] || ''}
                        placeholder={c.placeholder}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                      />
                    )}
                  </label>
                ))}
              </div>
            )}

            {longCols.length > 0 && (
              <div className="meta-long-fields">
                {longCols.map((c) => (
                  <label key={c.key} className="meta-long-field">
                    <span className="meta-long-label">{c.label}</span>
                    <textarea
                      className="meta-long-input"
                      rows={2}
                      value={row.values[c.key] || ''}
                      placeholder={c.placeholder}
                      onChange={(e) => onChange(row.id, c.key, e.target.value)}
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
