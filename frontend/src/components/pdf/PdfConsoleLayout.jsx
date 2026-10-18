'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ConsoleStagesShell } from '../console/ConsoleStages'
import FilesReturnChoiceDialog from '../console/FilesReturnChoiceDialog'
import { beginAppendFilesMode, goToConsoleFiles } from '../../lib/consoleSession'

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
  children,
}) {
  const router = useRouter()
  const [filesReturnOpen, setFilesReturnOpen] = useState(false)

  const openFilesChoice = () => setFilesReturnOpen(true)

  const defaultGoToStep = (targetStep) => {
    if (targetStep === 1) {
      if (jobId && maxStepReached >= 2) {
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

  return (
    <>
      <FilesReturnChoiceDialog
        open={filesReturnOpen}
        onCancel={() => setFilesReturnOpen(false)}
        onAddMore={() => {
          setFilesReturnOpen(false)
          if (!jobId) {
            goToConsoleFiles(router)
            return
          }
          beginAppendFilesMode(router, {
            jobId,
            existingFilenames: existingFilenames.length ? existingFilenames : [],
            returnPath: jobId ? `/console/review/${jobId}` : null,
          })
        }}
        onStartOver={() => {
          setFilesReturnOpen(false)
          goToConsoleFiles(router)
        }}
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
