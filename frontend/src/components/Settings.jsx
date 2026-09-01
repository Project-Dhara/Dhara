import { useState } from 'react'

// Static status glyphs for the standards list — signal "this is a status",
// not a control, since the row itself has no click behavior.
function CheckIcon({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5 8.2l2 2 4-4.4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function ClockIcon({ className }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 4.5V8l2.5 1.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const PROVIDERS = ['Anthropic', 'OpenAI', 'Self-hosted']
const ROLES = ['Administrator', 'Data Steward', 'Data User']

const STANDARDS = [
  { key: 'nmds', name: 'National Metadata Structure (NMDS 2.0)', desc: 'Used for the metadata workspace fields.' },
  { key: 'nco', name: 'National Classification of Occupations (NCO 2015)', desc: 'Standard occupation codes used during harmonisation.' },
  { key: 'nic', name: 'National Industrial Classification (NIC 2008)', desc: 'Standard industry codes used during harmonisation.' },
]

// Mock LLM provider/key form + user info form. No persistence backend today
// — `keySaved` is local state only, matching the mockup.
export default function Settings({ settings, onSettingsChange, keySaved, onSaveKey, user, onUserChange }) {
  const [local, setLocal] = useState(settings)
  const [customStandards, setCustomStandards] = useState([]) // saved custom standards: [{ name }]
  const [pendingFile, setPendingFile] = useState(null) // just uploaded, not yet saved

  const setField = (key) => (e) => {
    const next = { ...local, [key]: e.target.value }
    setLocal(next)
    onSettingsChange(next)
  }
  const setUserField = (key) => (e) => onUserChange({ ...user, [key]: e.target.value })

  const status = keySaved ? 'Key saved' : local.apiKey ? 'Unsaved changes' : 'No key configured'
  const statusClass = keySaved ? 'settings-key-status-ok' : local.apiKey ? 'settings-key-status-warn' : 'settings-key-status-none'

  const saveCustomStandard = () => {
    if (!pendingFile) return
    setCustomStandards((prev) => [...prev, { name: pendingFile.name }])
    setPendingFile(null)
  }

  return (
    <div className="settings-screen">
      <div className="settings-head">
        <div className="settings-title">Settings</div>
        
      </div>

      <div className="settings-card">
        <div className="settings-card-title">LLM API key</div>
        <div className="settings-grid-2">
          <div className="settings-field">
            <label className="settings-label">Provider</label>
            <select className="settings-input" value={local.provider} onChange={setField('provider')}>
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="settings-field">
            <label className="settings-label">API key</label>
            <input className="settings-input" type="password" value={local.apiKey} onChange={setField('apiKey')} placeholder="sk-..." />
          </div>
        </div>
        <div className="settings-key-row">
          <button className="settings-save-btn" onClick={onSaveKey}>Save key</button>
          <span className={statusClass}>{status}</span>
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card-title">Standards Configuration</div>
        <div className="settings-sub-note">Current supported standards. Add your own if you need one that isn't listed.</div>

        <div className="settings-standards-list">
          {STANDARDS.map((s) => (
            <div key={s.key} className="settings-standard-item">
              <CheckIcon className="settings-standard-check" />
              <div className="settings-standard-text">
                <div className="settings-standard-name">{s.name}</div>
                <div className="settings-standard-desc">{s.desc}</div>
              </div>
            </div>
          ))}

          {customStandards.map((s, i) => (
            <div key={`${s.name}-${i}`} className="settings-standard-item">
              <CheckIcon className="settings-standard-check" />
              <div className="settings-standard-text">
                <div className="settings-standard-name">{s.name}</div>
                <div className="settings-standard-desc">Custom standard, uploaded by you.</div>
              </div>
            </div>
          ))}

          {pendingFile && (
            <div className="settings-standard-item settings-standard-item-pending">
              <ClockIcon className="settings-standard-check" />
              <div className="settings-standard-text">
                <div className="settings-standard-name">{pendingFile.name}</div>
                <div className="settings-standard-desc">Not yet saved — click "Save configuration" to add it below.</div>
              </div>
            </div>
          )}
        </div>

        <div className="settings-upload-row">
          <label className="settings-upload-btn">
            + Add custom standard
            <input
              type="file"
              accept="application/pdf"
              style={{ display: 'none' }}
              onChange={(e) => setPendingFile(e.target.files[0] || null)}
            />
          </label>
        </div>

        <div className="settings-key-row">
          <button className="settings-save-btn" disabled={!pendingFile} onClick={saveCustomStandard}>
            Save configuration
          </button>
          <span className={pendingFile ? 'settings-key-status-warn' : 'settings-key-status-ok'}>
            {pendingFile ? 'Unsaved changes' : 'All standards saved'}
          </span>
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card-title">User information</div>
        <div className="settings-grid-2">
          <div className="settings-field">
            <label className="settings-label">Name</label>
            <input className="settings-input" type="text" value={user.name} onChange={setUserField('name')} />
          </div>
          <div className="settings-field">
            <label className="settings-label">Role</label>
            <select className="settings-input" value={user.role} onChange={setUserField('role')}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="settings-field">
            <label className="settings-label">Email</label>
            <input className="settings-input" type="email" value={user.email} onChange={setUserField('email')} />
          </div>
          <div className="settings-field">
            <label className="settings-label">Department</label>
            <input className="settings-input" type="text" value={user.dept} onChange={setUserField('dept')} />
          </div>
        </div>
      </div>
    </div>
  )
}
