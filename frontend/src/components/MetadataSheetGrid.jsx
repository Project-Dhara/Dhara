import { useEffect, useState } from 'react'

// Metadata entry, one card per table/metadata group. Field set mirrors what
// the backend's /api/catalogue/push and /api/catalogue/batch-push accept
// (see PushModal.jsx / BatchReview.jsx) — only `title` is actually required.
// Short categorical fields render as compact editable badges; focused fields
// expand to show wrapped content. Free-text fields get their own full-width row.
export const METADATA_COLUMNS = [
  { key: 'product', label: 'Product', type: 'badge', placeholder: 'e.g. Population_Data', readOnly: true },
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

function resizeBadgeInput(el, expanded) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = expanded ? `${el.scrollHeight}px` : ''
}

export default function MetadataSheetGrid({
  rows,
  columns = METADATA_COLUMNS,
  onChange,
  renderGroupFooter,
}) {
  const primaryCol = columns.find((c) => c.type === 'primary')
  const badgeCols = columns.filter((c) => c.type === 'badge' || c.type === 'date')
  const longCols = columns.filter((c) => c.type === 'long')

  const [activeIndex, setActiveIndex] = useState(0)
  useEffect(() => {
    if (activeIndex >= rows.length) setActiveIndex(Math.max(0, rows.length - 1))
  }, [rows.length, activeIndex])

  const activeRow = rows[activeIndex]

  return (
    <div className="meta-sheet">
      <div className="meta-groups-section">
        <div className="meta-groups-heading-row">
          <h3 className="meta-groups-heading">Available Groups</h3>
          <span className="meta-groups-count">
            {rows.length} metadata group{rows.length !== 1 ? 's' : ''} — select to review
          </span>
        </div>
        <div className="meta-carousel-nav">
        {rows.map((row, ri) => (
          <button
            key={row.id}
            type="button"
            className={`meta-carousel-tab${ri === activeIndex ? ' meta-carousel-tab-active' : ''}`}
            onClick={() => setActiveIndex(ri)}
            title={row.label}
          >
            <span className="meta-carousel-tab-num">{ri + 1}</span>
            <span className="meta-carousel-tab-label">{row.label}</span>
          </button>
        ))}
        </div>
      </div>

      {activeRow && (
        <div className="meta-carousel-viewport">
          <div className="meta-cards">
            {(() => {
              const row = activeRow
              const ri = activeIndex
              return (
            <div className="meta-card" key={row.id}>
            <div className="meta-card-head">
              <span className="meta-card-num">{ri + 1}</span>
              <span className="meta-card-label" title={row.label}>{row.label}</span>
              {row.manual && (
                <span className="meta-card-manual-tag" title="No metadata was auto-mapped for this group — fill in the fields below by hand">
                  Not auto-mapped — fill in manually
                </span>
              )}
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
                    className={`meta-badge${c.required && !(row.values[c.key] || '').trim() ? ' meta-field-missing' : ''}${c.readOnly ? ' meta-badge-readonly' : ''}`}
                  >
                    <span className="meta-badge-label">{c.label}{c.required && ' *'}</span>
                    {c.readOnly ? (
                      <span
                        className="meta-badge-input meta-badge-input-readonly"
                        title={row.values[c.key] || ''}
                        tabIndex={0}
                      >
                        {row.values[c.key] || c.placeholder}
                      </span>
                    ) : c.type === 'date' ? (
                      <input
                        className="meta-badge-input meta-badge-input-date"
                        type="date"
                        value={row.values[c.key] || ''}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                      />
                    ) : (
                      <textarea
                        className="meta-badge-input meta-badge-input-wrap"
                        rows={1}
                        value={row.values[c.key] || ''}
                        placeholder={c.placeholder}
                        onChange={(e) => onChange(row.id, c.key, e.target.value)}
                        onFocus={(e) => resizeBadgeInput(e.target, true)}
                        onBlur={(e) => resizeBadgeInput(e.target, false)}
                        onInput={(e) => {
                          if (document.activeElement === e.target) resizeBadgeInput(e.target, true)
                        }}
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

            {renderGroupFooter && (
              <div className="meta-card-group-footer">
                {renderGroupFooter(row, ri)}
              </div>
            )}
          </div>
              )
            })()}
          </div>
        </div>
      )}
    </div>
  )
}
