'use client'

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import Combobox from '../../ui/Combobox'
import { relatedAliasCount } from '../../../lib/classifyColumns'

const cardHeadClass = 'flex flex-wrap items-center gap-2 border-b border-line px-[18px] py-2.5 text-[14px] font-semibold text-ink'
const cardNoteClass = 'text-[12px] font-normal text-[#8E9398]'
const CHIP_CAP = 12

/**
 * Column locator: searchable combobox + color-coded chips
 * (green = mapped, coral/red = unmapped; stronger red when highlightIncomplete).
 */
export default function ColumnChipGrid({
  columns,
  selectedCol,
  onSelect,
  saving,
  incompleteNames,
  highlightIncomplete = false,
}) {
  const unmapped = incompleteNames instanceof Set ? incompleteNames : new Set(incompleteNames || [])
  const [expanded, setExpanded] = useState(false)

  const ordered = useMemo(() => {
    const list = [...(columns || [])]
    list.sort((a, b) => {
      const aOpen = unmapped.has(a.name) ? 0 : 1
      const bOpen = unmapped.has(b.name) ? 0 : 1
      if (aOpen !== bOpen) return aOpen - bOpen
      const aLen = (a.codes || []).length
      const bLen = (b.codes || []).length
      if (aLen !== bLen) return bLen - aLen
      return String(a.name).localeCompare(String(b.name))
    })
    return list
  }, [columns, unmapped])

  useEffect(() => {
    if (ordered.length <= CHIP_CAP) setExpanded(false)
  }, [ordered.length])

  const options = useMemo(
    () => ordered.map((c) => {
      const n = (c.codes || []).length
      const isUnmapped = unmapped.has(c.name)
      return {
        value: c.name,
        label: `${c.name} (${n})`,
        badge: isUnmapped ? 'Unmapped' : 'Mapped',
        badgeTone: isUnmapped ? 'warn' : 'ok',
      }
    }),
    [ordered, unmapped],
  )

  const visible = useMemo(() => {
    if (expanded || ordered.length <= CHIP_CAP) return ordered
    const head = ordered.slice(0, CHIP_CAP)
    if (!selectedCol || head.some((c) => c.name === selectedCol)) return head
    // Keep the active chip visible even when it sits past the cap.
    const selected = ordered.find((c) => c.name === selectedCol)
    if (!selected) return head
    return [...head.slice(0, CHIP_CAP - 1), selected]
  }, [expanded, ordered, selectedCol])

  const hiddenCount = Math.max(0, ordered.length - CHIP_CAP)
  const mappedCount = Math.max(0, columns.length - unmapped.size)
  const canToggle = ordered.length > CHIP_CAP

  return (
    <>
      <div className={cardHeadClass}>
        <span>Classified columns</span>
        <span className={cardNoteClass}>
          {mappedCount}/{columns.length} mapped
          {unmapped.size > 0 ? ` · ${unmapped.size} unmapped` : ''}
          {saving ? ' · saving…' : ''}
        </span>
      </div>

      <div className="flex flex-col gap-2.5 border-b border-line px-[18px] py-3.5">
        <Combobox
          options={options}
          value={selectedCol ?? ''}
          onChange={(next) => onSelect(next)}
          placeholder="Find a column…"
          ariaLabel="Select classified column"
          menuMinWidth={420}
        />

        <div
          className={`grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-1.5 ${
            expanded ? 'max-h-[min(16rem,40vh)] overflow-y-auto' : ''
          }`}
          aria-label="Classified columns"
        >
          {visible.map((c) => {
            const selected = c.name === selectedCol
            const isUnmapped = unmapped.has(c.name)
            const needsAttention = highlightIncomplete && isUnmapped
            const n = (c.codes || []).length
            const related = relatedAliasCount(c)
            const chipTone = selected
              ? isUnmapped
                ? needsAttention
                  ? 'border-coral bg-[rgba(217,91,104,0.22)] text-coral ring-2 ring-coral/30'
                  : 'border-coral bg-[rgba(217,91,104,0.14)] text-coral'
                : 'border-green bg-[rgba(45,138,90,0.14)] text-green'
              : isUnmapped
                ? needsAttention
                  ? 'border-coral bg-[rgba(217,91,104,0.14)] text-coral hover:border-coral hover:bg-[rgba(217,91,104,0.2)]'
                  : 'border-coral/50 bg-[rgba(217,91,104,0.07)] text-coral hover:border-coral hover:bg-[rgba(217,91,104,0.12)]'
                : 'border-green/40 bg-[rgba(45,138,90,0.07)] text-green hover:border-green hover:bg-[rgba(45,138,90,0.12)]'
            const badgeTone = isUnmapped
              ? needsAttention
                ? 'bg-coral/25 text-coral'
                : 'bg-coral/15 text-coral'
              : 'bg-green/15 text-green'
            return (
              <button
                key={`${c._metadataId || ''}:${c.name}`}
                type="button"
                className={`flex h-8 w-full min-w-0 items-center gap-1.5 rounded-md border px-2.5 text-left transition-colors ${chipTone}`}
                onClick={() => onSelect(c.name)}
                title={
                  related > 0
                    ? `${c.name} · ${n} codes · ${isUnmapped ? 'unmapped' : 'mapped'} · +${related} related`
                    : `${c.name} · ${n} codes · ${isUnmapped ? 'unmapped' : 'mapped'}`
                }
              >
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold leading-none">
                  {c.name}
                </span>
                <span
                  className={`flex h-[18px] min-w-[18px] flex-none items-center justify-center rounded px-1.5 text-[10.5px] font-semibold tabular-nums leading-none ${badgeTone}`}
                >
                  {n}
                </span>
              </button>
            )
          })}
        </div>

        {canToggle && (
          <div className="flex justify-center pt-0.5">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-line bg-[#FBF9F4] px-3.5 py-1.5 text-[12.5px] font-semibold text-ink-soft transition-colors hover:border-teal/40 hover:bg-sage/60 hover:text-teal-deep"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
            >
              {expanded ? 'Show less' : `Show more (${hiddenCount})`}
              {expanded ? (
                <ChevronUp className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden />
              )}
            </button>
          </div>
        )}
      </div>
    </>
  )
}
