import FileUpload from './FileUpload'
import NmdsConceptFields from './NmdsConceptFields'
import { nmdsFieldsToList } from '../nmdsConcepts'

// Per-metadata-group NMDS concept metadata: the same upload box that used
// to sit at the top of the standalone NMDS step, now shown right below
// each group's card in the carousel. Uploading (or the "View / edit
// fields" link) opens a modal with the same topic-by-topic field editor —
// the parsing/mismatch logic and the field set are untouched, only where
// they're shown has changed.
export default function NmdsGroupPanel({
  fields,
  onFieldChange,
  onFileSelected,
  file,
  appliedFrom,
  parsing,
  parseError,
  fileMismatch,
  modalOpen,
  onOpenModal,
  onCloseModal,
  groupLabel,
  onSaveGroup,
  onApplyToAll,
  canApplyToAll,
  appliedToAll,
}) {
  const filledCount = nmdsFieldsToList(fields).length
  const prefilledHint = appliedFrom?.fileName || (appliedFrom ? 'Fields filled in' : null)

  return (
    <div className="push-section nmds-group-panel">
      <div className="push-section-title">Upload NMDS concept metadata *</div>
      <FileUpload
        onUpload={onFileSelected}
        label="Add NMDS concept metadata file"
        hint="XLSX or CSV — prefills the topics below"
        selectedName={file?.name || prefilledHint}
        accept=".xlsx,.xls,.csv"
        extensionRegex={/\.(xlsx|xls|csv)$/i}
        compact
      />
      {canApplyToAll && (
        <label className="nmds-apply-all">
          <input
            type="checkbox"
            checked={!!appliedToAll}
            disabled={filledCount === 0}
            onChange={(e) => {
              if (e.target.checked) onApplyToAll?.()
            }}
          />
          <span>Apply to all</span>
        </label>
      )}
      {(file || appliedFrom) && (
        <div className="push-excel-row">
          {!parsing && !parseError && !fileMismatch && file && (
            <div className="push-file-name">{file.name} — fields filled in, click below to review</div>
          )}
          {!parsing && !parseError && !fileMismatch && !file && appliedFrom && (
            <div className="push-file-name">
              {appliedFrom.fileName
                ? `${appliedFrom.fileName} — fields filled in, click below to review`
                : 'Fields filled in, click below to review'}
            </div>
          )}
          {parsing && <div className="push-file-status">Reading concept metadata from {file.name}…</div>}
          {parseError && (
            <div className="push-file-error">
              Couldn't auto-fill from {file.name}: {parseError}. You can still fill the fields in manually.
            </div>
          )}
          {!parsing && !parseError && fileMismatch && (
            <div className="push-file-warning">
              ⚠ Couldn't match {file.name} against the known NMDS concepts — double-check you've uploaded the
              right file. You can still fill the fields in manually below.
            </div>
          )}
        </div>
      )}

      <div className="nmds-group-panel-actions">
        <button type="button" className="nmds-group-panel-view-btn" onClick={onOpenModal}>
          View / edit NMDS fields {filledCount > 0 && `(${filledCount} filled)`}
        </button>
        <button type="button" className="nmds-group-panel-save-btn" onClick={onSaveGroup}>
          Save
        </button>
      </div>

      {modalOpen && (
        <div className="kyds-overlay" role="dialog" aria-modal="true" aria-labelledby="nmds-modal-title">
          <div className="kyds-modal nmds-modal">
            <div className="kyds-header">
              <div>
                <div className="kyds-eyebrow">NMDS concept metadata</div>
                <div id="nmds-modal-title" className="kyds-title">{groupLabel}</div>
                {fileMismatch && !parsing && (
                  <div className="kyds-sub push-file-warning">
                    ⚠ Couldn't match the uploaded file against the known NMDS concepts — fields below are empty.
                    Kindly check the file or fill them in manually.
                  </div>
                )}
                {parseError && (
                  <div className="kyds-sub push-file-error">Couldn't auto-fill from the uploaded file: {parseError}.</div>
                )}
                {!fileMismatch && !parseError && (
                  <div className="kyds-sub">
                    {filledCount > 0 ? `${filledCount} field${filledCount !== 1 ? 's' : ''} filled in.` : 'The fields are autosaved, kindly fill in all the fields and proceed to next topic.'}
                  </div>
                )}
              </div>
              <button type="button" className="push-close" onClick={onCloseModal} aria-label="Close">×</button>
            </div>
            <div className="kyds-body">
              <div className="nmds-form">
                <NmdsConceptFields fields={fields} onFieldChange={onFieldChange} onSave={onCloseModal} />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
