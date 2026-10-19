'use client'

import { useRef } from 'react'
import BatchReview from './BatchReview'
import Classify from './Classify'
import Publish from './Publish'
import ClassifyBreadcrumb from './classify/ClassifyBreadcrumb'
import StageSubstepBreadcrumb from './StageSubstepBreadcrumb'
import { METADATA_CRUMBS } from './ConsoleStages'
import KydsSummaryCard from '../KydsSummaryCard'

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
            <div className="flex items-start justify-between gap-6">
              <div className="min-w-0">
                <StageSubstepBreadcrumb
                  crumbs={METADATA_CRUMBS}
                  activeId="metadata"
                  onNavigate={(next) => {
                    if (next === 'grouping') onBackToGrouping?.()
                  }}
                  isReachable={(crumb) => crumb.id === 'grouping' || crumb.id === 'metadata'}
                  ariaLabel="Metadata workspace"
                  size="page"
                />
              </div>
              <div className="flex flex-none flex-shrink-0 flex-wrap items-center justify-end gap-2.5">
                <KydsSummaryCard variant="corner" />
              </div>
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
