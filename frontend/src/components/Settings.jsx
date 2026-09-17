'use client'

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Clock } from 'lucide-react'
import Button from './ui/Button'
import { METADATA_COLUMNS } from './console/MetadataSheetGrid'
import {
  getDatasetIdConfig,
  setDatasetIdConfig as persistDatasetIdConfig,
  getMetadataRequiredFields,
  setMetadataRequiredFields as persistMetadataRequiredFields,
  getMetadataStandard,
  setMetadataStandard as persistMetadataStandard,
  METADATA_STANDARD_OPTIONS,
  STATISTICS_OPTIONS,
} from '../lib/settingsConfig'
import { SDG_CONCEPT_TEMPLATE } from '../lib/sdgConcepts'
import { withAuthHeaders } from '../lib/auth'
import FileUpload from './FileUpload'

const PROVIDERS = [
  { value: 'openai', label: 'MEITY-empanelled LLM' },
  { value: 'self-hosted', label: 'Self-hosted' },
]
const ROLES = ['Administrator', 'Data Steward', 'Data User']

const SETTINGS_METADATA_FIELDS = [
  ...METADATA_COLUMNS.map((c) => ({
    key: c.key,
    label: c.label,
    title: `Require ${c.label.toLowerCase()}`,
    desc: `Metadata sheet field “${c.label}” must be filled before submission.`,
  })),
  {
    key: 'owner',
    label: 'Owner',
    title: 'Require owner',
    desc: 'Datasets must be assigned an owner/department.',
  },
  {
    key: 'autoTagDomain',
    label: 'Tag domain',
    title: 'Auto-tag domain',
    desc: 'Automatically infer and tag the data domain from content.',
  },
]

const CONFIG_TABS = [
  { key: 'dataset', label: 'Dataset ID configuration' },
  { key: 'metadata', label: 'Metadata configuration' },
  { key: 'classification', label: 'Classification code configuration' },
]

function defaultNameFromFile(file) {
  if (!file?.name) return ''
  return file.name.replace(/\.csv$/i, '').replace(/[_-]+/g, ' ').trim()
}

// Mock LLM provider/key form + user info form. No persistence backend today
// — `keySaved` is local state only, matching the mockup.
export default function Settings({ settings, onSettingsChange, keySaved, onSaveKey, user, onUserChange }) {
  const [local, setLocal] = useState(settings)
  const [standards, setStandards] = useState([])
  const [standardsLoading, setStandardsLoading] = useState(false)
  const [standardsError, setStandardsError] = useState('')
  const [standardsBusy, setStandardsBusy] = useState(false)
  const [addingStandard, setAddingStandard] = useState(false)
  const [pendingFile, setPendingFile] = useState(null)
  const [pendingName, setPendingName] = useState('')
  const [activeTab, setActiveTab] = useState('dataset')
  const [datasetIdConfig, setDatasetIdConfig] = useState(getDatasetIdConfig)
  const [savedDatasetIdConfig, setSavedDatasetIdConfig] = useState(getDatasetIdConfig)
  const [extraRequiredFields, setExtraRequiredFields] = useState(getMetadataRequiredFields)
  const [savedRequiredFields, setSavedRequiredFields] = useState(getMetadataRequiredFields)
  const [metadataStandard, setMetadataStandard] = useState(getMetadataStandard)
  const [savedMetadataStandard, setSavedMetadataStandard] = useState(getMetadataStandard)
  const [pickingFields, setPickingFields] = useState(false)

  const setDatasetIdField = (key) => (e) => setDatasetIdConfig((prev) => ({ ...prev, [key]: e.target.value }))

  const setField = (key) => (e) => {
    const next = { ...local, [key]: e.target.value }
    setLocal(next)
    onSettingsChange(next)
  }
  const setUserField = (key) => (e) => onUserChange({ ...user, [key]: e.target.value })

  const status = keySaved ? 'Key saved' : local.apiKey ? 'Unsaved changes' : 'No key configured'
  const statusClass = keySaved ? 'settings-key-status-ok' : local.apiKey ? 'settings-key-status-warn' : 'settings-key-status-none'

  const datasetIdDirty = JSON.stringify(datasetIdConfig) !== JSON.stringify(savedDatasetIdConfig)
  const requiredFieldsDirty = JSON.stringify(extraRequiredFields) !== JSON.stringify(savedRequiredFields)
  const metadataStandardDirty = metadataStandard !== savedMetadataStandard
  const metadataConfigDirty = requiredFieldsDirty || metadataStandardDirty
  const pendingDirty = Boolean(pendingFile && pendingName.trim())

  const loadStandards = useCallback(async () => {
    setStandardsLoading(true)
    setStandardsError('')
    try {
      const res = await fetch('/api/catalogue/classification-standards', withAuthHeaders())
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Failed to load classification standards')
      setStandards(Array.isArray(data.standards) ? data.standards : [])
    } catch (err) {
      setStandardsError(err.message || 'Failed to load classification standards')
    } finally {
      setStandardsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'classification') loadStandards()
  }, [activeTab, loadStandards])

  const saveDatasetIdConfig = () => {
    persistDatasetIdConfig(datasetIdConfig)
    setSavedDatasetIdConfig(datasetIdConfig)
  }

  const saveMetadataConfig = () => {
    persistMetadataRequiredFields(extraRequiredFields)
    setSavedRequiredFields(extraRequiredFields)
    persistMetadataStandard(metadataStandard)
    setSavedMetadataStandard(metadataStandard)
  }

  const resetPendingUpload = () => {
    setPendingFile(null)
    setPendingName('')
    setAddingStandard(false)
  }

  const saveClassificationStandard = async () => {
    if (!pendingFile || !pendingName.trim()) return
    setStandardsBusy(true)
    setStandardsError('')
    try {
      const fd = new FormData()
      fd.append('name', pendingName.trim())
      fd.append('file', pendingFile)
      fd.append('select', 'true')
      const res = await fetch('/api/catalogue/classification-standards', withAuthHeaders({ method: 'POST', body: fd }))
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Upload failed')
      resetPendingUpload()
      await loadStandards()
    } catch (err) {
      setStandardsError(err.message || 'Upload failed')
    } finally {
      setStandardsBusy(false)
    }
  }

  const selectStandard = async (id) => {
    setStandardsBusy(true)
    setStandardsError('')
    try {
      const res = await fetch(
        `/api/catalogue/classification-standards/${id}/select`,
        withAuthHeaders({ method: 'POST' }),
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Could not select standard')
      await loadStandards()
    } catch (err) {
      setStandardsError(err.message || 'Could not select standard')
    } finally {
      setStandardsBusy(false)
    }
  }

  const removeStandard = async (id) => {
    setStandardsBusy(true)
    setStandardsError('')
    try {
      const res = await fetch(
        `/api/catalogue/classification-standards/${id}`,
        withAuthHeaders({ method: 'DELETE' }),
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Could not delete standard')
      await loadStandards()
    } catch (err) {
      setStandardsError(err.message || 'Could not delete standard')
    } finally {
      setStandardsBusy(false)
    }
  }

  const inputClass =
    'h-10 rounded-xl border border-line-strong bg-surface px-3 font-body text-[14.5px] text-ink transition-all duration-dhara ease-dhara outline-none focus:border-teal focus:shadow-focus-ring'
  const fieldLabelClass = 'text-[13px] font-medium text-ink'
  const statusToneClass = { ok: 'text-[13px] text-green', warn: 'text-[13px] text-yellow', none: 'text-[13px] text-ink-muted' }

  return (
    <div className="flex w-full flex-col gap-7">
      <div className="flex flex-col gap-1.5">
        <div className="dhara-page-title">Settings</div>
      </div>

      <div className="flex flex-col gap-[18px] rounded-2xl border border-line/90 bg-surface p-6">
        <div className="text-[16px] font-semibold tracking-tight text-ink">MEITY-empanelled LLM</div>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Provider</label>
            <select className={inputClass} value={local.provider} onChange={setField('provider')}>
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>API key</label>
            <input className={inputClass} type="password" value={local.apiKey} onChange={setField('apiKey')} placeholder="MEITY-empanelled API key" />
          </div>
        </div>
        <div className="flex items-center gap-3.5">
          <Button onClick={onSaveKey}>Save key</Button>
          <span className={statusClass === 'settings-key-status-ok' ? statusToneClass.ok : statusClass === 'settings-key-status-warn' ? statusToneClass.warn : statusToneClass.none}>{status}</span>
        </div>
      </div>

      <div className="flex flex-col gap-[18px] rounded-2xl border border-line/90 bg-surface p-6">
        <div className="flex gap-2" role="tablist" aria-label="Configuration sections">
          {CONFIG_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={activeTab === t.key}
              className={`dhara-tab h-9 min-w-0 flex-1 rounded-xl px-3 text-sm font-semibold ${
                activeTab === t.key
                  ? 'border-transparent bg-teal-deep text-cream shadow-sm'
                  : 'border-line bg-mist text-ink-soft hover:bg-sage hover:text-teal-deep'
              }`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div key={activeTab} className="dhara-tab-panel flex flex-col gap-[18px]" role="tabpanel">
        {activeTab === 'dataset' && (
          <>
            <div className="-mt-2.5 text-sm text-ink-soft">Controls how new dataset IDs are generated.</div>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className={fieldLabelClass}>Prefix</label>
                <input
                  className={inputClass}
                  type="text"
                  value={datasetIdConfig.prefix}
                  onChange={setDatasetIdField('prefix')}
                  placeholder="DDI_DES_DEL"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={fieldLabelClass}>Separator</label>
                <input
                  className={inputClass}
                  type="text"
                  value={datasetIdConfig.separator}
                  onChange={setDatasetIdField('separator')}
                  placeholder="_"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className={fieldLabelClass}>Statistics</label>
                <select
                  className={inputClass}
                  value={datasetIdConfig.statistics}
                  onChange={setDatasetIdField('statistics')}
                >
                  {STATISTICS_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3.5">
              <Button disabled={!datasetIdDirty} onClick={saveDatasetIdConfig}>Save configuration</Button>
              <span className={datasetIdDirty ? statusToneClass.warn : statusToneClass.ok}>
                {datasetIdDirty ? 'Unsaved changes' : 'Configuration saved'}
              </span>
            </div>
          </>
        )}

        {activeTab === 'metadata' && (
          <>
            <div className="-mt-2.5 text-sm text-ink-soft">Choose the metadata standard and which fields are required when a dataset is submitted.</div>
            <div className="flex flex-col gap-2.5">
              <div className="flex flex-col gap-0.5">
                <label className={fieldLabelClass}>Metadata standard</label>
                <div className="text-[13px] text-ink-soft">
                  Determines which metadata schema is used when filling dataset metadata.
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {METADATA_STANDARD_OPTIONS.map((opt) => {
                  const selected = metadataStandard === opt.value
                  const blurb = opt.value === 'sdg'
                    ? 'UN SDG indicator fields for goals, targets, and custodians.'
                    : 'National metadata sheet fields for catalogue publication.'
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setMetadataStandard(opt.value)}
                      className={`dhara-tab group flex flex-col gap-2 rounded-2xl px-4 py-3.5 text-left ${
                        selected
                          ? 'border-transparent bg-teal-deep text-cream'
                          : 'border-line bg-white text-ink hover:bg-sage hover:text-teal-deep'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className={`text-[14.5px] font-semibold tracking-tight ${selected ? 'text-cream' : 'text-ink group-hover:text-teal-deep'}`}>
                          {opt.label}
                        </span>
                        <span
                          className={`flex h-5 w-5 flex-none items-center justify-center rounded-full border transition-colors duration-[420ms] ${
                            selected
                              ? 'border-cream/40 bg-cream/20 text-cream'
                              : 'border-line bg-white text-transparent group-hover:border-teal/40 group-hover:bg-teal-deep group-hover:text-cream'
                          }`}
                          aria-hidden
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2.25} />
                        </span>
                      </div>
                      <span className={`text-[12.5px] leading-snug ${selected ? 'text-cream/80' : 'text-ink-soft group-hover:text-teal-deep/80'}`}>
                        {blurb}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            <div key={metadataStandard} className="dhara-tab-panel flex flex-col gap-[18px]">
            {metadataStandard === 'sdg' ? (
              <>
                <div className="text-[13px] font-semibold text-ink">Indicator information (SDG_INDICATOR_INFO)</div>
                <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-white">
                  {SDG_CONCEPT_TEMPLATE.filter((row) => !row.section).map((row) => (
                    <div className="flex cursor-default select-text items-start gap-3 border-b border-line bg-white px-4 py-3.5 last:border-b-0" key={row.code}>
                      <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-green" strokeWidth={1.75} />
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <div className="text-[15px] font-semibold text-ink">
                          {row.concept}{' '}
                          <span className="text-[13px] font-medium text-ink-soft">({row.code})</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="text-[13px] text-ink-soft">
                  These SDG indicator fields are filled in Batch Review and saved with each catalogue push.
                </div>
              </>
            ) : (
              <>
            <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-white">
              {Object.keys(extraRequiredFields).length === 0 && (
                <div className="flex cursor-default select-text items-start gap-3 border-b border-line bg-white px-4 py-3.5 last:border-b-0">
                  <div className="flex flex-1 flex-col gap-0.5">
                    <div className="text-[13px] text-ink-soft">No required fields. Add fields from the metadata sheet below.</div>
                  </div>
                </div>
              )}
              {Object.keys(extraRequiredFields).map((key) => {
                const field = SETTINGS_METADATA_FIELDS.find((c) => c.key === key)
                if (!field) return null
                return (
                  <div className="flex cursor-default select-text items-start gap-3 border-b border-line bg-white px-4 py-3.5 last:border-b-0" key={key}>
                    <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-green" strokeWidth={1.75} />
                    <div className="flex flex-1 flex-col gap-0.5">
                      <div className="text-[15px] font-semibold text-ink">{field.title}</div>
                      <div className="text-[13px] text-ink-soft">{field.desc}</div>
                    </div>
                    <input
                      type="checkbox"
                      className="mt-1.5 h-[15px] w-[15px] flex-none accent-teal"
                      checked={extraRequiredFields[key]}
                      onChange={() => setExtraRequiredFields((prev) => ({ ...prev, [key]: !prev[key] }))}
                    />
                    <button
                      type="button"
                      className="flex-none rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-ink-soft transition-colors hover:border-coral hover:text-coral"
                      onClick={() => setExtraRequiredFields((prev) => {
                        const next = { ...prev }
                        delete next[key]
                        return next
                      })}
                    >
                      Remove
                    </button>
                  </div>
                )
              })}
            </div>
            {(() => {
              const available = SETTINGS_METADATA_FIELDS.filter((c) => extraRequiredFields[c.key] === undefined)
              return (
                <>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="inline-flex h-10 items-center rounded-lg border border-teal bg-white px-4 text-sm font-semibold text-teal transition-colors duration-200 hover:bg-sage disabled:cursor-default disabled:opacity-45"
                      disabled={!available.length}
                      onClick={() => setPickingFields((open) => !open)}
                    >
                      {pickingFields ? 'Hide metadata sheet fields' : '+ Add required field'}
                    </button>
                  </div>
                  {pickingFields && available.length > 0 && (
                    <div className="flex flex-col gap-2.5 rounded-lg border border-line bg-white px-4 py-3">
                      <div className="text-[13px] text-ink-soft">
                        Fields from the metadata sheet. Choose one to require it on submission.
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {available.map((c) => (
                          <button
                            type="button"
                            key={c.key}
                            className="h-8 rounded-full border border-line bg-mist px-3 text-[13px] font-semibold text-ink transition-colors hover:bg-sage hover:text-teal-deep"
                            onClick={() => {
                              setExtraRequiredFields((prev) => ({ ...prev, [c.key]: true }))
                              if (available.length <= 1) setPickingFields(false)
                            }}
                          >
                            {c.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )
            })()}
              </>
            )}
            </div>
            <div className="flex items-center gap-3.5">
              <Button disabled={!metadataConfigDirty} onClick={saveMetadataConfig}>Save configuration</Button>
              <span className={metadataConfigDirty ? statusToneClass.warn : statusToneClass.ok}>
                {metadataConfigDirty ? 'Unsaved changes' : 'Configuration saved'}
              </span>
            </div>
          </>
        )}

        {activeTab === 'classification' && (
          <>
            <div className="-mt-2.5 text-sm text-ink-soft">
              Upload a CSV, give it a name, then select which standard Classify should use for occupation suggestions.
              Columns must match the NCO layout (see <code className="text-[12px]">nco_2015_concordance.csv.example</code>).
            </div>

            <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-white">
              {standardsLoading && standards.length === 0 && (
                <div className="px-4 py-3.5 text-[13px] text-ink-soft">Loading standards…</div>
              )}
              {!standardsLoading && standards.length === 0 && !pendingFile && (
                <div className="px-4 py-3.5 text-[13px] text-ink-soft">
                  No classification standards yet. Upload a CSV to enable occupation matching.
                </div>
              )}
              {standards.map((s) => {
                const selected = Boolean(s.is_selected)
                return (
                  <div
                    key={s.id}
                    className={`flex items-start gap-3 border-b border-line px-4 py-3.5 last:border-b-0 ${
                      selected ? 'bg-sage/40' : 'bg-white'
                    }`}
                  >
                    <button
                      type="button"
                      className={`mt-0.5 flex h-5 w-5 flex-none items-center justify-center rounded-full border transition-colors disabled:cursor-default ${
                        selected
                          ? 'border-transparent bg-green text-white'
                          : 'border-line bg-white text-transparent hover:border-teal'
                      }`}
                      aria-pressed={selected}
                      aria-label={selected ? `${s.name} selected` : `Use ${s.name} for classification`}
                      disabled={standardsBusy || selected}
                      onClick={() => selectStandard(s.id)}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2.25} />
                    </button>
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <div className="text-[15px] font-semibold text-ink">{s.name}</div>
                      <div className="text-[13px] text-ink-soft">
                        {selected ? 'Selected for classification. ' : 'Click the check to use this for classification. '}
                        {(s.row_count ?? 0).toLocaleString()} codes
                        {s.original_filename ? ` · ${s.original_filename}` : ''}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="flex-none rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-ink-soft transition-colors hover:border-coral hover:text-coral disabled:opacity-45"
                      disabled={standardsBusy}
                      onClick={() => removeStandard(s.id)}
                    >
                      Remove
                    </button>
                  </div>
                )
              })}

              {pendingFile && (
                <div className="flex cursor-default select-text items-start gap-3 border-b border-line bg-[#fffaf1] px-4 py-3.5 last:border-b-0">
                  <Clock className="mt-0.5 h-4 w-4 flex-none text-yellow" strokeWidth={1.75} />
                  <div className="flex flex-1 flex-col gap-0.5">
                    <div className="text-[15px] font-semibold text-ink">{pendingName || pendingFile.name}</div>
                    <div className="text-[13px] text-ink-soft">
                      Not yet saved — name it below and click &quot;Save configuration&quot; to load into Postgres.
                    </div>
                  </div>
                </div>
              )}
            </div>

            {addingStandard || pendingFile ? (
              <div className="flex flex-col gap-3 rounded-lg border border-line bg-white px-4 py-3.5">
                <div className="text-[13px] font-semibold text-ink">New classification standard</div>
                <div className="flex flex-col gap-1.5">
                  <label className={fieldLabelClass}>Name</label>
                  <input
                    className={inputClass}
                    type="text"
                    value={pendingName}
                    onChange={(e) => setPendingName(e.target.value)}
                    placeholder="e.g. National Classification of Occupations (NCO 2015)"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className={fieldLabelClass}>Upload file</label>
                  <FileUpload
                    compact
                    accept=".csv,text/csv"
                    extensionRegex={/\.csv$/i}
                    label="Drop your file here"
                    hint="CSV — drag and drop or browse"
                    selectedName={pendingFile?.name}
                    loading={standardsBusy}
                    onUpload={(file) => {
                      setPendingFile(file)
                      setPendingName((prev) => prev.trim() || defaultNameFromFile(file))
                    }}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button disabled={!pendingDirty || standardsBusy} onClick={saveClassificationStandard}>
                    {standardsBusy ? 'Saving…' : 'Save configuration'}
                  </Button>
                  <button
                    type="button"
                    className="text-[13px] font-semibold text-ink-soft hover:text-ink"
                    disabled={standardsBusy}
                    onClick={resetPendingUpload}
                  >
                    Cancel
                  </button>
                  <span className={pendingDirty ? statusToneClass.warn : statusToneClass.ok}>
                    {pendingDirty ? 'Unsaved changes' : 'Name the standard and upload a file'}
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="inline-flex h-10 cursor-pointer items-center rounded-lg border border-teal bg-white px-4 text-sm font-semibold text-teal transition-colors duration-200 hover:bg-sage"
                  onClick={() => setAddingStandard(true)}
                >
                  + Add classification standard
                </button>
                {!standardsLoading && standards.length > 0 && (
                  <span className={statusToneClass.ok}>
                    {standards.some((s) => s.is_selected) ? 'Active standard saved in Postgres' : 'Select a standard to use for Classify'}
                  </span>
                )}
              </div>
            )}

            {standardsError && (
              <div className="text-[13px] text-coral">{standardsError}</div>
            )}
          </>
        )}
        </div>
      </div>

      <div className="flex flex-col gap-[18px] rounded-2xl border border-line/90 bg-surface p-6">
        <div className="text-[16px] font-semibold tracking-tight text-ink">User information</div>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Name</label>
            <input className={inputClass} type="text" value={user.name} onChange={setUserField('name')} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Role</label>
            <select className={inputClass} value={user.role} onChange={setUserField('role')}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Email</label>
            <input className={inputClass} type="email" value={user.email} onChange={setUserField('email')} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Department</label>
            <input className={inputClass} type="text" value={user.dept} onChange={setUserField('dept')} />
          </div>
        </div>
      </div>
    </div>
  )
}
