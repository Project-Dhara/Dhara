'use client'

import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

/**
 * Viewport-fixed toast. Portaled to document.body so it stays on screen even
 * when the page content is inside a transformed / scrollable AppShell shell.
 */
export default function Toast({
  message,
  onDismiss,
  tone = 'success', // 'success' | 'warn' | 'info'
  className = '',
}) {
  if (!message || typeof document === 'undefined') return null

  const toneClass =
    tone === 'success'
      ? 'bg-green text-white'
      : tone === 'warn'
        ? 'border border-yellow bg-warn-bg text-ink'
        : 'border border-[#c9610f] bg-[#e2711d] text-[#111]'

  return createPortal(
    <div
      className={`fixed right-6 top-6 z-[1300] flex max-w-[min(420px,calc(100vw-3rem))] animate-toast-in items-center gap-3 rounded-[10px] py-3 pl-[18px] pr-4 font-sans text-sm font-medium leading-snug shadow-lg ${toneClass} ${className}`}
      role="alert"
    >
      <span className="min-w-0 [overflow-wrap:anywhere]">{message}</span>
      {onDismiss && (
        <button
          type="button"
          className="flex h-6 w-6 flex-none items-center justify-center rounded px-0.5 text-current opacity-70 hover:opacity-100"
          onClick={onDismiss}
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" strokeWidth={1.75} />
        </button>
      )}
    </div>,
    document.body,
  )
}
