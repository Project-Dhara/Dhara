'use client'

import { useState } from 'react'
import { ArrowLeft, ArrowRight, AlertTriangle } from 'lucide-react'
import { NMDS_TOPICS } from '../lib/nmdsConcepts'
import FileUpload from './FileUpload'
import Button from './ui/Button'

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
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="text-xs font-bold uppercase tracking-wide text-ink">Upload NMDS concept metadata *</div>
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
          <div className="mt-1.5 flex flex-col gap-0.5">
            {!parsing && !parseError && !fileMismatch && (
              <div className="mt-0.5 text-[11px] text-teal">{file.name} — fields filled in below</div>
            )}
            {parsing && <div className="mt-0.5 text-[11px] text-ink-soft">Reading concept metadata from {file.name}…</div>}
            {parseError && (
              <div className="mt-0.5 text-[11px] text-[#c0392b]">
                Couldn't auto-fill from {file.name}: {parseError}. You can still fill the fields in manually.
              </div>
            )}
            {!parsing && !parseError && fileMismatch && (
              <div className="mt-1 text-[13.5px] font-medium text-[#8a4b0f]">
                <span className="inline-flex items-start gap-1.5">
                  <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                  <span>
                    Couldn&apos;t match {file.name} against the known NMDS concepts — double-check you&apos;ve uploaded the
                    right file. You can still fill the fields in manually below.
                  </span>
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-4 gap-x-4 gap-y-3.5 max-[900px]:grid-cols-2 max-[560px]:grid-cols-1">
        {NMDS_TOPICS.map((t, i) => {
          const filled = t.items.filter((r) => (fields[r.concept] || '').trim()).length
          const active = i === topicIndex
          const done = filled === t.items.length
          const unfilled = !done
          return (
            <button
              key={t.item_no}
              type="button"
              className={`dhara-tab grid min-w-0 grid-cols-[18px_1fr] items-center gap-2 rounded-full px-2.5 py-1.5 pl-2 font-sans text-[12.5px] font-medium ${
                active
                  ? 'border-transparent bg-teal-deep text-cream'
                  : unfilled
                    ? 'border-yellow bg-white text-ink-soft shadow-[0_0_0_1px_#E5B72F] hover:text-ink'
                    : 'border-line bg-white text-ink-soft hover:bg-sage hover:text-teal-deep'
              }`}
              onClick={() => setTopicIndex(i)}
            >
              <span className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-full text-[10.5px] font-bold transition-colors duration-[420ms] ${active ? 'bg-teal text-white' : done ? 'bg-green text-white' : 'bg-mist text-ink-soft'}`}>{i + 1}</span>
              <span className="min-w-0 text-center leading-tight">{t.title}</span>
            </button>
          )
        })}
      </div>

      <div key={topicIndex} className="dhara-tab-panel flex flex-col gap-3.5 rounded-[10px] border border-line bg-surface p-4 px-[18px]">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="text-base font-bold text-ink">{topic.item_no}. {topic.title}</div>
          <div className="whitespace-nowrap text-[12.5px] text-ink-soft">
            Topic {topicIndex + 1} of {NMDS_TOPICS.length} · {filledInTopic}/{topic.items.length} filled
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {topic.items.map((row) => (
            <label className="flex flex-col gap-1" key={row.item_no}>
              <span className="font-sans text-[11px] font-semibold uppercase tracking-wide text-ink-soft">{row.item_no} {row.concept}</span>
              <textarea
                className="box-border min-h-[44px] w-full resize-y rounded-lg border border-line-strong bg-cream px-3 py-2 font-sans text-[13.5px] leading-relaxed text-ink placeholder:text-ink-muted focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal"
                rows={3}
                value={fields[row.concept] || ''}
                placeholder={`Details for ${row.concept}`}
                onChange={(e) => onFieldChange(row.concept, e.target.value)}
              />
            </label>
          ))}
        </div>

        <div className="mt-1 flex justify-between gap-3 border-t border-line pt-1">
          <Button variant="secondary" size="sm" onClick={goBack} disabled={saving} className="inline-flex items-center gap-1.5">
            <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            {isFirst ? 'Back to metadata' : 'Previous topic'}
          </Button>
          <Button size="sm" onClick={goNext} disabled={saving || (isLast && saveDisabled)} className="inline-flex items-center gap-1.5">
            {isLast ? (saving ? 'Pushing…' : (
              <>
                Save & continue to classification
                <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              </>
            )) : (
              <>
                Next topic
                <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}