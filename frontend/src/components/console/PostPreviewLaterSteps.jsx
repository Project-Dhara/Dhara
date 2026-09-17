'use client'

import { ArrowLeft } from 'lucide-react'
import BatchReview from './BatchReview'
import Classify from './Classify'
import Publish from './Publish'

/**
 * Shared metadata → classify → publish steps (Excel reference flow).
 * Used by Console (Excel/SQL) and PdfGrouping after the shared grouping step.
 */
export default function PostPreviewLaterSteps({
  step,
  matchResult,
  pdfJobId = null,
  metadataFiles = [],
  metadataStarted = false,
  metaLabel,
  metadataId,
  metadataIds,
  datasetLabel,
  hasKey,
  onBackToGrouping,
  onMetadataDone,
  onClassifyContinue,
  onGoSettings,
  onGoDashboard,
  onGoCatalogue,
  onUploadAnother,
  showMetadataHeading = false,
}) {
  return (
    <>
      {(metadataStarted || step === 4) && matchResult && (
        <div style={{ display: step === 4 ? (showMetadataHeading ? 'flex' : 'contents') : 'none' }} className={showMetadataHeading ? 'flex-col gap-[18px]' : undefined}>
          {showMetadataHeading && step === 4 && (
            <div className="min-w-0">
              <button
                type="button"
                className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
                onClick={onBackToGrouping}
              >
                <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
                Back to grouping
              </button>
              <div className="font-display text-[26px] font-medium leading-tight text-ink">Metadata</div>
            </div>
          )}
          <BatchReview
            matchResult={matchResult}
            pdfJobId={pdfJobId || matchResult?.pdf_job_id || null}
            metadataFiles={metadataFiles}
            onDone={onMetadataDone}
            onCancel={onBackToGrouping}
          />
        </div>
      )}

      {step === 5 && (
        <Classify
          metadataIds={metadataIds}
          datasetLabel={metaLabel || datasetLabel || 'This dataset'}
          onContinue={onClassifyContinue}
        />
      )}

      {step === 6 && (
        <Publish
          datasetLabel={metaLabel || datasetLabel || 'This dataset'}
          metadataId={metadataId}
          onGoDashboard={onGoDashboard}
          onGoCatalogue={onGoCatalogue}
          onUploadAnother={onUploadAnother}
        />
      )}
    </>
  )
}
