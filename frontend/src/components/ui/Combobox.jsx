'use client'

import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'

/**
 * Searchable single-select combobox: text input + filtered popover list.
 * options: [{ value, label }]
 */
export default function Combobox({
  options = [],
  value,
  onChange,
  placeholder = 'Select…',
  emptyLabel = 'No matches',
  ariaLabel,
  className = '',
  disabled = false,
  menuMinWidth = 360,
}) {
  const listId = useId()
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const [mounted, setMounted] = useState(false)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 })

  const selected = useMemo(
    () => options.find((o) => String(o.value) === String(value)) || null,
    [options, value],
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => String(o.label || '').toLowerCase().includes(q))
  }, [options, query])

  useEffect(() => { setMounted(true) }, [])

  const updateMenuPos = () => {
    const el = rootRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const minWidth = Math.max(Number(menuMinWidth) || 0, rect.width)
    const width = Math.min(minWidth, Math.max(window.innerWidth - 16, rect.width))
    const left = Math.min(
      Math.max(8, rect.left),
      Math.max(8, window.innerWidth - width - 8),
    )
    setMenuPos({
      top: rect.bottom + 6,
      left,
      width,
    })
  }

  useEffect(() => {
    if (!open) return undefined
    updateMenuPos()
    const onScroll = () => updateMenuPos()
    window.addEventListener('resize', onScroll)
    // Capture scroll from nested scrollports (console main pane).
    window.addEventListener('scroll', onScroll, true)
    return () => {
      window.removeEventListener('resize', onScroll)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      setQuery('')
      return undefined
    }
    const idx = filtered.findIndex((o) => String(o.value) === String(value))
    setHighlight(idx >= 0 ? idx : 0)
    return undefined
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (rootRef.current?.contains(e.target)) return
      if (listRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    if (!open || highlight < 0) return
    const el = listRef.current?.querySelector(`[data-combo-idx="${highlight}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [highlight, open, filtered])

  const commit = (opt) => {
    if (!opt) return
    onChange?.(opt.value)
    setOpen(false)
    setQuery('')
    inputRef.current?.blur()
  }

  const openMenu = () => {
    if (disabled) return
    setOpen(true)
    setQuery('')
    requestAnimationFrame(() => {
      updateMenuPos()
      inputRef.current?.focus()
    })
  }

  const onKeyDown = (e) => {
    if (disabled) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        openMenu()
        return
      }
      setHighlight((h) => (filtered.length ? Math.min((h < 0 ? 0 : h) + 1, filtered.length - 1) : -1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) {
        openMenu()
        return
      }
      setHighlight((h) => (filtered.length ? Math.max((h < 0 ? filtered.length - 1 : h) - 1, 0) : -1))
    } else if (e.key === 'Enter') {
      if (open && filtered[highlight]) {
        e.preventDefault()
        commit(filtered[highlight])
      }
    } else if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
        setQuery('')
      }
    }
  }

  // Closed: show selected label. Open + empty query: blank so placeholder shows (type to filter).
  const inputValue = open ? query : (selected?.label ?? '')

  const menu = open && mounted
    ? createPortal(
      <ul
        ref={listRef}
        id={listId}
        role="listbox"
        aria-label={ariaLabel || placeholder}
        style={{
          position: 'fixed',
          top: menuPos.top,
          left: menuPos.left,
          width: menuPos.width,
        }}
        className="z-[1200] max-h-72 overflow-auto rounded-xl border border-line bg-white py-1 shadow-[0_10px_30px_rgba(16,64,63,0.14)]"
      >
        {filtered.length === 0 ? (
          <li className="px-3.5 py-2.5 text-[13.5px] text-ink-soft">{emptyLabel}</li>
        ) : (
          filtered.map((opt, i) => {
            const isSelected = String(opt.value) === String(value)
            const isActive = i === highlight
            return (
              <li
                key={String(opt.value)}
                id={`${listId}-opt-${i}`}
                role="option"
                aria-selected={isSelected}
                data-combo-idx={i}
                title={opt.label}
                className={`flex cursor-pointer items-start gap-2.5 px-3.5 py-2 text-[13.5px] leading-snug ${
                  isActive
                    ? 'bg-sage text-teal-deep'
                    : isSelected
                      ? 'bg-cream/80 text-ink'
                      : 'text-ink hover:bg-cream'
                }`}
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault()
                  commit(opt)
                }}
              >
                <span className="mt-0.5 flex h-4 w-4 flex-none items-center justify-center">
                  {isSelected ? (
                    <Check className="h-3.5 w-3.5 text-teal" strokeWidth={2.5} aria-hidden />
                  ) : null}
                </span>
                <span className="min-w-0 flex-1 whitespace-normal break-words [overflow-wrap:anywhere]">
                  {opt.label}
                </span>
              </li>
            )
          })
        )}
      </ul>,
      document.body,
    )
    : null

  return (
    <div ref={rootRef} className={`relative w-full ${className}`}>
      <div
        className={`flex h-11 w-full items-center rounded-xl border bg-white transition-shadow duration-200 ${
          disabled
            ? 'cursor-not-allowed border-line opacity-60'
            : open
              ? 'border-teal shadow-focus-ring'
              : 'border-line hover:border-teal/40'
        }`}
      >
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && highlight >= 0 ? `${listId}-opt-${highlight}` : undefined}
          aria-label={ariaLabel || placeholder}
          disabled={disabled}
          placeholder={placeholder}
          value={inputValue}
          onChange={(e) => {
            setQuery(e.target.value)
            if (!open) setOpen(true)
            setHighlight(0)
            requestAnimationFrame(updateMenuPos)
          }}
          onFocus={() => openMenu()}
          onClick={() => {
            if (!open) openMenu()
          }}
          onKeyDown={onKeyDown}
          className="min-w-0 flex-1 bg-transparent px-3.5 py-2.5 font-sans text-[14px] text-ink placeholder:text-ink-soft/80 focus:outline-none disabled:cursor-not-allowed"
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          aria-label={open ? 'Close options' : 'Open options'}
          className="mr-1 flex h-9 w-9 flex-none items-center justify-center rounded-lg text-ink-soft hover:bg-cream hover:text-teal disabled:cursor-not-allowed"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            if (disabled) return
            if (open) {
              setOpen(false)
              setQuery('')
            } else {
              openMenu()
            }
          }}
        >
          <ChevronDown
            className={`h-4 w-4 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            strokeWidth={2}
            aria-hidden
          />
        </button>
      </div>
      {menu}
    </div>
  )
}
