'use client'

import { useLayoutEffect, useRef, useState } from 'react'
import { ArrowRight, Upload } from 'lucide-react'
import { NMDS_TOPICS } from '../../lib/nmdsConcepts'
import Button from '../ui/Button'
import { REQUIRED_EMPTY_INPUT_CLASS } from './MetadataSheetGrid'

function GrowingTextarea({ value, onChange, placeholder, missing }) {
  const ref = useRef(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(el.scrollHeight, 72)}px`
  }, [value])

  return (
    <textarea
      ref={ref}
      className={`box-border min-h-[72px] w-full resize-y overflow-hidden rounded-lg border px-3 py-2 font-sans text-[13.5px] leading-relaxed text-ink placeholder:text-ink-muted focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal ${
        missing ? REQUIRED_EMPTY_INPUT_CLASS : 'border-line-strong bg-cream'
      }`}
      rows={3}
      value={value}
      placeholder={placeholder}
      onChange={onChange}
      aria-required
    />
  )
}

// The topic-pills + one-topic-at-a-time field box, factored out of
// NmdsConceptForm so it can also be shown inside a modal (per metadata
// group) without duplicating the field-rendering logic.
export default function NmdsConceptFields({
  fields,
  onFieldChange,
  onSave,
  topics = NMDS_TOPICS,
  placeholders = {},
  canApplyToAll = false,
  appliedToAll = false,
  onApplyToAllChange,
  onFileSelected,
  uploadStatus = null,
  standardName = 'NMDS',
}) {
  const [topicIndex, setTopicIndex] = useState(0)
  const fileInputRef = useRef(null)
  const safeIndex = Math.min(topicIndex, Math.max(0, topics.length - 1))
  const topic = topics[safeIndex]
  const isLast = safeIndex === topics.length - 1

  if (!topic) return null

  const filledInTopic = topic.items.filter((r) => (fields[r.concept] || '').trim()).length
  const filledCount = Object.values(fields || {}).filter((v) => String(v || '').trim()).length

  const goNext = () => {
    if (isLast) onSave?.()
    else setTopicIndex((i) => Math.min(topics.length - 1, i + 1))
  }

  const openFilePicker = () => {
    fileInputRef.current?.click()
  }

  const onFileChange = (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) onFileSelected?.(file)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2.5">
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xls,.csv"
        className="hidden"
        onChange={onFileChange}
      />

      <div className="grid flex-none grid-cols-5 gap-1.5 p-px max-[900px]:grid-cols-3 max-[560px]:grid-cols-2">
        {topics.map((t, i) => {
          const filled = t.items.filter((r) => (fields[r.concept] || '').trim()).length
          const active = i === safeIndex
          const done = filled === t.items.length
          const unfilled = !done
          return (
            <button
              key={t.item_no || t.title}
              type="button"
              title={t.title}
              className={`dhara-tab flex min-w-0 items-center gap-1.5 rounded-full px-2 py-1 pl-1.5 font-sans text-[11px] font-medium leading-none ${
                active
                  ? 'border-transparent bg-teal-deep text-cream'
                  : unfilled
                    ? 'border-yellow bg-white text-ink-soft hover:text-ink'
                    : 'border-line bg-white text-ink-soft hover:bg-sage hover:text-teal-deep'
              }`}
              onClick={() => setTopicIndex(i)}
            >
              <span className={`inline-flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px] font-bold transition-colors duration-[420ms] ${active ? 'bg-teal text-white' : done ? 'bg-green text-white' : 'bg-mist text-ink-soft'}`}>{i + 1}</span>
              <span className="min-w-0 truncate">{t.title}</span>
            </button>
          )
        })}
      </div>

      <div key={safeIndex} className="dhara-tab-panel flex min-h-0 flex-1 flex-col gap-3.5 overflow-hidden rounded-[10px] border border-line bg-surface p-4 px-[18px]">
        <div className="flex flex-none flex-col gap-1">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div className="text-base font-bold text-ink">
              {topic.item_no ? `${topic.item_no}. ` : ''}{topic.title}
              {topic.code ? <span className="ml-1.5 text-[12px] font-semibold text-ink-soft">({topic.code})</span> : null}
            </div>
            <div className="whitespace-nowrap text-[12.5px] text-ink-soft">
              Topic {safeIndex + 1} of {topics.length} · {filledInTopic}/{topic.items.length} filled
            </div>
          </div>
          <p className="m-0 text-[12px] leading-snug text-ink-soft">
            These fields can be filled manually or autofilled by uploading a prefilled file.
          </p>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
          {topic.items.map((row) => {
            const value = fields[row.concept] || ''
            const missing = !value.trim()
            return (
              <label className="flex flex-col gap-1" key={row.item_no || row.concept}>
                <span className="font-sans text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  {row.item_no ? `${row.item_no}. ` : ''}{row.concept}
                  {row.code ? <span className="ml-1 font-medium normal-case tracking-normal">({row.code})</span> : null}
                  {' *'}
                </span>
                <GrowingTextarea
                  value={value}
                  missing={missing}
                  placeholder={placeholders[row.concept] || `Details for ${row.concept}`}
                  onChange={(e) => onFieldChange(row.concept, e.target.value)}
                />
              </label>
            )
          })}
        </div>

        <div className="mt-1 flex flex-none flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
          <div className="flex min-w-0 flex-col gap-1">
            <Button
              variant="secondary"
              size="sm"
              onClick={openFilePicker}
              className="inline-flex w-fit items-center gap-1.5"
            >
              <Upload className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              Auto-fill from file
            </Button>
            {uploadStatus}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {isLast && canApplyToAll && (
              <label className={`inline-flex select-none items-center gap-2 font-sans text-[13px] font-semibold ${filledCount === 0 ? 'cursor-default text-ink-muted' : 'cursor-pointer text-ink'}`}>
                <input
                  type="checkbox"
                  className="m-0 h-[15px] w-[15px] accent-teal"
                  checked={!!appliedToAll}
                  disabled={filledCount === 0}
                  onChange={(e) => onApplyToAllChange?.(e.target.checked)}
                />
                <span>Apply to all groups</span>
              </label>
            )}
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
      </div>
    </div>
  )
}
