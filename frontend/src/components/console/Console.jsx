'use client'

import { AlertTriangle, ArrowLeft, Check, Sparkles } from 'lucide-react'
import KydsSummaryCard from '../KydsSummaryCard'
import TableViewer from '../TableViewer'
import BatchUpload from './BatchUpload'
import SqlUpload from './SqlUpload'
import ReconcileIds from './ReconcileIds'
import GroupingWorkspace from './GroupingWorkspace'
import PostPreviewLaterSteps from './PostPreviewLaterSteps'
import ConsoleStatusPlaceholder from './ConsoleStatusPlaceholder'
import { StageSidebar } from './ConsoleStages'
import { tableCode, tablePickerLabel } from '../../lib/postPreview'
import { UploadChoice, BACK_LABELS } from './ConsoleUploadChoice'
import { useConsolePipeline } from './useConsolePipeline'

export default function Console({ hasKey, onGoSettings, onGoDashboard, onGoCatalogue, onUploadAnother }) {
  const {
    STATUS_TRANSITIONS,
    addStep1MetadataFiles,
    applyReconcile,
    autoMatchResultRef,
    back,
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
    matchResult,
    maxStepReached,
    metaLabel,
    metadataFiles,
    metadataFilling,
    metadataId,
    metadataIds,
    metadataStarted,
    mismatchedPreviewTables,
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
    removeStep1MetadataFile,
    requestContinueToMetadata,
    resetUploadChoice,
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

  return (
    <div className="flex flex-col gap-5">
      <StageSidebar
        stageIdx={stageIdx}
        step={step}
        maxStepReached={maxStepReached}
        expandedStage={expandedStage}
        setExpandedStage={setExpandedStage}
        goToStep={goToStep}
      />

      <div key={step} className="dhara-page-enter flex min-w-0 flex-1 flex-col gap-[18px]">
        {/* Page header — title / purpose stay above the content panel */}
        {!statusPage && (
        <div className="flex flex-col">
          {step > 1 && step < 6 && (
            <div className="mb-3.5 inline-flex cursor-pointer items-center gap-1.5 text-[14px] font-medium text-teal transition-colors duration-dhara ease-dhara hover:text-teal-dark" onClick={back}>
              <ArrowLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden />
              {BACK_LABELS[step]}
            </div>
          )}
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="dhara-page-title">{info.title}</div>
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
            <UploadChoice
              choice={uploadChoice}
              onChoose={setUploadChoice}
              onDatasetFile={handleDatasetFile}
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
            {uploadChoice === 'xlsx' && (
              <>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 self-start text-[13px] font-semibold text-teal hover:text-teal-dark"
                  onClick={resetUploadChoice}
                >
                  <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                  Back to file upload
                </button>
                <BatchUpload
                  onMatched={handleMatched}
                  initialDatasetFiles={pendingDatasetFiles}
                  metadataFiles={step1MetadataFiles}
                  onMetadataFilesChange={setStep1MetadataFiles}
                  hideMetadataSection
                />
              </>
            )}
          </div>
        )}

        {step === 2 && previewTables.length > 0 && (
          <div className="flex flex-col gap-5">
            {previewDatasets.length > 1 && (
              <div className="flex flex-wrap items-center gap-2">
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
            {(unsavedMismatched.length > 0 || unsavedAiFilled.length > 0) && (
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                {unsavedMismatched.length > 0 && (
                  <div className="flex-1 rounded-lg border border-coral/40 bg-error-bg px-4 py-3 text-sm font-medium text-ink">
                    <span className="inline-flex items-start gap-1.5">
                      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-coral" strokeWidth={2} aria-hidden />
                      <span>
                        <span className="font-semibold text-coral">Needs fixing:</span>{' '}
                        {unsavedMismatched.length} of {mismatchedPreviewTables.length} table{mismatchedPreviewTables.length !== 1 ? 's' : ''} still need correcting & saving.
                      </span>
                    </span>
                  </div>
                )}
                {unsavedAiFilled.length > 0 && (
                  <div className="flex-1 rounded-lg border border-[#5B8DEF]/45 bg-[#EEF4FF] px-4 py-3 text-sm font-medium text-ink">
                    <span className="inline-flex items-start gap-1.5">
                      <Sparkles className="mt-0.5 h-4 w-4 flex-none text-[#2F6FED]" strokeWidth={2} aria-hidden />
                      <span>
                        <span className="font-semibold text-[#2F6FED]">AI review:</span>{' '}
                        {unsavedAiFilled.length} table{unsavedAiFilled.length !== 1 ? 's' : ''} had Source Table ID / Title filled by AI — confirm they look right.
                      </span>
                    </span>
                  </div>
                )}
              </div>
            )}
            {mismatchedPreviewTables.length > 0 && unsavedMismatched.length === 0 && (
              <div className="rounded-lg border border-green bg-sage px-4 py-3 text-sm font-medium text-teal">
                <span className="inline-flex items-start gap-1.5">
                  <Check className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2.5} aria-hidden />
                  All {mismatchedPreviewTables.length} flagged table{mismatchedPreviewTables.length !== 1 ? 's' : ''} saved.
                </span>
              </div>
            )}

            {(unsavedMismatched.length > 0 || unsavedAiFilled.length > 0 || previewReviewFilter !== 'all') && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Show</span>
                {[
                  { id: 'all', label: 'All', count: visiblePreviewTables.length, activeClass: 'bg-teal-deep text-cream' },
                  { id: 'fix', label: 'Needs fixing', count: unsavedMismatched.length, activeClass: 'bg-coral text-white', idleClass: 'border-coral/35 text-coral hover:bg-error-bg' },
                  { id: 'ai', label: 'AI review', count: unsavedAiFilled.length, activeClass: 'bg-[#2F6FED] text-white', idleClass: 'border-[#5B8DEF]/40 text-[#2F6FED] hover:bg-[#EEF4FF]' },
                  { id: 'ok', label: 'Reviewed / OK', count: okPreviewCount, activeClass: 'bg-green text-white', idleClass: 'border-green/40 text-green hover:bg-sage' },
                ].map((f) => (
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
            )}

            {filteredPreviewTables.length === 0 ? (
              <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-soft">
                No tables in this filter. Choose another status above.
              </div>
            ) : filteredPreviewTables.length > 10 ? (
              <label className="flex min-w-0 max-w-3xl flex-col gap-1.5">
                <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  Table
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
                {filteredPreviewTables.map((t) => {
                  const status = previewReviewStatus(t, savedIds)
                  const active = t._uid === previewSelected?._uid
                  return (
                    <div
                      key={t._uid}
                      className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition-colors duration-dhara ease-dhara ${
                        active
                          ? 'border-transparent bg-teal-deep'
                          : status === 'fix'
                            ? 'border-coral/50 bg-error-bg ring-1 ring-coral/30 hover:border-coral'
                            : status === 'ai'
                              ? 'border-[#5B8DEF]/50 bg-[#EEF4FF] ring-1 ring-[#5B8DEF]/25 hover:border-[#2F6FED]'
                              : 'border-green bg-sage hover:border-teal/35'
                      }`}
                      onClick={() => selectPreviewTable(t._uid)}
                      title={
                        status === 'fix'
                          ? `${t.id} — Needs fixing`
                          : status === 'ai'
                            ? `${t.id} — AI filled — please review`
                            : `${t.id} — Reviewed / OK`
                      }
                    >
                      <span className={`flex h-4.5 w-4.5 items-center justify-center rounded-full ${
                        active
                          ? 'bg-cream/20 text-cream'
                          : status === 'fix'
                            ? 'bg-coral text-white'
                            : status === 'ai'
                              ? 'bg-[#2F6FED] text-white'
                              : 'bg-green text-white'
                      }`}>
                        {status === 'fix' ? (
                          <AlertTriangle className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
                        ) : status === 'ai' ? (
                          <Sparkles className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
                        ) : (
                          <Check className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
                        )}
                      </span>
                      <span className={`font-sans text-xs font-medium ${active ? 'text-cream' : 'text-ink'}`}>{tableCode(t)}</span>
                      <span className={`text-[10.5px] font-semibold uppercase tracking-wide ${
                        active
                          ? 'text-cream/70'
                          : status === 'fix'
                            ? 'text-coral'
                            : status === 'ai'
                              ? 'text-[#2F6FED]'
                              : 'text-ink-soft'
                      }`}>
                        {status === 'fix' ? 'Fix' : status === 'ai' ? 'AI' : 'OK'}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
            {previewSelected && filteredPreviewTables.some((t) => t._uid === previewSelected._uid) && (
              <TableViewer table={previewSelected} compact />
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
          onClassifyContinue={publishFromClassify}
          onGoSettings={onGoSettings}
          onGoDashboard={onGoDashboard}
          onGoCatalogue={onGoCatalogue}
          onUploadAnother={onUploadAnother}
        />

        </div>
        </div>
      </div>
    </div>
  )
}
