'use client'

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Clock } from 'lucide-react'
import Button from './ui/Button'
import { METADATA_COLUMNS } from './console/MetadataSheetGrid'
import {
  getDatasetIdConfig,
  setDatasetIdConfig as persistDatasetIdConfig,
  statisticsShortForm,
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
  { value: 'openai', label: 'OpenAI' },
  { value: 'self-hosted', label: 'Self-hosted' },
]
const ROLES = ['Administrator', 'Data Steward', 'Data User']

function DesktopSupportCard({ fieldLabelClass: _fieldLabelClass }) {
  const [diagNote, setDiagNote] = useState('')

  return (
    <div className="flex flex-col gap-[18px] rounded-2xl border border-line/90 bg-surface p-6">
      <div className="flex flex-col gap-1">
        <div className="text-[16px] font-semibold tracking-tight text-ink">Desktop help</div>
        <div className="text-sm text-ink-soft">
          Cloud API keys are recommended. Local Ollama is optional and starts only when you use a local
          model. Prefer about 1.2 GB free RAM before large PDF jobs.
        </div>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button
          variant="secondary"
          onClick={() => { void window.dharaDesktop?.openLogsFolder?.() }}
        >
          Open logs folder
        </Button>
        <Button
          variant="secondary"
          onClick={async () => {
            try {
              await window.dharaDesktop?.copyDiagnostics?.()
              setDiagNote('Diagnostics copied to the clipboard.')
            } catch {
              setDiagNote('Could not copy diagnostics.')
            }
          }}
        >
          Copy diagnostics
        </Button>
      </div>
      {diagNote ? <div className="text-[13px] text-ink-soft">{diagNote}</div> : null}
    </div>
  )
}

const LOCAL_MODEL_FALLBACK = {
  modelId: 'gemma3:1b',
  baseUrl: 'http://127.0.0.1:11434/v1',
  approxSizeLabel: '~800 MB',
}

/**
 * Desktop-only guided flow for optional Gemma 3 1B via bundled (or system) Ollama.
 * Never auto-saves LLM credentials — only fills the form on explicit click.
 */
function LocalModelCard({ applyLocalModel }) {
  const [status, setStatus] = useState(null)
  const [checking, setChecking] = useState(true)
  const [pull, setPull] = useState(null)
  const [confirmPull, setConfirmPull] = useState(false)
  const [testNote, setTestNote] = useState('')
  const [testing, setTesting] = useState(false)
  const [fillNote, setFillNote] = useState('')

  const defaults = status?.defaults || LOCAL_MODEL_FALLBACK
  const modelId = defaults.modelId || LOCAL_MODEL_FALLBACK.modelId
  const bundled = Boolean(status?.bundled)

  const refreshStatus = useCallback(async () => {
    setChecking(true)
    try {
      const s = await window.dharaDesktop?.ollama?.status?.()
      setStatus(s || null)
    } catch {
      setStatus(null)
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void refreshStatus()
    let cancelled = false
    ;(async () => {
      try {
        const ps = await window.dharaDesktop?.ollama?.pullStatus?.()
        if (!cancelled && ps) setPull(ps)
      } catch {
        /* ignore */
      }
    })()
    const unsub = window.dharaDesktop?.ollama?.onPullProgress?.((payload) => {
      setPull(payload)
      if (payload?.phase === 'success') {
        void refreshStatus()
      }
    })
    return () => {
      cancelled = true
      if (typeof unsub === 'function') unsub()
    }
  }, [refreshStatus])

  const pulling = pull?.phase === 'pulling'
  const reachable = Boolean(status?.reachable)
  const versionOk = status?.versionOk !== false
  const modelPresent = Boolean(status?.modelPresent)
  const diskOk = status?.diskOk !== false

  const onDownload = async () => {
    if (!confirmPull) {
      setConfirmPull(true)
      return
    }
    setConfirmPull(false)
    setTestNote('')
    setFillNote('')
    try {
      const ps = await window.dharaDesktop?.ollama?.pullStart?.()
      if (ps) setPull(ps)
      if (ps?.phase === 'success') void refreshStatus()
    } catch (err) {
      setPull({
        phase: 'error',
        percent: null,
        status: 'error',
        error: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const onCancelPull = async () => {
    try {
      const ps = await window.dharaDesktop?.ollama?.pullCancel?.()
      if (ps) setPull(ps)
    } catch {
      /* ignore */
    }
  }

  const onUseModel = () => {
    applyLocalModel({
      provider: 'self-hosted',
      baseUrl: defaults.baseUrl || LOCAL_MODEL_FALLBACK.baseUrl,
      model: modelId,
      apiKeyPlaceholder: 'ollama',
    })
    setFillNote('Form filled. Click “Save key” above to persist.')
  }

  const onTest = async () => {
    setTesting(true)
    setTestNote('Loading the model into memory — this can take a minute on CPU.')
    try {
      const r = await window.dharaDesktop?.ollama?.testConnection?.()
      if (!r) {
        setTestNote('Could not run the connection test.')
        return
      }
      if (r.ok) {
        let msg = `Connection OK (${r.latencyMs} ms).`
        if (r.ramWarning) msg += ` ${r.ramWarning}`
        setTestNote(msg)
      } else {
        setTestNote(r.error || 'Connection test failed.')
      }
    } catch (err) {
      setTestNote(err instanceof Error ? err.message : String(err))
    } finally {
      setTesting(false)
    }
  }

  const percent = typeof pull?.percent === 'number' ? pull.percent : null

  return (
    <div className="flex flex-col gap-[18px] rounded-2xl border border-line/90 bg-surface p-6">
      <div className="flex flex-col gap-1">
        <div className="text-[16px] font-semibold tracking-tight text-ink">
          Run a local model (optional)
        </div>
        <div className="text-sm text-ink-soft">
          Use Gemma 3 1B on your PC via Ollama. Dhara ships Ollama and starts it when you use this
          option; the model (~800 MB) downloads on first use. Cloud keys are still recommended on
          8 GB machines.
        </div>
      </div>

      {checking && !status ? (
        <div className="text-[13px] text-ink-soft">Starting local Ollama…</div>
      ) : null}

      {!checking && !reachable ? (
        <div className="flex flex-col gap-3">
          <div className="text-[13px] text-ink-soft">
            {bundled
              ? (status?.error
                || `Bundled Ollama could not start at ${defaults.baseUrl?.replace(/\/v1$/, '') || 'http://127.0.0.1:11434'}. Check the logs, then try again.`)
              : `Ollama is not available at ${defaults.baseUrl?.replace(/\/v1$/, '') || 'http://127.0.0.1:11434'}. This build has no bundled runtime — install Ollama yourself, start it, then check again.`}
          </div>
          <div className="flex flex-wrap gap-3">
            {!bundled ? (
              <Button
                variant="secondary"
                onClick={() => { void window.dharaDesktop?.ollama?.openDownloadPage?.() }}
              >
                Open Ollama download page
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => { void refreshStatus() }}>
              {bundled ? 'Start again' : 'Check again'}
            </Button>
          </div>
        </div>
      ) : null}

      {reachable && !versionOk ? (
        <div className="flex flex-col gap-3">
          <div className="text-[13px] text-coral">
            {status?.versionWarning ||
              'Please update Ollama to 0.6 or newer to use Gemma 3 1B.'}
          </div>
          <div className="flex flex-wrap gap-3">
            {!bundled ? (
              <Button
                variant="secondary"
                onClick={() => { void window.dharaDesktop?.ollama?.openDownloadPage?.() }}
              >
                Open Ollama download page
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => { void refreshStatus() }}>
              Check again
            </Button>
          </div>
        </div>
      ) : null}

      {reachable && versionOk && status?.versionWarning ? (
        <div className="text-[13px] text-ink-soft">{status.versionWarning}</div>
      ) : null}

      {reachable && versionOk && !modelPresent && !pulling && pull?.phase !== 'success' ? (
        <div className="flex flex-col gap-3">
          {!diskOk ? (
            <div className="text-[13px] text-coral">
              {status?.diskMessage || 'Not enough free disk space to download the model.'}
            </div>
          ) : null}
          {confirmPull ? (
            <div className="text-[13px] text-ink-soft">
              This downloads about {defaults.approxSizeLabel || '~800 MB'}. Continue only if you have
              enough disk space and a stable network.
            </div>
          ) : (
            <div className="text-[13px] text-ink-soft">
              Download <span className="font-medium text-ink">{modelId}</span> (
              {defaults.approxSizeLabel || '~800 MB'}) to use a local CPU model.
            </div>
          )}
          {pull?.phase === 'error' || pull?.phase === 'cancelled' ? (
            <div className="text-[13px] text-coral">
              {pull.error ||
                'Download interrupted. It is safe to retry — Ollama will resume.'}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button
              onClick={() => { void onDownload() }}
              disabled={!diskOk}
            >
              {confirmPull ? `Download ${modelId}` : `Prepare ${modelId} download`}
            </Button>
            {confirmPull ? (
              <Button variant="secondary" onClick={() => setConfirmPull(false)}>
                Cancel
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => { void refreshStatus() }}>
              Refresh status
            </Button>
          </div>
        </div>
      ) : null}

      {pulling ? (
        <div className="flex flex-col gap-3">
          <div className="text-[13px] text-ink-soft">
            Downloading {modelId}… {pull?.status || ''}
            {percent != null ? ` (${percent}%)` : ''}
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-teal transition-all duration-300"
              style={{
                width: percent != null ? `${percent}%` : '30%',
                opacity: percent != null ? 1 : 0.5,
              }}
            />
          </div>
          <Button variant="secondary" onClick={() => { void onCancelPull() }}>
            Cancel download
          </Button>
        </div>
      ) : null}

      {reachable && versionOk && (modelPresent || pull?.phase === 'success') ? (
        <div className="flex flex-col gap-3">
          <div className="text-[13px] text-green">
            {modelId} is available in Ollama.
          </div>
          <div className="flex flex-wrap gap-3">
            <Button onClick={onUseModel}>Use this model in the form</Button>
            <Button variant="secondary" disabled={testing} onClick={() => { void onTest() }}>
              {testing ? 'Testing…' : 'Test connection'}
            </Button>
            <Button variant="secondary" onClick={() => { void refreshStatus() }}>
              Refresh status
            </Button>
          </div>
          {fillNote ? <div className="text-[13px] text-ink-soft">{fillNote}</div> : null}
          {testNote ? <div className="text-[13px] text-ink-soft">{testNote}</div> : null}
        </div>
      ) : null}
    </div>
  )
}

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

// LLM provider/key + user info. API key is loaded decrypted from Postgres via
// GET /api/llm-key (AppContext); classification standards also in Postgres.
const VALID_TABS = new Set(CONFIG_TABS.map((t) => t.key))

export default function Settings({
  settings,
  onSettingsChange,
  keySaved,
  llmCryptoError = false,
  onSaveKey,
  user,
  onUserChange,
  initialTab,
}) {
  const [local, setLocal] = useState(settings)
  const [standards, setStandards] = useState([])
  // Read-only bundled code lists (e.g. Delhi LGD) — pre-configured, not selectable or removable.
  const [referenceStandards, setReferenceStandards] = useState([])
  const [standardsLoading, setStandardsLoading] = useState(false)
  const [standardsError, setStandardsError] = useState('')
  const [standardsBusy, setStandardsBusy] = useState(false)
  const [addingStandard, setAddingStandard] = useState(false)
  const [pendingFile, setPendingFile] = useState(null)
  const [pendingName, setPendingName] = useState('')
  const [activeTab, setActiveTab] = useState(
    () => (VALID_TABS.has(initialTab) ? initialTab : 'dataset'),
  )
  const [datasetIdConfig, setDatasetIdConfig] = useState(getDatasetIdConfig)
  const [savedDatasetIdConfig, setSavedDatasetIdConfig] = useState(getDatasetIdConfig)
  const [extraRequiredFields, setExtraRequiredFields] = useState(getMetadataRequiredFields)
  const [savedRequiredFields, setSavedRequiredFields] = useState(getMetadataRequiredFields)
  const [metadataStandard, setMetadataStandard] = useState(getMetadataStandard)
  const [savedMetadataStandard, setSavedMetadataStandard] = useState(getMetadataStandard)
  const [pickingFields, setPickingFields] = useState(false)
  const [ncoAliases, setNcoAliases] = useState([])
  const [ncoAliasesLoading, setNcoAliasesLoading] = useState(false)
  const [ncoAliasesError, setNcoAliasesError] = useState('')
  const [ncoAliasesBusy, setNcoAliasesBusy] = useState(false)

  // AppContext loads the decrypted key from GET /api/llm-key — keep the form in sync.
  useEffect(() => {
    setLocal(settings)
  }, [settings])

  useEffect(() => {
    if (VALID_TABS.has(initialTab)) setActiveTab(initialTab)
  }, [initialTab])

  const setDatasetIdField = (key) => (e) => setDatasetIdConfig((prev) => ({ ...prev, [key]: e.target.value }))

  const setField = (key) => (e) => {
    const value = e.target.value
    const next = { ...local, [key]: value }
    // Switching away from self-hosted: drop Ollama endpoint fields so Save
    // cannot re-persist a leftover localhost base_url with an OpenAI key.
    if (key === 'provider' && value !== 'self-hosted') {
      next.baseUrl = ''
      next.model = ''
      if (String(next.apiKey || '').trim().toLowerCase() === 'ollama') {
        next.apiKey = ''
      }
    }
    setLocal(next)
    onSettingsChange(next)
  }
  const setUserField = (key) => (e) => onUserChange({ ...user, [key]: e.target.value })

  const status = llmCryptoError
    ? 'Stored key could not be decrypted — enter a new key'
    : keySaved
      ? 'Key saved'
      : local.apiKey
        ? 'Unsaved changes'
        : 'No key configured'
  const statusClass = llmCryptoError
    ? 'settings-key-status-warn'
    : keySaved
      ? 'settings-key-status-ok'
      : local.apiKey
        ? 'settings-key-status-warn'
        : 'settings-key-status-none'

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
      setReferenceStandards(Array.isArray(data.reference_standards) ? data.reference_standards : [])
    } catch (err) {
      setStandardsError(err.message || 'Failed to load classification standards')
    } finally {
      setStandardsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'classification') {
      loadStandards()
      loadNcoAliases()
    }
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

  const loadNcoAliases = async () => {
    setNcoAliasesLoading(true)
    setNcoAliasesError('')
    try {
      const res = await fetch('/api/catalogue/nco-aliases', withAuthHeaders())
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Failed to load NCO aliases')
      setNcoAliases(Array.isArray(data.aliases) ? data.aliases : [])
    } catch (err) {
      setNcoAliasesError(err.message || 'Failed to load NCO aliases')
    } finally {
      setNcoAliasesLoading(false)
    }
  }

  const deleteNcoAlias = async (normalizedValue) => {
    if (!normalizedValue) return
    setNcoAliasesBusy(true)
    setNcoAliasesError('')
    try {
      const res = await fetch(
        `/api/catalogue/nco-aliases?normalized_value=${encodeURIComponent(normalizedValue)}`,
        withAuthHeaders({ method: 'DELETE' }),
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Could not delete alias')
      await loadNcoAliases()
    } catch (err) {
      setNcoAliasesError(err.message || 'Could not delete alias')
    } finally {
      setNcoAliasesBusy(false)
    }
  }

  const clearLearnedNcoAliases = async () => {
    if (!window.confirm('Clear all learned (non-seed) NCO aliases? This cannot be undone.')) return
    setNcoAliasesBusy(true)
    setNcoAliasesError('')
    try {
      const res = await fetch(
        '/api/catalogue/nco-aliases/clear-learned',
        withAuthHeaders({ method: 'POST' }),
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Could not clear aliases')
      await loadNcoAliases()
    } catch (err) {
      setNcoAliasesError(err.message || 'Could not clear aliases')
    } finally {
      setNcoAliasesBusy(false)
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
        <div className="flex flex-col gap-1">
          <div className="text-[16px] font-semibold tracking-tight text-ink">LLM</div>
          <div className="text-sm text-ink-soft">
            One API key powers metadata auto-fill, NCO matching suggestions, and other AI assists.
            A cloud provider key is recommended; optional local models are configured below on desktop.
            Save the key here before AI-assisted steps.
          </div>
        </div>
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
            <input
              className={inputClass}
              type="password"
              value={local.apiKey}
              onChange={setField('apiKey')}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
        </div>
        {local.provider === 'self-hosted' ? (
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className={fieldLabelClass}>Base URL</label>
              <input
                className={inputClass}
                type="text"
                value={local.baseUrl || ''}
                onChange={setField('baseUrl')}
                autoComplete="off"
                spellCheck={false}
              />
              <div className="text-[12px] text-ink-muted">
                OpenAI-compatible endpoint. On Dhara Desktop with Ollama: http://127.0.0.1:11434/v1
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className={fieldLabelClass}>Model</label>
              <input
                className={inputClass}
                type="text"
                value={local.model || ''}
                onChange={setField('model')}
                autoComplete="off"
                spellCheck={false}
              />
              <div className="text-[12px] text-ink-muted">
                Small CPU models (e.g. gemma3:1b) recommended on 8 GB RAM systems.
              </div>
            </div>
          </div>
        ) : null}
        <div className="flex items-center gap-3.5">
          <Button
            onClick={() => {
              // Persist the form's local value (not a click event / stale context).
              onSaveKey(local)
            }}
          >
            Save key
          </Button>
          <span className={statusClass === 'settings-key-status-ok' ? statusToneClass.ok : statusClass === 'settings-key-status-warn' ? statusToneClass.warn : statusToneClass.none}>{status}</span>
        </div>
      </div>

      {typeof window !== 'undefined' && window.dharaDesktop?.isDesktop ? (
        <LocalModelCard
          applyLocalModel={({ provider, baseUrl, model, apiKeyPlaceholder }) => {
            setLocal((prev) => ({
              ...prev,
              provider,
              baseUrl,
              model,
              apiKey: (prev.apiKey || '').trim() ? prev.apiKey : apiKeyPlaceholder,
            }))
          }}
        />
      ) : null}

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
            <div className="rounded-lg border border-line bg-[#FFFCF6] px-3 py-2.5 text-[12.5px] text-ink-soft">
              Example catalogue ID:{' '}
              <span className="font-mono text-[12px] font-semibold text-ink">
                {[
                  datasetIdConfig.prefix,
                  statisticsShortForm(datasetIdConfig.statistics),
                  '00042',
                ].join(datasetIdConfig.separator || '_')}
              </span>
              <span className="mt-1 block text-[11.5px]">
                Prefix + statistics short form + a zero-padded sequence (e.g. 00042). Assigned when tables are extracted, shown in Preview, and kept at publish. Numbers are never reused.
              </span>
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
                    : 'Configure metadata fields for catalogue publication.'
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
              NCO 2015 and LGD codes are pre-configured from the backend. You can upload more
              CSVs and select which standard Classify should use for suggestions.
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
                        {s.uploaded_by !== 'system' && s.original_filename
                          ? ` · ${s.original_filename}`
                          : ''}
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

              {referenceStandards.map((s) => (
                <div
                  key={s.id}
                  className="flex items-start gap-3 border-b border-line bg-white px-4 py-3.5 last:border-b-0"
                >
                  <span
                    className="mt-0.5 flex h-5 w-5 flex-none items-center justify-center rounded-full border border-transparent bg-green text-white"
                    aria-hidden
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2.25} />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <div className="text-[15px] font-semibold text-ink">{s.name}</div>
                    <div className="text-[13px] text-ink-soft">Selected for classification.</div>
                  </div>
                </div>
              ))}

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
                    {standards.some((s) => s.is_selected) ? 'Active standard saved.' : 'Select a standard to use for Classify'}
                  </span>
                )}
              </div>
            )}

            {standardsError && (
              <div className="text-[13px] text-coral">{standardsError}</div>
            )}

            <div className="mt-2 flex flex-col gap-3 rounded-xl border border-line bg-[#FBF7EF] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-[13px] font-semibold text-ink">NCO value aliases</div>
                  <div className="text-[12.5px] text-ink-soft">
                    Steward-verified mappings reused by Suggest NCO. Conflicts never overwrite silently.
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="h-8 rounded-md border border-line bg-white px-3 text-[12.5px] font-semibold text-ink-soft hover:border-teal/40 hover:text-teal disabled:opacity-50"
                    disabled={ncoAliasesLoading || ncoAliasesBusy}
                    onClick={loadNcoAliases}
                  >
                    Refresh
                  </button>
                  <button
                    type="button"
                    className="h-8 rounded-md border border-coral/40 bg-white px-3 text-[12.5px] font-semibold text-coral hover:bg-coral/10 disabled:opacity-50"
                    disabled={ncoAliasesBusy || !ncoAliases.some((a) => a.source !== 'seed')}
                    onClick={clearLearnedNcoAliases}
                  >
                    Clear learned (non-seed)
                  </button>
                </div>
              </div>
              {ncoAliasesError && <div className="text-[13px] text-coral">{ncoAliasesError}</div>}
              {ncoAliasesLoading ? (
                <div className="text-[13px] text-ink-soft">Loading aliases…</div>
              ) : ncoAliases.length === 0 ? (
                <div className="text-[13px] text-ink-soft">No learned aliases yet.</div>
              ) : (
                <div className="max-h-56 overflow-auto rounded-lg border border-[#d7cdb9] bg-white">
                  <table className="w-full text-left text-[12.5px]">
                    <thead className="bg-[#F4EFE3] text-[11px] uppercase tracking-wide text-[#8E9398]">
                      <tr>
                        <th className="px-2.5 py-2 font-semibold">Label</th>
                        <th className="px-2.5 py-2 font-semibold">Code</th>
                        <th className="px-2.5 py-2 font-semibold">Version</th>
                        <th className="px-2.5 py-2 font-semibold">Source</th>
                        <th className="px-2.5 py-2 font-semibold">Updated</th>
                        <th className="px-2.5 py-2 font-semibold" />
                      </tr>
                    </thead>
                    <tbody>
                      {ncoAliases.map((a) => (
                        <tr key={a.normalized_value} className="border-t border-[#f1ebdf]">
                          <td className="px-2.5 py-1.5 font-medium text-ink">{a.normalized_value}</td>
                          <td className="px-2.5 py-1.5 tabular-nums text-ink">{a.code}</td>
                          <td className="px-2.5 py-1.5 text-ink-soft">{a.nco_version || '2015'}</td>
                          <td className="px-2.5 py-1.5 text-ink-soft">{a.source || '—'}</td>
                          <td className="px-2.5 py-1.5 text-ink-soft">
                            {a.updated_at ? String(a.updated_at).slice(0, 19) : '—'}
                          </td>
                          <td className="px-2.5 py-1.5 text-right">
                            <button
                              type="button"
                              className="text-[12px] font-semibold text-coral hover:underline disabled:opacity-50"
                              disabled={ncoAliasesBusy}
                              onClick={() => deleteNcoAlias(a.normalized_value)}
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
        </div>
      </div>

      {typeof window !== 'undefined' && window.dharaDesktop?.isDesktop ? (
        <DesktopSupportCard fieldLabelClass={fieldLabelClass} />
      ) : null}

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
