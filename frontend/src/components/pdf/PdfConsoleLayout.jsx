'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ConsoleStagesShell } from '../console/ConsoleStages'
import FilesReturnChoiceDialog from '../console/FilesReturnChoiceDialog'
import { beginAppendFilesMode, goToConsoleFiles } from '../../lib/consoleSession'
import { withAuthHeaders } from '../../lib/auth'

/**
 * PDF pipeline stages map onto the same Console Stages numbers as Excel:
 *   1 Files · 2 Preview · 3 Grouping · 4 Metadata · 5 Classification · 6 Harmonisation · 7 Publish
 *
 * Pass `onGoToStep` when the page owns later steps in-memory (grouping →
 * metadata onward); otherwise default to the review/grouping routes.
 */
export default function PdfConsoleLayout({
  jobId,
  step,
  maxStepReached,
  onGoToStep = undefined,
  isStepReachable = undefined,
  /** Filenames already in this job — used for "add more" mode. */
  existingFilenames = [],
  /**
   * When true (processing page), clicking Files while a job is active opens
   * the append / start-over dialog even though maxStepReached is still 1.
   */
  askBeforeLeaveFiles = false,
  /** Where "add more" should return after upload (processing/review/…). */
  filesReturnPath = null,
  /** Dialog copy override for in-flight extraction. */
  filesReturnTitle = undefined,
  filesReturnBody = undefined,
  /** Cancel the active job when the user chooses Start over. */
  cancelJobOnStartOver = false,
  children,
}) {
  const router = useRouter()
  const [filesReturnOpen, setFilesReturnOpen] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  const openFilesChoice = () => setFilesReturnOpen(true)

  const defaultReturnPath = filesReturnPath
    || (jobId ? `/console/review/${jobId}` : null)

  const defaultGoToStep = (targetStep) => {
    if (targetStep === 1) {
      if (jobId && (maxStepReached >= 2 || askBeforeLeaveFiles)) {
        openFilesChoice()
        return
      }
      goToConsoleFiles(router)
      return
    }
    if (!jobId) return
    if (targetStep === 2) {
      router.push(`/console/review/${jobId}`)
      return
    }
    if (targetStep === 3) {
      router.push(`/console/grouping/${jobId}`)
    }
  }

  const handleGoToStep = (targetStep) => {
    if (targetStep === 1 && onGoToStep) {
      // Let the parent show the same choice (it owns return-path / pipeline state).
      onGoToStep(1)
      return
    }
    ;(onGoToStep || defaultGoToStep)(targetStep)
  }

  const confirmAddMore = () => {
    setFilesReturnOpen(false)
    if (!jobId) {
      goToConsoleFiles(router)
      return
    }
    beginAppendFilesMode(router, {
      jobId,
      existingFilenames: existingFilenames.length ? existingFilenames : [],
      returnPath: defaultReturnPath,
    })
  }

  const confirmStartOver = async () => {
    if (cancelling) return
    setCancelling(true)
    try {
      if (cancelJobOnStartOver && jobId) {
        try {
          await fetch(
            `/api/pdf/jobs/${encodeURIComponent(jobId)}/cancel`,
            withAuthHeaders({ method: 'POST' }),
          )
        } catch {
          // Best-effort — still leave Files so the user is not stuck.
        }
      }
      setFilesReturnOpen(false)
      goToConsoleFiles(router)
    } finally {
      setCancelling(false)
    }
  }

  return (
    <>
      <FilesReturnChoiceDialog
        open={filesReturnOpen}
        title={filesReturnTitle}
        body={filesReturnBody}
        startOverBusy={cancelling}
        onCancel={() => {
          if (!cancelling) setFilesReturnOpen(false)
        }}
        onAddMore={confirmAddMore}
        onStartOver={confirmStartOver}
      />
      <ConsoleStagesShell
        step={step}
        maxStepReached={maxStepReached}
        onGoToStep={handleGoToStep}
        isStepReachable={isStepReachable}
      >
        {children}
      </ConsoleStagesShell>
    </>
  )
}
