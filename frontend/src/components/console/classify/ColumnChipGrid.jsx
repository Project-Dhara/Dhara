'use client'

import { relatedAliasCount } from '../../../lib/classifyColumns'

const cardHeadClass = 'flex flex-wrap items-center gap-2 border-b border-line px-[18px] py-2.5 text-[14px] font-semibold text-ink'
const cardNoteClass = 'text-[12px] font-normal text-[#8E9398]'

/** Evenly spaced chip grid for picking one classified column to inspect below. */
export default function ColumnChipGrid({ columns, selectedCol, onSelect, saving }) {
  return (
    <>
      <div className={cardHeadClass}>
        <span>Classified columns</span>
        <span className={cardNoteClass}>
          {columns.length} columns · pick one to check its code list
          {saving ? ' · saving…' : ''}
        </span>
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(10.75rem,1fr))] gap-2 border-b border-line px-[18px] py-3.5">
        {columns.map((c) => {
          const selected = c.name === selectedCol
          const related = relatedAliasCount(c)
          return (
            <button
              key={`${c._metadataId || ''}:${c.name}`}
              type="button"
              className={`flex h-8 w-full min-w-0 items-center gap-1.5 rounded-full border px-2.5 text-left transition-colors ${
                selected
                  ? 'border-teal bg-sage text-teal-deep'
                  : 'border-line bg-white text-ink hover:border-teal/40 hover:bg-cream'
              }`}
              onClick={() => onSelect(c.name)}
              title={
                related > 0
                  ? `${c.name} · ${c.codes.length} codes · +${related} in harmonisation`
                  : `${c.name} · ${c.codes.length} codes`
              }
            >
              <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold leading-none">
                {c.name}
              </span>
              <span
                className={`flex h-[18px] min-w-[18px] flex-none items-center justify-center rounded-full px-1.5 text-[10.5px] font-semibold tabular-nums leading-none ${
                  selected ? 'bg-teal/15 text-teal-deep' : 'bg-cream text-ink-soft'
                }`}
              >
                {c.codes.length}
              </span>
            </button>
          )
        })}
      </div>
    </>
  )
}
