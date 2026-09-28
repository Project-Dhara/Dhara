'use client'

import { useRef } from 'react'
import { ArrowLeft } from 'lucide-react'
import BatchReview from './BatchReview'
import Classify from './Classify'
import Publish from './Publish'
import ClassifyBreadcrumb from './classify/ClassifyBreadcrumb'

/**
 * Shared metadata → classify → harmonise → publish steps (Excel reference flow).
 * Used by Console (Excel/SQL) and PdfGrouping after the shared grouping step.
 *
 * Classify stays mounted across steps 5–6 so codes / NCO / harmonise state
 * survive breadcrumb navigation. Leaving Classification with empty codes shows
 * a confirm dialog inside Classify before Harmonisation opens.
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
  onClassifyPhaseChange,
  onClassifyContinue,
  onClassificationCompleteChange,
  onRegisterGoToHarmonisation,
  classificationComplete = false,
  onGoSettings,
  onGoDashboard,
  onGoCatalogue,
  onUploadAnother,
  onMatchResultChange,
  showMetadataHeading = false,
  showClassifyHeading = false,
}) {
  const goToHarmRef = useRef(null)
  const onClassifySteps = step === 5 || step === 6
  const phase = step === 6 ? 'harmonisation' : 'classification'

  const requestHarmonisation = () => {
    if (goToHarmRef.current) goToHarmRef.current()
    else if (classificationComplete) onClassifyPhaseChange?.('harmonisation')
  }

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
            onMatchResultChange={onMatchResultChange}
            onGoSettings={onGoSettings}
          />
        </div>
      )}

      {onClassifySteps && showClassifyHeading && (
        <div className="min-w-0">
          {step === 6 && (
            <button
              type="button"
              className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={() => onClassifyPhaseChange?.('classification')}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Back to classification
            </button>
          )}
          <ClassifyBreadcrumb
            phase={phase}
            canOpenHarmonisation={classificationComplete}
            onNavigate={(next) => {
              if (next === 'harmonisation') requestHarmonisation()
              else onClassifyPhaseChange?.('classification')
            }}
            size="page"
          />
        </div>
      )}

      {(step === 5 || step === 6) && (
        <Classify
          metadataIds={metadataIds}
          datasetLabel={metaLabel || datasetLabel || 'This dataset'}
          phase={phase}
          hasKey={hasKey}
          onGoSettings={onGoSettings}
          onPhaseChange={onClassifyPhaseChange}
          onClassificationCompleteChange={onClassificationCompleteChange}
          onRegisterGoToHarmonisation={(fn) => {
            goToHarmRef.current = fn
            onRegisterGoToHarmonisation?.(fn)
          }}
          onContinue={onClassifyContinue}
        />
      )}

      {step === 7 && (
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
