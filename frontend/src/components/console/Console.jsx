'use client'

import { useRef, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import KydsSummaryCard from '../KydsSummaryCard'
import TableViewer from '../TableViewer'
import BatchUpload from './BatchUpload'
import SqlUpload from './SqlUpload'
import ReconcileIds from './ReconcileIds'
import GroupingWorkspace from './GroupingWorkspace'
import PostPreviewLaterSteps from './PostPreviewLaterSteps'
import ConsoleStatusPlaceholder from './ConsoleStatusPlaceholder'
import { StageSidebar, withinStageBack } from './ConsoleStages'
import { tableCode, tablePickerLabel } from '../../lib/postPreview'
import { UploadChoice } from './ConsoleUploadChoice'
import { useConsolePipeline } from './useConsolePipeline'
import ClassifyBreadcrumb from './classify/ClassifyBreadcrumb'
import LlmKeyRequiredBanner from '../LlmKeyRequiredBanner'
import { useApp } from '../../context/AppContext'

export default function Console({ hasKey, onGoSettings, onGoDashboard, onGoCatalogue, onUploadAnother }) {
  const { keySaved } = useApp()
  const hasLlmKey = hasKey || keySaved
  const {
    STATUS_TRANSITIONS,
    addPendingDatasetFiles,
    addStep1MetadataFiles,
    applyReconcile,
    autoMatchResultRef,
    batchAllTables,
    editingGroups,
    effectiveDataset,
    expandedStage,
    filteredPreviewTables,
    goToStep,
    groupingToast,
    handleDatasetFile,
    handleMatched,
    handlePdfFile,
    handleRequestAutomatic,
    info,
    manualGrouping,
    markTableSaved,
    updatePreviewTableId,
    matchResult,
    maxStepReached,
    metaLabel,
    metadataFiles,
    metadataFilling,
    metadataId,
    metadataIds,
    metadataStarted,
    okPreviewCount,
    pdfError,
    pdfUploading,
    pendingDatasetFiles,
    previewDatasets,
    previewReviewFilter,
    previewReviewStatus,
    previewSelected,
    previewTables,
    publishFromClassify,
    removePendingDatasetFile,
    removeStep1MetadataFile,
    requestContinueToMetadata,
    savedIds,
    selectPreviewDataset,
    selectPreviewTable,
    setEditingGroups,
    setExpandedStage,
    setGroupingToast,
    setManualGrouping,
    setMatchResult,
    setMetaLabel,
    setMetadataId,
    setMetadataIds,
    setPdfError,
    setPendingDatasetFiles,
    setPendingGroups,
    setPreviewReviewFilter,
    setStatusPage,
    setStep,
    setStep1MetadataFiles,
    setUploadChoice,
    stageIdx,
    statusPage,
    step,
    step1MetadataFiles,
    unsavedAiFilled,
    unsavedMismatched,
    uploadChoice,
    visiblePreviewTables,
  } = useConsolePipeline()

  const [classificationComplete, setClassificationComplete] = useState(false)
  const goToHarmRef = useRef(null)
  const stageBack = withinStageBack(step)

  const requestHarmonisation = () => {
    if (goToHarmRef.current) goToHarmRef.current()
    else if (classificationComplete) setStep(6)
  }

  const goToStepGuarded = (targetStep) => {
    if (targetStep === 6) {
      requestHarmonisation()
      return
    }
    goToStep(targetStep)
  }

  return (
    <div className="flex flex-col gap-5">
      <StageSidebar
        stageIdx={stageIdx}
        step={step}
        maxStepReached={maxStepReached}
        expandedStage={expandedStage}
        setExpandedStage={setExpandedStage}
        goToStep={goToStepGuarded}
        isStepReachable={(s) => {
          if (s === 6) return classificationComplete
          return s <= maxStepReached
        }}
      />

      <div key={step === 5 || step === 6 ? 'classify-harmonise' : step} className="dhara-page-enter flex min-w-0 flex-1 flex-col gap-[18px]">
        {/* Page header — title / purpose stay above the content panel */}
        {!statusPage && (
        <div className="flex flex-col">
          {stageBack && (
            <div
              className="mb-3.5 inline-flex cursor-pointer items-center gap-1.5 text-[14px] font-medium text-teal transition-colors duration-dhara ease-dhara hover:text-teal-dark"
              onClick={() => setStep(stageBack.step)}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden />
              {stageBack.label}
            </div>
          )}
          <div className="flex items-center justify-between gap-6">
            <div>
              {(step === 5 || step === 6) ? (
                <ClassifyBreadcrumb
                  phase={step === 6 ? 'harmonisation' : 'classification'}
                  canOpenHarmonisation={classificationComplete}
                  onNavigate={(next) => {
                    if (next === 'harmonisation') requestHarmonisation()
                    else setStep(5)
                  }}
                  size="page"
                />
              ) : (
                <div className="dhara-page-title">{info.title}</div>
              )}
            </div>
            {stageIdx === 0 && (step === 1 || step === 2) && <KydsSummaryCard variant="corner" />}
          </div>
        </div>
        )}

        {/* Shared content panel — choice cards, then tables / grouping / later steps */}
        <div className="flex flex-col gap-5 rounded-2xl border border-line/90 bg-white p-5 sm:p-6">
        {statusPage && (
          <ConsoleStatusPlaceholder
            key={statusPage.key}
            title={statusPage.title}
            subtitle={statusPage.subtitle}
            steps={statusPage.steps}
            work={statusPage.work || null}
            msPerStep={statusPage.msPerStep || 850}
            onComplete={statusPage.after}
          />
        )}
        <div style={{ display: statusPage ? 'none' : undefined }}>
        {step === 1 && (
          <div className="flex flex-col gap-6">
            {!hasLlmKey && <LlmKeyRequiredBanner onGoSettings={onGoSettings} />}
            <UploadChoice
              choice={uploadChoice}
              onChoose={setUploadChoice}
              onDatasetFile={handleDatasetFile}
              onDatasetFilesAdd={addPendingDatasetFiles}
              onDatasetFileRemove={removePendingDatasetFile}
              datasetFiles={pendingDatasetFiles}
              onPdfFile={handlePdfFile}
              pdfUploading={pdfUploading}
              pdfError={pdfError}
              onClearPdfError={() => setPdfError('')}
              metadataFiles={step1MetadataFiles}
              onMetadataFilesAdd={addStep1MetadataFiles}
              onMetadataFileRemove={removeStep1MetadataFile}
              sqlPanel={(
                <SqlUpload
                  onMatched={handleMatched}
                  metadataFiles={step1MetadataFiles}
                  onMetadataFilesChange={setStep1MetadataFiles}
                  hideMetadataSection
                />
              )}
            />
            {uploadChoice === 'xlsx' && pendingDatasetFiles.length > 0 && (
              <BatchUpload
                onMatched={handleMatched}
                datasetFiles={pendingDatasetFiles}
                onDatasetFilesChange={setPendingDatasetFiles}
                metadataFiles={step1MetadataFiles}
                onMetadataFilesChange={setStep1MetadataFiles}
                hideMetadataSection
                hideDatasetSection
              />
            )}
          </div>
        )}

        {step === 2 && previewTables.length > 0 && (
          <div className="flex flex-col gap-6">
            {previewDatasets.length > 1 && (
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Dataset</span>
                {previewDatasets.length > 2 ? (
                  <select
                    className="rounded-md border border-line-strong bg-white px-3 py-1.5 text-[13px] text-ink outline-none focus:border-teal"
                    value={effectiveDataset}
                    onChange={(e) => selectPreviewDataset(e.target.value)}
                  >
                    {previewDatasets.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                ) : (
                  previewDatasets.map((name) => (
                    <div
                      key={name}
                      className={`dhara-tab cursor-pointer rounded-full border px-3 py-1.5 text-sm ${
                        name === effectiveDataset
                          ? 'border-transparent bg-teal-deep text-cream'
                          : 'border-line bg-white text-ink hover:bg-sage hover:text-teal-deep'
                      }`}
                      onClick={() => selectPreviewDataset(name)}
                      title={name}
                    >
                      {name}
                    </div>
                  ))
                )}
              </div>
            )}

            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Filter</span>
                  {[
                    { id: 'all', label: 'All', count: visiblePreviewTables.length, activeClass: 'bg-teal-deep text-cream' },
                    { id: 'fix', label: 'Needs fixing', count: unsavedMismatched.length, activeClass: 'bg-coral text-white', idleClass: 'border-coral/35 text-coral hover:bg-error-bg' },
                    { id: 'ai', label: 'AI review', count: unsavedAiFilled.length, activeClass: 'bg-[#2F6FED] text-white', idleClass: 'border-[#5B8DEF]/40 text-[#2F6FED] hover:bg-[#EEF4FF]' },
                    { id: 'ok', label: 'Reviewed', count: okPreviewCount, activeClass: 'bg-green text-white', idleClass: 'border-green/40 text-green hover:bg-sage' },
                  ]
                    .filter((f) => {
                      if (f.id === 'all') return true
                      if (f.id === 'ok') return unsavedMismatched.length > 0 || unsavedAiFilled.length > 0 || previewReviewFilter !== 'all'
                      return f.count > 0
                    })
                    .map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] font-semibold transition-colors ${
                        previewReviewFilter === f.id
                          ? `border-transparent ${f.activeClass}`
                          : `border-line bg-white text-ink-soft ${f.idleClass || 'hover:bg-sage hover:text-teal-deep'}`
                      }`}
                      onClick={() => setPreviewReviewFilter(f.id)}
                    >
                      {f.label}
                      <span className={`rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold ${
                        previewReviewFilter === f.id ? 'bg-white/20' : 'bg-cream text-ink-soft'
                      }`}>
                        {f.count}
                      </span>
                    </button>
                  ))}
                </div>

                <div className="ml-auto flex flex-col items-center gap-1.5 text-[12.5px] font-medium text-ink">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Details</span>
                  <div className="flex flex-wrap items-center justify-center gap-3.5">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 flex-none rounded-[3px] bg-coral" aria-hidden />
                      Partial
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 flex-none rounded-[3px] bg-[#2F6FED]" aria-hidden />
                      Missing (Filled by AI)
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 flex-none rounded-[3px] bg-green" aria-hidden />
                      present
                    </span>
                  </div>
                </div>
              </div>

              {filteredPreviewTables.length === 0 ? (
                <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-soft">
                  No tables in this filter. Choose another status above.
                </div>
              ) : filteredPreviewTables.length > 10 ? (
                <label className="flex min-w-0 max-w-3xl flex-col gap-1.5">
                  <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                    Tables
                    <span className="rounded bg-cream px-1.5 py-0.5 text-[10.5px] font-semibold normal-case tracking-normal text-ink-soft">
                      {filteredPreviewTables.length}
                    </span>
                  </span>
                  <select
                    className="w-full rounded-md border border-line-strong bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-teal"
                    value={previewSelected?._uid || ''}
                    onChange={(e) => selectPreviewTable(e.target.value)}
                  >
                    {filteredPreviewTables.map((t) => {
                      const status = previewReviewStatus(t, savedIds)
                      const mark = status === 'fix' ? '⚠ Needs fixing — ' : status === 'ai' ? '✦ AI review — ' : ''
                      return (
                        <option key={t._uid} value={t._uid}>
                          {mark}{tablePickerLabel(t)}
                        </option>
                      )
                    })}
                  </select>
                </label>
              ) : (
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Tables</span>
                  {filteredPreviewTables.map((t) => {
                    const status = previewReviewStatus(t, savedIds)
                    const active = t._uid === previewSelected?._uid
                    return (
                      <button
                        key={t._uid}
                        type="button"
                        className={`inline-flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-left transition-colors duration-dhara ease-dhara ${
                          active
                            ? 'border-teal/40 bg-sage text-teal-deep'
                            : 'border-line bg-white text-ink hover:border-teal/40 hover:bg-sage'
                        }`}
                        onClick={() => selectPreviewTable(t._uid)}
                        title={
                          status === 'fix'
                            ? `${t.id} — Needs fixing`
                            : status === 'ai'
                              ? `${t.id} — AI filled — please review`
                              : `${t.id} — Reviewed`
                        }
                      >
                        <span
                          className={`h-2.5 w-2.5 flex-none rounded-[3px] ${
                            status === 'fix'
                              ? 'bg-coral'
                              : status === 'ai'
                                ? 'bg-[#2F6FED]'
                                : 'bg-green'
                          }`}
                          aria-hidden
                        />
                        <span className={`font-sans text-xs font-medium ${active ? 'text-teal-deep' : 'text-ink'}`}>
                          {tableCode(t)}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {previewSelected && filteredPreviewTables.some((t) => t._uid === previewSelected._uid) && (
              <TableViewer
                table={previewSelected}
                compact
                onUpdateId={(nextId) => updatePreviewTableId(previewSelected._uid, nextId)}
              />
            )}
            <ReconcileIds
              tables={batchAllTables}
              scopeTables={visiblePreviewTables}
              visibleId={
                filteredPreviewTables.some((t) => t._uid === previewSelected?._uid)
                  ? previewSelected?._uid
                  : filteredPreviewTables[0]?._uid
              }
              onContinue={applyReconcile}
              onNavigate={selectPreviewTable}
              onSave={markTableSaved}
              savedIds={savedIds}
            />
          </div>
        )}

        {step === 3 && matchResult && (
          <GroupingWorkspace
            matchResult={matchResult}
            onMatchResultChange={setMatchResult}
            manualGrouping={manualGrouping}
            onManualGroupingChange={setManualGrouping}
            editingGroups={editingGroups}
            onEditingGroupsChange={setEditingGroups}
            autoSnapshot={autoMatchResultRef.current}
            onRequestAutomatic={handleRequestAutomatic}
            onContinueToMetadata={requestContinueToMetadata}
            metadataFilling={metadataFilling}
            toast={groupingToast}
            onDismissToast={() => setGroupingToast(null)}
          />
        )}

        <PostPreviewLaterSteps
          step={step}
          matchResult={matchResult}
          metadataFiles={metadataFiles}
          metadataStarted={metadataStarted}
          metaLabel={metaLabel}
          metadataId={metadataId}
          metadataIds={metadataIds}
          datasetLabel="This dataset"
          hasKey={hasKey}
          onBackToGrouping={() => setStep(3)}
          onMetadataDone={(label, ids) => {
            setMetaLabel(label || 'this release')
            setMetadataIds(ids || [])
            setMetadataId((ids && ids[0]) || null)
            setPendingGroups(null)
            setStatusPage({
              ...STATUS_TRANSITIONS.metadataToClassify,
              key: 'metadataToClassify',
              msPerStep: 550,
              after: () => {
                setStatusPage(null)
                setStep(5)
              },
            })
          }}
          onClassifyPhaseChange={(next) => {
            if (next === 'harmonisation') setStep(6)
            else setStep(5)
          }}
          onClassificationCompleteChange={setClassificationComplete}
          onRegisterGoToHarmonisation={(fn) => { goToHarmRef.current = fn }}
          classificationComplete={classificationComplete}
          onClassifyContinue={publishFromClassify}
          onGoSettings={onGoSettings}
          onGoDashboard={onGoDashboard}
          onGoCatalogue={onGoCatalogue}
          onUploadAnother={onUploadAnother}
          onMatchResultChange={setMatchResult}
        />

        </div>
        </div>
      </div>
    </div>
  )
}
