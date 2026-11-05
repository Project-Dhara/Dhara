'use client'

import { createPortal } from 'react-dom'
import { useEffect, useState } from 'react'
import Button from '../ui/Button'

/**
 * When leaving Preview/Grouping/Processing for Files: choose append vs start over.
 */
export default function FilesReturnChoiceDialog({
  open,
  onCancel,
  onAddMore,
  onStartOver,
  title,
  body,
  startOverBusy = false,
}) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  if (!open || !mounted) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="files-return-title"
      aria-describedby="files-return-body"
      onClick={startOverBusy ? undefined : onCancel}
    >
      <div
        className="flex w-full max-w-[460px] flex-col gap-3.5 rounded-xl border border-line bg-white p-5 shadow-[0_16px_40px_rgba(16,64,63,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="files-return-title" className="text-[16px] font-bold text-ink">
          {title || 'Back to Files'}
        </div>
        <p id="files-return-body" className="text-[13px] leading-snug text-ink-soft">
          {body || (
            <>
              Do you want to keep your current extract and add more files, or start over
              with a new upload? Starting over clears this session&apos;s progress.
            </>
          )}
        </p>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
          <Button variant="secondary" size="sm" disabled={startOverBusy} onClick={onCancel}>
            Stay here
          </Button>
          <Button variant="secondary" size="sm" disabled={startOverBusy} onClick={onAddMore}>
            Upload additional files
          </Button>
          <Button
            variant="primary"
            size="sm"
            className="!bg-[#c45c4a] hover:!bg-[#a84a3b]"
            disabled={startOverBusy}
            onClick={onStartOver}
          >
            {startOverBusy ? 'Cancelling…' : 'Start over with new files'}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
