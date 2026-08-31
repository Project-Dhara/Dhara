import { useRef, useState } from 'react'

const MODALITY_OPTIONS = [
  'Structured / tabular',
  'Semi-structured',
  'Binary serialisation / interchange',
  'Database native',
  'Geospatial',
  'Documents and text',
  'Scanned / image-as-document',
  'Raster images',
  'Audio',
  'Video',
  'Biometric',
  'Logs and event data',
  'Scientific / research',
  'Communication / messaging',
  'AI / model',
  'Synthetic / derived',
  'Mixed (tick the specific categories present)',
  'Other (does not fit any category above — describe)',
]

const DPDP_TIERS = [
  'Open (no PII)',
  'Aggregated from personal data',
  'Quasi-identifiable',
  'PII',
  'Special-category PII (tick sub-types below)',
]

const SPECIAL_CATEGORY_SUBTYPES = [
  'Health / medical records',
  'HIV status',
  'Biometric incl. voiceprint',
  'Genetic data',
  'Caste / tribe',
  'Religion',
  'Sexual orientation',
  "Children's data (under 18)",
  'Financial data',
  'Disability',
  'Trade union membership',
  'Political opinion / affiliation',
  'Location traces over time',
]

const ORG_CLASSIFICATION = ['Confidential', 'Restricted', 'Internal use', 'Unclassified']

const NATIONAL_CLASSIFICATION = ['Top Secret', 'Secret', 'Confidential', 'Restricted', 'Unclassified']

const ACCESS_LEVELS = [
  'Open data',
  'Statutorily mandated disclosure',
  'Registered access',
  'Controlled access',
  'Restricted (inter-agency / MOU)',
  'Embargoed',
  'Internal only',
]

const GRANULARITY_INDIVIDUAL = [
  'Individual / Record level',
  'Event / Transaction level',
  'Household / Family',
]

const GRANULARITY_LOCAL = [
  'Building / Property / Parcel / Survey Number',
  'Street / Locality / Village',
  'Gram Panchayat / Municipal Ward',
  'Community / Neighbourhood',
  'Block / Taluk / Tehsil / Mandal',
  'District',
]

const GRANULARITY_REGIONAL = [
  'City / Municipality / Urban Local Body',
  'Metropolitan Region',
  'State / UT',
  'Regional / Zonal Office',
  'National',
]

const GRANULARITY_STATISTICAL = ['Aggregated / Statistical only', 'Mixed granularities']

const UPDATE_FREQUENCY = [
  'Streaming / Continuous',
  'Real-time (< 1 min)',
  'Near real-time (< 1 hour)',
  'Hourly',
  'Daily',
  'Weekly',
  'Fortnightly',
  'Monthly',
  'Bi-monthly',
  'Quarterly',
  'Half-yearly',
  'Annual',
  'Multi-year',
  'Event-triggered',
  'Irregular / Ad-hoc',
  'Historical / Archival',
]

const RETENTION = [
  'Indefinite',
  'Defined statutory period (cite below)',
  'Until purpose served',
  'Until specific event',
  'Operational discretion',
  'Not yet determined',
]

const STORAGE_OFFLINE = [
  'Local file server',
  'Network-attached storage (NAS)',
  'Storage area network (SAN)',
  'On-premise data warehouse',
  'Airgapped / offline storage',
  'Physical media',
]

const STORAGE_ONLINE = ['Cloud-based storage']

const DPIA_OPTIONS = ['Yes', 'In progress', 'No', 'Not required']

const YES_NO = ['No', 'Yes']

function emptyForm() {
  return {
    datasetName: '',
    description: '',
    department: '',
    characterisationDate: '',
    modality: [],
    otherModalityDescribe: '',
    specificFormats: '',
    dpdpTiers: [],
    specialCategorySubtypes: [],
    degreePerTier: '',
    orgClassification: [],
    nationalClassification: [],
    accessLevel: [],
    moreOpenSubset: '',
    restrictedSharingPartner: '',
    embargoedRelease: '',
    granularity: [],
    restrictedToSubPopulation: [],
    linkedPersistentId: [],
    longitudinal: [],
    updateFrequency: [],
    retention: [],
    retentionCitation: '',
    storage: [],
    restrictedLawfulBasis: '',
    specialCategoryBasis: '',
    dpia: [],
    notes: '',
  }
}

function toggleIn(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

function CheckboxGrid({ options, selected, onToggle }) {
  return (
    <div className="kyds-check-grid">
      {options.map((opt) => (
        <label key={opt} className="kyds-check">
          <input
            type="checkbox"
            checked={selected.includes(opt)}
            onChange={() => onToggle(opt)}
          />
          <span>{opt}</span>
        </label>
      ))}
    </div>
  )
}

function ExclusiveCheckboxes({ options, selected, onChange }) {
  return (
    <div className="kyds-check-row">
      {options.map((opt) => (
        <label key={opt} className="kyds-check">
          <input
            type="checkbox"
            checked={selected.includes(opt)}
            onChange={() => onChange(selected.includes(opt) ? [] : [opt])}
          />
          <span>{opt}</span>
        </label>
      ))}
    </div>
  )
}

function ExclusiveCheckboxGrid({ options, selected, onChange }) {
  return (
    <div className="kyds-check-grid">
      {options.map((opt) => (
        <label key={opt} className="kyds-check">
          <input
            type="checkbox"
            checked={selected.includes(opt)}
            onChange={() => onChange(selected.includes(opt) ? [] : [opt])}
          />
          <span>{opt}</span>
        </label>
      ))}
    </div>
  )
}

function Field({ label, hint, children }) {
  return (
    <div className="kyds-field">
      <label className="kyds-label">{label}</label>
      {hint && <div className="kyds-hint">{hint}</div>}
      {children}
    </div>
  )
}

export default function KydsModal({ onSkip, onSave }) {
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)

  const setList = (key) => (value) => {
    setForm((prev) => ({ ...prev, [key]: toggleIn(prev[key], value) }))
  }

  const setText = (key) => (e) => {
    setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  const setExclusive = (key) => (next) => {
    setForm((prev) => ({ ...prev, [key]: next }))
  }

  return (
    <div className="kyds-overlay" role="dialog" aria-modal="true" aria-labelledby="kyds-title">
      <div className="kyds-modal">
        <div className="kyds-header">
          <div>
            <div className="kyds-eyebrow">Optional · Know Your Dataset</div>
            <div id="kyds-title" className="kyds-title">KYDS Entry</div>
            <div className="kyds-sub">
              Record modality, sensitivity, access, granularity, retention and storage.
              You can skip this and continue — none of these fields are required.
            </div>
          </div>
          <button type="button" className="push-close" onClick={onSkip} aria-label="Skip KYDS form">×</button>
        </div>

        <div className="kyds-body">
          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">0</span>
              <h2>About this assessment</h2>
            </div>
            <Field label="Dataset name">
              <input
                className="kyds-input"
                type="text"
                value={form.datasetName}
                onChange={setText('datasetName')}
                placeholder="Name the dataset is actually known by"
              />
            </Field>
            <Field
              label="Description of the dataset"
              hint="What it contains, what a single row represents, and what it is used for."
            >
              <textarea
                className="kyds-input kyds-textarea"
                value={form.description}
                onChange={setText('description')}
                placeholder="e.g. Records of ration card holders in the district. One row per ration card..."
              />
            </Field>
            <Field label="Department / ministry">
              <input
                className="kyds-input"
                type="text"
                value={form.department}
                onChange={setText('department')}
                placeholder="Department or ministry that holds this dataset"
              />
            </Field>
            <Field label="Date of characterisation">
              <input
                className="kyds-input"
                type="date"
                value={form.characterisationDate}
                onChange={setText('characterisationDate')}
              />
            </Field>
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">1</span>
              <h2>Modality</h2>
            </div>
            <p className="kyds-section-lead">Tick every category present in the dataset.</p>
            <CheckboxGrid options={MODALITY_OPTIONS} selected={form.modality} onToggle={setList('modality')} />
            <Field label="Other — describe">
              <input
                className="kyds-input"
                type="text"
                value={form.otherModalityDescribe}
                onChange={setText('otherModalityDescribe')}
                placeholder="Describe if Other is ticked"
              />
            </Field>
            <Field
              label="Specific format(s) within ticked categories"
              hint="Optional, for precision — e.g. Excel (.xlsx), GeoJSON, PDF."
            >
              <input
                className="kyds-input"
                type="text"
                value={form.specificFormats}
                onChange={setText('specificFormats')}
                placeholder="e.g. Excel (.xlsx), CSV, GeoJSON"
              />
            </Field>
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">2</span>
              <h2>Sensitivity and classification</h2>
            </div>

            <h3 className="kyds-subhead">A. Personal-data sensitivity (DPDP Act)</h3>
            <ExclusiveCheckboxGrid options={DPDP_TIERS} selected={form.dpdpTiers} onChange={setExclusive('dpdpTiers')} />

            <h3 className="kyds-subhead">Special-category sub-types</h3>
            <CheckboxGrid
              options={SPECIAL_CATEGORY_SUBTYPES}
              selected={form.specialCategorySubtypes}
              onToggle={setList('specialCategorySubtypes')}
            />

            <Field
              label="Degree per tier"
              hint="Proportion of records / which fields."
            >
              <textarea
                className="kyds-input kyds-textarea"
                value={form.degreePerTier}
                onChange={setText('degreePerTier')}
                placeholder="e.g. PII in 12% of rows — name, Aadhaar, phone"
              />
            </Field>

            <h3 className="kyds-subhead">B. Information / dataset classification (IT Act)</h3>
            <h4 className="kyds-group-label">Organisational classification</h4>
            <ExclusiveCheckboxGrid
              options={ORG_CLASSIFICATION}
              selected={form.orgClassification}
              onChange={setExclusive('orgClassification')}
            />
            <h4 className="kyds-group-label">National-interest classification (only if applicable)</h4>
            <ExclusiveCheckboxGrid
              options={NATIONAL_CLASSIFICATION}
              selected={form.nationalClassification}
              onChange={setExclusive('nationalClassification')}
            />
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">3</span>
              <h2>Access level</h2>
            </div>
            <p className="kyds-section-lead">Pick the most restrictive level that governs the dataset.</p>
            <ExclusiveCheckboxGrid options={ACCESS_LEVELS} selected={form.accessLevel} onChange={setExclusive('accessLevel')} />
            <Field
              label="If a more open subset is published separately, what and at what aggregation"
            >
              <input
                className="kyds-input"
                type="text"
                value={form.moreOpenSubset}
                onChange={setText('moreOpenSubset')}
                placeholder="e.g. District-level dashboard extract"
              />
            </Field>
            <Field label="If Restricted: sharing partner">
              <input
                className="kyds-input"
                type="text"
                value={form.restrictedSharingPartner}
                onChange={setText('restrictedSharingPartner')}
                placeholder="Agency or partner name"
              />
            </Field>
            <Field label="If Embargoed: release trigger and responsible authority">
              <input
                className="kyds-input"
                type="text"
                value={form.embargoedRelease}
                onChange={setText('embargoedRelease')}
                placeholder="Trigger and authority"
              />
            </Field>
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">4</span>
              <h2>Granularity</h2>
            </div>
            <p className="kyds-section-lead">Tick the finest level present.</p>
            <h4 className="kyds-group-label">Individual level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_INDIVIDUAL} selected={form.granularity} onChange={setExclusive('granularity')} />
            <h4 className="kyds-group-label">Local level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_LOCAL} selected={form.granularity} onChange={setExclusive('granularity')} />
            <h4 className="kyds-group-label">Regional level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_REGIONAL} selected={form.granularity} onChange={setExclusive('granularity')} />
            <h4 className="kyds-group-label">Statistical level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_STATISTICAL} selected={form.granularity} onChange={setExclusive('granularity')} />

            <h3 className="kyds-subhead">Identifiability flags</h3>
            <Field label="Restricted to a sub-population?">
              <ExclusiveCheckboxes
                options={YES_NO}
                selected={form.restrictedToSubPopulation}
                onChange={setExclusive('restrictedToSubPopulation')}
              />
            </Field>
            <Field label="Linked to a persistent identifier?">
              <ExclusiveCheckboxes
                options={YES_NO}
                selected={form.linkedPersistentId}
                onChange={setExclusive('linkedPersistentId')}
              />
            </Field>
            <Field label="Longitudinal?">
              <ExclusiveCheckboxes
                options={YES_NO}
                selected={form.longitudinal}
                onChange={setExclusive('longitudinal')}
              />
            </Field>
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">5</span>
              <h2>Update frequency and retention</h2>
            </div>
            <h4 className="kyds-group-label">Update frequency</h4>
            <ExclusiveCheckboxGrid options={UPDATE_FREQUENCY} selected={form.updateFrequency} onChange={setExclusive('updateFrequency')} />
            <h4 className="kyds-group-label">Retention</h4>
            <ExclusiveCheckboxGrid options={RETENTION} selected={form.retention} onChange={setExclusive('retention')} />
            <Field label="Retention citation / purpose / event">
              <textarea
                className="kyds-input kyds-textarea"
                value={form.retentionCitation}
                onChange={setText('retentionCitation')}
                placeholder="e.g. Rule X of Y Rules, 8 years from closure"
              />
            </Field>
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">6</span>
              <h2>Storage</h2>
            </div>
            <h4 className="kyds-group-label">Offline</h4>
            <CheckboxGrid options={STORAGE_OFFLINE} selected={form.storage} onToggle={setList('storage')} />
            <h4 className="kyds-group-label">Online</h4>
            <CheckboxGrid options={STORAGE_ONLINE} selected={form.storage} onToggle={setList('storage')} />
          </section>

          <section className="kyds-section">
            <div className="kyds-section-head">
              <span className="kyds-section-num">7</span>
              <h2>Notes and lawful basis</h2>
              <span className="kyds-optional-pill">Optional</span>
            </div>
            <Field label="If Restricted access — lawful basis cited">
              <textarea
                className="kyds-input kyds-textarea"
                value={form.restrictedLawfulBasis}
                onChange={setText('restrictedLawfulBasis')}
                placeholder="Cite the statute or exemption — an MOU alone is not a lawful basis"
              />
            </Field>
            <Field label="If Special-category — sectoral / constitutional basis cited">
              <textarea
                className="kyds-input kyds-textarea"
                value={form.specialCategoryBasis}
                onChange={setText('specialCategoryBasis')}
                placeholder="e.g. Aadhaar Act 2016; Mental Healthcare Act 2017"
              />
            </Field>
            <Field label="Data Protection Impact Assessment done?">
              <ExclusiveCheckboxes options={DPIA_OPTIONS} selected={form.dpia} onChange={setExclusive('dpia')} />
            </Field>
            <Field label="Notes">
              <textarea
                className="kyds-input kyds-textarea"
                value={form.notes}
                onChange={setText('notes')}
                placeholder="Any additional characterisation notes"
              />
            </Field>
          </section>
        </div>

        <div className="kyds-footer">
          <button type="button" className="push-btn-secondary" onClick={onSkip}>
            Skip for now
          </button>
          <button
            type="button"
            className="push-btn"
            disabled={saving}
            onClick={() => {
              if (savingRef.current) return
              savingRef.current = true
              setSaving(true)
              onSave(form)
            }}
          >
            Save &amp; continue
          </button>
        </div>
      </div>
    </div>
  )
}
