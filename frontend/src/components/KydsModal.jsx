'use client'

import { startTransition, useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'

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

// Short labels for the scrollspy dots -- the real section titles (below)
// are often too long to fit next to 8 dots in a fixed-width header.
const SECTION_LABELS = [
  'About', 'Modality', 'Sensitivity', 'Access', 'Granularity', 'Frequency', 'Storage', 'Notes',
]

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
    <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-x-3 gap-y-1.5">
      {options.map((opt) => (
        <label key={opt} className="flex cursor-pointer items-start gap-2 py-1 text-[13px] leading-tight text-ink">
          <input
            type="checkbox"
            className="mt-0.5 h-[15px] w-[15px] flex-none accent-teal"
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
    <div className="flex flex-wrap gap-x-4 gap-y-2">
      {options.map((opt) => (
        <label key={opt} className="flex cursor-pointer items-start gap-2 py-1 text-[13px] leading-tight text-ink">
          <input
            type="checkbox"
            className="mt-0.5 h-[15px] w-[15px] flex-none accent-teal"
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
    <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-x-3 gap-y-1.5">
      {options.map((opt) => (
        <label key={opt} className="flex cursor-pointer items-start gap-2 py-1 text-[13px] leading-tight text-ink">
          <input
            type="checkbox"
            className="mt-0.5 h-[15px] w-[15px] flex-none accent-teal"
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
    <div className="mt-1 flex flex-col gap-1">
      <label className="text-xs font-semibold text-ink">{label}</label>
      {hint && <div className="text-xs text-ink-soft">{hint}</div>}
      {children}
    </div>
  )
}

const inputClass = 'w-full rounded-[7px] border border-line bg-cream px-3 py-2 font-sans text-[13.5px] text-ink placeholder:text-[#a49c8e] focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal'
const textareaClass = `${inputClass} min-h-[72px] resize-y leading-relaxed`

// Sticky scrollspy dot-row: click a dot to jump to that section; the
// current section is highlighted as the user scrolls, and every dot up to
// the furthest section ever reached stays filled ("visited"), even if the
// user scrolls back up -- there's no real per-field validation in this
// form (see KydsModal below), so "visited" (scrolled past) is the only
// honestly-derivable progress signal, not "completed".
function ScrollspyNav({ activeIndex, maxSeenIndex, onJump }) {
  return (
    <div className="flex flex-shrink-0 items-center gap-1.5 border-b border-line bg-cream px-6 py-2.5">
      {SECTION_LABELS.map((label, i) => {
        const visited = i <= maxSeenIndex
        const isCurrent = i === activeIndex
        return (
          <button
            key={label}
            type="button"
            onClick={() => onJump(i)}
            className="group flex flex-1 flex-col items-center gap-1"
            title={label}
          >
            <span
              className={`h-1.5 w-full rounded-full transition-[background-color,box-shadow] duration-200 ${
                isCurrent ? 'bg-teal ring-2 ring-teal/30' : visited ? 'bg-teal/50' : 'bg-line'
              }`}
            />
            <span className={`text-center text-[10px] font-semibold leading-tight transition-colors duration-200 ${isCurrent ? 'text-teal' : 'text-ink-soft'}`}>
              {label}
            </span>
          </button>
        )
      })}
    </div>
  )
}

export default function KydsModal({ onSkip, onSave, initialForm = null, editing = false }) {
  const [form, setForm] = useState(() => ({ ...emptyForm(), ...(initialForm || {}) }))
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const savingRef = useRef(false)

  const bodyRef = useRef(null)
  const sectionRefs = useRef([])
  const jumpingRef = useRef(false)
  const jumpClearTimer = useRef(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [maxSeenIndex, setMaxSeenIndex] = useState(0)

  // Scrollspy: activate the last section whose top has crossed a line near
  // the top of the scrollport. IntersectionObserver was inconsistent because
  // tall sections stay "intersecting" long after you've moved into the next.
  useEffect(() => {
    const bodyEl = bodyRef.current
    if (!bodyEl) return undefined

    const ACTIVATION_OFFSET = 56
    let raf = 0

    const syncActiveFromScroll = () => {
      if (jumpingRef.current) return
      const sections = sectionRefs.current
      if (!sections.length) return

      const rootTop = bodyEl.getBoundingClientRect().top
      const marker = rootTop + ACTIVATION_OFFSET
      let next = 0
      for (let i = 0; i < sections.length; i++) {
        const el = sections[i]
        if (!el) continue
        if (el.getBoundingClientRect().top <= marker) next = i
      }

      // At the bottom, pin the last section so Notes lights up reliably.
      const atBottom = bodyEl.scrollTop + bodyEl.clientHeight >= bodyEl.scrollHeight - 4
      if (atBottom) {
        const last = sections.length - 1
        if (last >= 0) next = last
      }

      // Defer nav highlight updates so they don't contend with scroll frames.
      startTransition(() => {
        setActiveIndex((prev) => (prev === next ? prev : next))
        setMaxSeenIndex((prev) => (next > prev ? next : prev))
      })
    }

    const onScroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        syncActiveFromScroll()
      })
    }

    bodyEl.addEventListener('scroll', onScroll, { passive: true })
    // Layout may settle after first paint (fonts / checkboxes).
    const boot = requestAnimationFrame(syncActiveFromScroll)
    return () => {
      cancelAnimationFrame(boot)
      if (raf) cancelAnimationFrame(raf)
      bodyEl.removeEventListener('scroll', onScroll)
    }
  }, [])

  const jumpTo = (i) => {
    const bodyEl = bodyRef.current
    const section = sectionRefs.current[i]
    if (!bodyEl || !section) return

    jumpingRef.current = true
    setActiveIndex(i)
    setMaxSeenIndex((prev) => Math.max(prev, i))

    const delta = section.getBoundingClientRect().top - bodyEl.getBoundingClientRect().top
    const target = Math.max(0, bodyEl.scrollTop + delta - 12)
    bodyEl.scrollTo({ top: target, behavior: 'smooth' })

    const unlock = () => {
      if (!jumpingRef.current) return
      jumpingRef.current = false
      jumpClearTimer.current = null
    }
    if (jumpClearTimer.current) clearTimeout(jumpClearTimer.current)
    bodyEl.addEventListener('scrollend', unlock, { once: true })
    // Fallback when scrollend is unsupported or the scroll is a no-op.
    jumpClearTimer.current = setTimeout(unlock, 450)
  }

  useEffect(() => () => {
    if (jumpClearTimer.current) clearTimeout(jumpClearTimer.current)
  }, [])

  const setList = (key) => (value) => {
    setForm((prev) => ({ ...prev, [key]: toggleIn(prev[key], value) }))
  }

  const setText = (key) => (e) => {
    setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  const setExclusive = (key) => (next) => {
    setForm((prev) => ({ ...prev, [key]: next }))
  }

  const sectionProps = (i) => ({
    ref: (el) => { sectionRefs.current[i] = el },
    className: 'flex flex-col gap-2.5 rounded-[10px] border border-line bg-white px-[18px] pb-[18px] pt-4',
  })

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5" role="dialog" aria-modal="true" aria-labelledby="kyds-title">
      <div className="flex max-h-[92vh] w-full max-w-[860px] flex-col overflow-hidden rounded-[14px] bg-surface shadow-dhara">
        <div className="relative flex flex-shrink-0 items-center justify-center bg-cream px-12 pb-4 pt-5 text-center">
          <div>
            <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-teal">Optional · Know Your Dataset</div>
            <div id="kyds-title" className="text-2xl font-bold tracking-tight text-ink">{editing ? 'Edit KYDS Entry' : 'KYDS Entry'}</div>
            <div className="mt-1.5 text-[13.5px] leading-relaxed text-ink-soft">
              Record modality, sensitivity, access, granularity, retention and storage.
              {editing ? ' Update any fields below and save.' : ' You can skip this and continue — none of these fields are required.'}
            </div>
          </div>
          <button type="button" className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-md text-ink-soft hover:bg-white/60 hover:text-ink" onClick={onSkip} aria-label={editing ? 'Close' : 'Skip KYDS form'}>
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
        </div>

        <ScrollspyNav activeIndex={activeIndex} maxSeenIndex={maxSeenIndex} onJump={jumpTo} />

        {/* min-h-0 is required so this flex child can shrink and actually overflow-scroll. */}
        <div ref={bodyRef} className="flex min-h-0 flex-1 flex-col gap-[18px] overflow-y-auto px-6 pb-6 pt-[18px]">
          <section {...sectionProps(0)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">0</span>
              <h2 className="text-[16px] font-bold text-ink">About this assessment</h2>
            </div>
            <Field label="Dataset name">
              <input
                className={inputClass}
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
                className={textareaClass}
                value={form.description}
                onChange={setText('description')}
                placeholder="e.g. Records of ration card holders in the district. One row per ration card..."
              />
            </Field>
            <Field label="Department / ministry">
              <input
                className={inputClass}
                type="text"
                value={form.department}
                onChange={setText('department')}
                placeholder="Department or ministry that holds this dataset"
              />
            </Field>
            <Field label="Date of characterisation">
              <input
                className={inputClass}
                type="date"
                value={form.characterisationDate}
                onChange={setText('characterisationDate')}
              />
            </Field>
          </section>

          <section {...sectionProps(1)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">1</span>
              <h2 className="text-[16px] font-bold text-ink">Modality</h2>
            </div>
            <p className="text-[13px] leading-snug text-ink-soft">Tick every category present in the dataset.</p>
            <CheckboxGrid options={MODALITY_OPTIONS} selected={form.modality} onToggle={setList('modality')} />
            <Field label="Other — describe">
              <input
                className={inputClass}
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
                className={inputClass}
                type="text"
                value={form.specificFormats}
                onChange={setText('specificFormats')}
                placeholder="e.g. Excel (.xlsx), CSV, GeoJSON"
              />
            </Field>
          </section>

          <section {...sectionProps(2)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">2</span>
              <h2 className="text-[16px] font-bold text-ink">Sensitivity and classification</h2>
            </div>

            <h3 className="mt-1.5 text-[13px] font-bold text-ink">A. Personal-data sensitivity (DPDP Act)</h3>
            <ExclusiveCheckboxGrid options={DPDP_TIERS} selected={form.dpdpTiers} onChange={setExclusive('dpdpTiers')} />

            <h3 className="mt-1.5 text-[13px] font-bold text-ink">Special-category sub-types</h3>
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
                className={textareaClass}
                value={form.degreePerTier}
                onChange={setText('degreePerTier')}
                placeholder="e.g. PII in 12% of rows — name, Aadhaar, phone"
              />
            </Field>

            <h3 className="mt-1.5 text-[13px] font-bold text-ink">B. Information / dataset classification (IT Act)</h3>
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Organisational classification</h4>
            <ExclusiveCheckboxGrid
              options={ORG_CLASSIFICATION}
              selected={form.orgClassification}
              onChange={setExclusive('orgClassification')}
            />
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">National-interest classification (only if applicable)</h4>
            <ExclusiveCheckboxGrid
              options={NATIONAL_CLASSIFICATION}
              selected={form.nationalClassification}
              onChange={setExclusive('nationalClassification')}
            />
          </section>

          <section {...sectionProps(3)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">3</span>
              <h2 className="text-[16px] font-bold text-ink">Access level</h2>
            </div>
            <p className="text-[13px] leading-snug text-ink-soft">Pick the most restrictive level that governs the dataset.</p>
            <ExclusiveCheckboxGrid options={ACCESS_LEVELS} selected={form.accessLevel} onChange={setExclusive('accessLevel')} />
            <Field label="If a more open subset is published separately, what and at what aggregation">
              <input
                className={inputClass}
                type="text"
                value={form.moreOpenSubset}
                onChange={setText('moreOpenSubset')}
                placeholder="e.g. District-level dashboard extract"
              />
            </Field>
            <Field label="If Restricted: sharing partner">
              <input
                className={inputClass}
                type="text"
                value={form.restrictedSharingPartner}
                onChange={setText('restrictedSharingPartner')}
                placeholder="Agency or partner name"
              />
            </Field>
            <Field label="If Embargoed: release trigger and responsible authority">
              <input
                className={inputClass}
                type="text"
                value={form.embargoedRelease}
                onChange={setText('embargoedRelease')}
                placeholder="Trigger and authority"
              />
            </Field>
          </section>

          <section {...sectionProps(4)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">4</span>
              <h2 className="text-[16px] font-bold text-ink">Granularity</h2>
            </div>
            <p className="text-[13px] leading-snug text-ink-soft">Tick the finest level present.</p>
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Individual level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_INDIVIDUAL} selected={form.granularity} onChange={setExclusive('granularity')} />
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Local level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_LOCAL} selected={form.granularity} onChange={setExclusive('granularity')} />
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Regional level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_REGIONAL} selected={form.granularity} onChange={setExclusive('granularity')} />
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Statistical level</h4>
            <ExclusiveCheckboxGrid options={GRANULARITY_STATISTICAL} selected={form.granularity} onChange={setExclusive('granularity')} />

            <h3 className="mt-1.5 text-[13px] font-bold text-ink">Identifiability flags</h3>
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

          <section {...sectionProps(5)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">5</span>
              <h2 className="text-[16px] font-bold text-ink">Update frequency and retention</h2>
            </div>
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Update frequency</h4>
            <ExclusiveCheckboxGrid options={UPDATE_FREQUENCY} selected={form.updateFrequency} onChange={setExclusive('updateFrequency')} />
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Retention</h4>
            <ExclusiveCheckboxGrid options={RETENTION} selected={form.retention} onChange={setExclusive('retention')} />
            <Field label="Retention citation / purpose / event">
              <textarea
                className={textareaClass}
                value={form.retentionCitation}
                onChange={setText('retentionCitation')}
                placeholder="e.g. Rule X of Y Rules, 8 years from closure"
              />
            </Field>
          </section>

          <section {...sectionProps(6)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">6</span>
              <h2 className="text-[16px] font-bold text-ink">Storage</h2>
            </div>
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Offline</h4>
            <CheckboxGrid options={STORAGE_OFFLINE} selected={form.storage} onToggle={setList('storage')} />
            <h4 className="mt-1 text-[11px] font-bold uppercase tracking-wide text-[#8E9398]">Online</h4>
            <CheckboxGrid options={STORAGE_ONLINE} selected={form.storage} onToggle={setList('storage')} />
          </section>

          <section {...sectionProps(7)}>
            <div className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-teal text-xs font-bold text-white">7</span>
              <h2 className="text-[16px] font-bold text-ink">Notes and lawful basis</h2>
              <span className="ml-auto rounded-full bg-sage px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-[#3d5230]">Optional</span>
            </div>
            <Field label="If Restricted access — lawful basis cited">
              <textarea
                className={textareaClass}
                value={form.restrictedLawfulBasis}
                onChange={setText('restrictedLawfulBasis')}
                placeholder="Cite the statute or exemption — an MOU alone is not a lawful basis"
              />
            </Field>
            <Field label="If Special-category — sectoral / constitutional basis cited">
              <textarea
                className={textareaClass}
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
                className={textareaClass}
                value={form.notes}
                onChange={setText('notes')}
                placeholder="Any additional characterisation notes"
              />
            </Field>
          </section>
        </div>

        <div className="flex flex-shrink-0 items-center justify-end gap-2 border-t border-line bg-white px-5 py-3">
          {saveError && <span className="mr-auto text-[12.5px] text-[#b3261e]">{saveError}</span>}
          <button type="button" className="rounded-[7px] border border-line bg-cream px-4 py-2 text-[13px] font-semibold text-ink hover:bg-outer-bg" onClick={onSkip}>
            {editing ? 'Cancel' : 'Skip for now'}
          </button>
          <button
            type="button"
            className="rounded-[7px] bg-teal px-5 py-2 text-[13px] font-bold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:opacity-50"
            disabled={saving}
            onClick={async () => {
              if (savingRef.current) return
              savingRef.current = true
              setSaving(true)
              setSaveError('')
              try {
                await onSave(form)
                // Success: the caller is expected to unmount this modal.
              } catch (e) {
                setSaveError(e?.message || 'Could not save — please try again.')
              } finally {
                savingRef.current = false
                setSaving(false)
              }
            }}
          >
            {editing ? (saving ? 'Saving…' : 'Save changes') : 'Save & continue'}
          </button>
        </div>
      </div>
    </div>
  )
}
