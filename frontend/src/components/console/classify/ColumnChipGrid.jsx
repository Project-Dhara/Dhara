'use client'

import { relatedAliasCount } from '../../../lib/classifyColumns'

const cardHeadClass = 'flex items-center gap-2.5 border-b border-line px-[18px] py-3 text-[15px] font-semibold text-ink'
const cardNoteClass = 'text-xs font-normal text-[#8E9398]'

/** Chip grid for picking one classified column to inspect below. */
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

      <div className="grid grid-cols-1 gap-2.5 border-b border-line p-4 px-[18px] sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {columns.map((c) => (
          <button
            key={`${c._metadataId || ''}:${c.name}`}
            type="button"
            className={`flex min-w-0 w-full cursor-pointer flex-col gap-1 rounded-lg border px-3.5 py-2.5 text-left transition-colors hover:border-[#c9bda6] ${
              c.name === selectedCol ? 'border-[#b9cfa9] bg-sage' : 'border-line bg-white'
            }`}
            onClick={() => onSelect(c.name)}
            title={c.name}
          >
            <div className="truncate text-[14px] font-semibold text-ink">{c.name}</div>
            <div className="truncate text-[12.5px] text-ink-soft">
              {c.codes.length} code{c.codes.length === 1 ? '' : 's'}
              {relatedAliasCount(c) > 0
                ? ` · +${relatedAliasCount(c)} in harmonisation`
                : ''}
            </div>
          </button>
        ))}
      </div>
    </>
  )
}
