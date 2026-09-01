import { useState } from 'react'
import { NMDS_TOPICS } from '../nmdsConcepts'
import FileUpload from './FileUpload'

// Upload-or-fill-manually form for the NMDS concept metadata sheet
// (nmds_concept_meta_data — see backend/metadata_excel.py parse_concepts).
// One topic (section) shown at a time in its own box, with Next/Back to
// step through them instead of one long scroll of every concept.
export default function NmdsConceptForm({
  fields,
  onFieldChange,
  onFileSelected,
  file,
  parsing,
  parseError,
  fileMismatch,
  onBack,
  onSave,
  saving,
  saveDisabled,
}) {
  const [topicIndex, setTopicIndex] = useState(0)
  const topic = NMDS_TOPICS[topicIndex]
  const isLast = topicIndex === NMDS_TOPICS.length - 1
  const isFirst = topicIndex === 0

  const filledInTopic = topic.items.filter((r) => (fields[r.concept] || '').trim()).length

  const goNext = () => {
    if (isLast) onSave?.()
    else setTopicIndex((i) => Math.min(NMDS_TOPICS.length - 1, i + 1))
  }
  const goBack = () => {
    if (isFirst) onBack?.()
    else setTopicIndex((i) => Math.max(0, i - 1))
  }

  return (
    <div className="nmds-form">
      <div className="push-section">
        <div className="push-section-title">Upload NMDS concept metadata (optional)</div>
        <FileUpload
          onUpload={onFileSelected}
          label="Add NMDS concept metadata file"
          hint="XLSX or CSV — prefills the topics below"
          selectedName={file?.name}
          accept=".xlsx,.xls,.csv"
          extensionRegex={/\.(xlsx|xls|csv)$/i}
          compact
        />
        {file && (
          <div className="push-excel-row">
            {!parsing && !parseError && !fileMismatch && (
              <div className="push-file-name">{file.name} — fields filled in below</div>
            )}
            {parsing && <div className="push-file-status">Reading concept metadata from {file.name}…</div>}
            {parseError && (
              <div className="push-file-error">
                Couldn't auto-fill from {file.name}: {parseError}. You can still fill the fields in manually.
              </div>
            )}
            {!parsing && !parseError && fileMismatch && (
              <div className="push-file-warning">
                ⚠ Couldn't match {file.name} against the known NMDS concepts — double-check you've uploaded the
                right file. You can still fill the fields in manually below.
              </div>
            )}
          </div>
        )}
      </div>

      <div className="nmds-topic-pills">
        {NMDS_TOPICS.map((t, i) => {
          const filled = t.items.filter((r) => (fields[r.concept] || '').trim()).length
          return (
            <button
              key={t.item_no}
              type="button"
              className={`nmds-topic-pill${i === topicIndex ? ' nmds-topic-pill-active' : ''}${filled === t.items.length ? ' nmds-topic-pill-done' : ''}`}
              onClick={() => setTopicIndex(i)}
            >
              <span className="nmds-topic-pill-num">{i + 1}</span>
              {t.title}
            </button>
          )
        })}
      </div>

      <div className="nmds-topic-box">
        <div className="nmds-topic-box-head">
          <div className="nmds-topic-box-title">{topic.item_no}. {topic.title}</div>
          <div className="nmds-topic-box-progress">
            Topic {topicIndex + 1} of {NMDS_TOPICS.length} · {filledInTopic}/{topic.items.length} filled
          </div>
        </div>

        <div className="nmds-topic-fields">
          {topic.items.map((row) => (
            <label className="meta-long-field nmds-field" key={row.item_no}>
              <span className="meta-long-label">{row.item_no} {row.concept}</span>
              <textarea
                className="meta-long-input"
                rows={3}
                value={fields[row.concept] || ''}
                placeholder={`Details for ${row.concept}`}
                onChange={(e) => onFieldChange(row.concept, e.target.value)}
              />
            </label>
          ))}
        </div>

        <div className="nmds-topic-box-nav">
          <button type="button" className="push-btn-secondary" onClick={goBack} disabled={saving}>
            {isFirst ? '← Back to metadata' : '← Previous topic'}
          </button>
          <button type="button" className="push-btn" onClick={goNext} disabled={saving || (isLast && saveDisabled)}>
            {isLast ? (saving ? 'Pushing…' : 'Save & continue to classification →') : 'Next topic →'}
          </button>
        </div>
      </div>
    </div>
  )
}
