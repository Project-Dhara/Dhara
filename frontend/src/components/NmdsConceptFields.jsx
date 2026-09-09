'use client'

import { useState } from 'react'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { NMDS_TOPICS } from '../lib/nmdsConcepts'
import Button from './ui/Button'

// The topic-pills + one-topic-at-a-time field box, factored out of
// NmdsConceptForm so it can also be shown inside a modal (per metadata
// group) without duplicating the field-rendering logic.
export default function NmdsConceptFields({
  fields,
  onFieldChange,
  onSave,
  topics = NMDS_TOPICS,
  placeholders = {},
}) {
  const [topicIndex, setTopicIndex] = useState(0)
  const safeIndex = Math.min(topicIndex, Math.max(0, topics.length - 1))
  const topic = topics[safeIndex]
  const isLast = safeIndex === topics.length - 1
  const isFirst = safeIndex === 0

  if (!topic) return null

  const filledInTopic = topic.items.filter((r) => (fields[r.concept] || '').trim()).length

  const goNext = () => {
    if (isLast) onSave?.()
    else setTopicIndex((i) => Math.min(topics.length - 1, i + 1))
  }

  return (
    <>
      <div className="grid grid-cols-4 gap-x-4 gap-y-3.5 max-[900px]:grid-cols-2 max-[560px]:grid-cols-1">
        {topics.map((t, i) => {
          const filled = t.items.filter((r) => (fields[r.concept] || '').trim()).length
          const active = i === safeIndex
          const done = filled === t.items.length
          const unfilled = !done
          return (
            <button
              key={t.item_no || t.title}
              type="button"
              className={`grid min-w-0 grid-cols-[18px_1fr] items-center gap-2 rounded-full border px-2.5 py-1.5 pl-2 font-sans text-[12.5px] font-medium transition-colors ${
                active
                  ? 'border-teal bg-sage text-ink'
                  : unfilled
                    ? 'border-[#e2711d] bg-surface text-ink-soft shadow-[0_0_0_1px_#e2711d] hover:text-ink'
                    : 'border-line bg-surface text-ink-soft hover:border-teal hover:text-ink'
              }`}
              onClick={() => setTopicIndex(i)}
            >
              <span className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-full text-[10.5px] font-bold ${active || done ? 'bg-teal text-white' : 'bg-[#ece4d6] text-ink-soft'}`}>{i + 1}</span>
              <span className="min-w-0 text-center leading-tight">{t.title}</span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-col gap-3.5 rounded-[10px] border border-line bg-surface p-4 px-[18px]">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="text-base font-bold text-ink">
            {topic.item_no ? `${topic.item_no}. ` : ''}{topic.title}
            {topic.code ? <span className="ml-1.5 text-[12px] font-semibold text-[#8E9398]">({topic.code})</span> : null}
          </div>
          <div className="whitespace-nowrap text-[12.5px] text-ink-soft">
            Topic {safeIndex + 1} of {topics.length} · {filledInTopic}/{topic.items.length} filled
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {topic.items.map((row) => (
            <label className="flex flex-col gap-1" key={row.item_no || row.concept}>
              <span className="font-sans text-[11px] font-semibold uppercase tracking-wide text-[#8E9398]">
                {row.item_no ? `${row.item_no}. ` : ''}{row.concept}
                {row.code ? <span className="ml-1 font-medium normal-case tracking-normal">({row.code})</span> : null}
              </span>
              <textarea
                className="box-border min-h-[44px] w-full resize-y rounded-lg border border-line bg-cream px-3 py-2 font-sans text-[13.5px] leading-relaxed text-ink placeholder:text-[#a49c8e] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                rows={3}
                value={fields[row.concept] || ''}
                placeholder={placeholders[row.concept] || `Details for ${row.concept}`}
                onChange={(e) => onFieldChange(row.concept, e.target.value)}
              />
            </label>
          ))}
        </div>

        <div className="mt-1 flex justify-between gap-3 border-t border-line pt-1">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setTopicIndex((i) => Math.max(0, i - 1))}
            disabled={isFirst}
            className="inline-flex items-center gap-1.5"
          >
            <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            Previous topic
          </Button>
          <Button
            size="sm"
            onClick={goNext}
            className="inline-flex items-center gap-1.5"
          >
            {isLast ? 'Save' : (
              <>
                Next topic
                <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              </>
            )}
          </Button>
        </div>
      </div>
    </>
  )
}
