'use client'

import { useState } from 'react'
import { CheckCircle2, Clock } from 'lucide-react'
import { METADATA_COLUMNS } from './MetadataSheetGrid'
import {
  getDatasetIdConfig,
  setDatasetIdConfig as persistDatasetIdConfig,
  getMetadataRequiredFields,
  setMetadataRequiredFields as persistMetadataRequiredFields,
  STATISTICS_OPTIONS,
} from '../lib/settingsConfig'

const PROVIDERS = ['Anthropic', 'OpenAI', 'Self-hosted']
const ROLES = ['Administrator', 'Data Steward', 'Data User']

const STANDARDS = [
  { key: 'nco', name: 'National Classification of Occupations (NCO 2015)', desc: 'Standard occupation codes used during harmonisation.' },
  { key: 'nic', name: 'National Industrial Classification (NIC 2008)', desc: 'Standard industry codes used during harmonisation.' },
]

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

// Mock LLM provider/key form + user info form. No persistence backend today
// — `keySaved` is local state only, matching the mockup.
export default function Settings({ settings, onSettingsChange, keySaved, onSaveKey, user, onUserChange }) {
  const [local, setLocal] = useState(settings)
  const [customStandards, setCustomStandards] = useState([]) // saved custom standards: [{ name }]
  const [pendingFile, setPendingFile] = useState(null) // just uploaded, not yet saved
  const [activeTab, setActiveTab] = useState('dataset')
  const [datasetIdConfig, setDatasetIdConfig] = useState(getDatasetIdConfig)
  const [savedDatasetIdConfig, setSavedDatasetIdConfig] = useState(getDatasetIdConfig)
  const [extraRequiredFields, setExtraRequiredFields] = useState(getMetadataRequiredFields)
  const [savedRequiredFields, setSavedRequiredFields] = useState(getMetadataRequiredFields)
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

  const saveDatasetIdConfig = () => {
    persistDatasetIdConfig(datasetIdConfig)
    setSavedDatasetIdConfig(datasetIdConfig)
  }

  const saveMetadataRequiredFields = () => {
    persistMetadataRequiredFields(extraRequiredFields)
    setSavedRequiredFields(extraRequiredFields)
  }

  const saveCustomStandard = () => {
    if (!pendingFile) return
    setCustomStandards((prev) => [...prev, { name: pendingFile.name }])
    setPendingFile(null)
  }

  const inputClass = 'h-[42px] rounded-md border border-[#ddd3c0] bg-white px-3 font-sans text-[15px] text-ink'
  const fieldLabelClass = 'text-[13px] font-semibold text-ink'
  const statusToneClass = { ok: 'text-[13px] text-[#3d7a3d]', warn: 'text-[13px] text-[#9a7413]', none: 'text-[13px] text-[#8E9398]' }

  return (
    <div className="flex max-w-[720px] flex-col gap-[22px]">
      <div className="flex flex-col gap-1.5">
        <div className="font-display text-4xl font-medium text-ink">Settings</div>
      </div>

      <div className="flex flex-col gap-[18px] rounded-lg border border-line bg-white p-6">
        <div className="text-lg font-semibold text-ink">LLM API key</div>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Provider</label>
            <select className={inputClass} value={local.provider} onChange={setField('provider')}>
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>API key</label>
            <input className={inputClass} type="password" value={local.apiKey} onChange={setField('apiKey')} placeholder="sk-..." />
          </div>
        </div>
        <div className="flex items-center gap-3.5">
          <button className="flex h-10 items-center rounded-md bg-teal px-[18px] text-[15px] font-semibold text-white transition-colors hover:bg-teal-dark" onClick={onSaveKey}>Save key</button>
          <span className={statusClass === 'settings-key-status-ok' ? statusToneClass.ok : statusClass === 'settings-key-status-warn' ? statusToneClass.warn : statusToneClass.none}>{status}</span>
        </div>
      </div>

      <div className="flex flex-col gap-[18px] rounded-lg border border-line bg-white p-6">
        <div className="flex flex-wrap gap-2">
          {CONFIG_TABS.map((t) => (
            <button
              key={t.key}
              className={`h-9 rounded-full border px-[18px] text-sm font-semibold transition-colors ${
                activeTab === t.key ? 'border-teal bg-teal text-white' : 'border-line bg-cream text-ink-soft hover:bg-sage hover:text-ink'
              }`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

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
              <button className="flex h-10 items-center rounded-md bg-teal px-[18px] text-[15px] font-semibold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]" disabled={!datasetIdDirty} onClick={saveDatasetIdConfig}>Save configuration</button>
              <span className={datasetIdDirty ? statusToneClass.warn : statusToneClass.ok}>
                {datasetIdDirty ? 'Unsaved changes' : 'Configuration saved'}
              </span>
            </div>
          </>
        )}

        {activeTab === 'metadata' && (
          <>
            <div className="-mt-2.5 text-sm text-ink-soft">Controls which metadata fields are required when a dataset is submitted.</div>
            <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-cream">
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
                    <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-[#3d7a3d]" strokeWidth={1.75} />
                    <div className="flex flex-1 flex-col gap-0.5">
                      <div className="text-[15px] font-semibold text-ink">{field.title}</div>
                      <div className="text-[13px] text-ink-soft">{field.desc}</div>
                    </div>
                    <input
                      type="checkbox"
                      checked={extraRequiredFields[key]}
                      onChange={() => setExtraRequiredFields((prev) => ({ ...prev, [key]: !prev[key] }))}
                    />
                    <button
                      type="button"
                      className="flex-none rounded-[5px] border border-line px-2.5 py-1 text-xs font-semibold text-ink-soft transition-colors hover:border-[#c45c4a] hover:text-[#c45c4a]"
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
                      className="inline-flex h-10 items-center rounded-md border border-teal bg-white px-4 text-sm font-semibold text-teal transition-colors hover:bg-sage disabled:cursor-default disabled:opacity-45"
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
                            className="h-8 rounded-full border border-line bg-cream px-3 text-[13px] font-semibold text-ink transition-colors hover:border-teal hover:bg-sage"
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
            <div className="flex items-center gap-3.5">
              <button className="flex h-10 items-center rounded-md bg-teal px-[18px] text-[15px] font-semibold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]" disabled={!requiredFieldsDirty} onClick={saveMetadataRequiredFields}>Save configuration</button>
              <span className={requiredFieldsDirty ? statusToneClass.warn : statusToneClass.ok}>
                {requiredFieldsDirty ? 'Unsaved changes' : 'Configuration saved'}
              </span>
            </div>
          </>
        )}

        {activeTab === 'classification' && (
          <>
            <div className="-mt-2.5 text-sm text-ink-soft">Current supported classification codes. Add your own if you need one that isn't listed.</div>

            <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-cream">
              {STANDARDS.map((s) => (
                <div key={s.key} className="flex cursor-default select-text items-start gap-3 border-b border-line bg-white px-4 py-3.5 last:border-b-0">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-[#3d7a3d]" strokeWidth={1.75} />
                  <div className="flex flex-1 flex-col gap-0.5">
                    <div className="text-[15px] font-semibold text-ink">{s.name}</div>
                    <div className="text-[13px] text-ink-soft">{s.desc}</div>
                  </div>
                </div>
              ))}

              {customStandards.map((s, i) => (
                <div key={`${s.name}-${i}`} className="flex cursor-default select-text items-start gap-3 border-b border-line bg-white px-4 py-3.5 last:border-b-0">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-[#3d7a3d]" strokeWidth={1.75} />
                  <div className="flex flex-1 flex-col gap-0.5">
                    <div className="text-[15px] font-semibold text-ink">{s.name}</div>
                    <div className="text-[13px] text-ink-soft">Custom standard, uploaded by you.</div>
                  </div>
                </div>
              ))}

              {pendingFile && (
                <div className="flex cursor-default select-text items-start gap-3 border-b border-line bg-[#fffaf1] px-4 py-3.5 last:border-b-0">
                  <Clock className="mt-0.5 h-4 w-4 flex-none text-[#9a7413]" strokeWidth={1.75} />
                  <div className="flex flex-1 flex-col gap-0.5">
                    <div className="text-[15px] font-semibold text-ink">{pendingFile.name}</div>
                    <div className="text-[13px] text-ink-soft">Not yet saved — click "Save configuration" to add it below.</div>
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-3">
              <label className="inline-flex h-10 cursor-pointer items-center rounded-md border border-teal bg-white px-4 text-sm font-semibold text-teal transition-colors hover:bg-sage">
                + Add custom standard
                <input
                  type="file"
                  accept="application/pdf"
                  style={{ display: 'none' }}
                  onChange={(e) => setPendingFile(e.target.files[0] || null)}
                />
              </label>
            </div>

            <div className="flex items-center gap-3.5">
              <button className="flex h-10 items-center rounded-md bg-teal px-[18px] text-[15px] font-semibold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:bg-[#ece4d6] disabled:text-[#a49c8e]" disabled={!pendingFile} onClick={saveCustomStandard}>
                Save configuration
              </button>
              <span className={pendingFile ? statusToneClass.warn : statusToneClass.ok}>
                {pendingFile ? 'Unsaved changes' : 'All standards saved'}
              </span>
            </div>
          </>
        )}
      </div>

      <div className="flex flex-col gap-[18px] rounded-lg border border-line bg-white p-6">
        <div className="text-lg font-semibold text-ink">User information</div>
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