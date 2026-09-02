import { useState } from 'react'
import { NMDS_TOPICS } from '../nmdsConcepts'

// The topic-pills + one-topic-at-a-time field box, factored out of
// NmdsConceptForm so it can also be shown inside a modal (per metadata
// group) without duplicating the field-rendering logic.
export default function NmdsConceptFields({ fields, onFieldChange, onSave }) {
  const [topicIndex, setTopicIndex] = useState(0)
  const topic = NMDS_TOPICS[topicIndex]
  const isLast = topicIndex === NMDS_TOPICS.length - 1
  const isFirst = topicIndex === 0

  const filledInTopic = topic.items.filter((r) => (fields[r.concept] || '').trim()).length

  const goNext = () => {
    if (isLast) onSave?.()
    else setTopicIndex((i) => Math.min(NMDS_TOPICS.length - 1, i + 1))
  }

  return (
    <>
      <div className="nmds-topic-pills">
        {NMDS_TOPICS.map((t, i) => {
          const filled = t.items.filter((r) => (fields[r.concept] || '').trim()).length
          return (
            <button
              key={t.item_no}
              type="button"
              className={`nmds-topic-pill${i === topicIndex ? ' nmds-topic-pill-active' : ''}${filled === t.items.length ? ' nmds-topic-pill-done' : ' nmds-topic-pill-unfilled'}`}
              onClick={() => setTopicIndex(i)}
            >
              <span className="nmds-topic-pill-num">{i + 1}</span>
              <span className="nmds-topic-pill-label">{t.title}</span>
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
          <button
            type="button"
            className="push-btn-secondary"
            onClick={() => setTopicIndex((i) => Math.max(0, i - 1))}
            disabled={isFirst}
          >
            ← Previous topic
          </button>
          <button
            type="button"
            className="push-btn"
            onClick={goNext}
          >
            {isLast ? 'Save' : 'Next topic →'}
          </button>
        </div>
      </div>
    </>
  )
}
