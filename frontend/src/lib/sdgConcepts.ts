// SDG indicator metadata — from the UN SDG metadata template.
// Rows with `section: true` are dividers (no input); the rest are fillable fields.
export const SDG_CONCEPT_TEMPLATE = [
  { concept: 'Indicator information', code: 'SDG_INDICATOR_INFO', section: true },
  { concept: 'Goal', code: 'SDG_GOAL' },
  { concept: 'Target', code: 'SDG_TARGET' },
  { concept: 'Indicator', code: 'SDG_INDICATOR' },
  { concept: 'Series', code: 'SDG_SERIES_DESCR' },
  { concept: 'Metadata update', code: 'META_LAST_UPDATE' },
  { concept: 'Related indicators', code: 'SDG_RELATED_INDICATORS' },
  {
    concept: 'International organisations(s) responsible for global monitoring',
    code: 'SDG_CUSTODIAN_AGENCIES',
  },
]

// Example values from the UN SDG metadata site (Goal 3 / Target 3.b / Indicator 3.b.2).
export const SDG_FIELD_PLACEHOLDERS = {
  Goal: 'Goal 3: Ensure healthy lives and promote well-being for all at all ages',
  Target:
    'Target 3.b: Support the research and development of vaccines and medicines for the communicable and non‑communicable diseases that primarily affect developing countries, provide access to affordable essential medicines and vaccines, in accordance with the Doha Declaration on the TRIPS Agreement and Public Health, which affirms the right of developing countries to use to the full the provisions in the Agreement on Trade-Related Aspects of Intellectual Property Rights regarding flexibilities to protect public health, and, in particular, provide access to medicines for all',
  Indicator:
    'Indicator 3.b.2: Total net official development assistance to medical research and basic health sectors',
  Series:
    'DC_TOF_HLTHL - Total official development assistance to medical research and basic heath sectors, gross disbursement, by recipient countries [3.b.2]\nDC_TOF_HLTHNT - Total official development assistance to medical research and basic heath sectors, net disbursement, by recipient countries [3.b.2]',
  'Metadata update': '2025-12-12',
  'Related indicators': 'Other ODA indicators',
  'International organisations(s) responsible for global monitoring':
    'Organisation for Economic Co-operation and Development (OECD)',
}

export const SDG_TOPICS = SDG_CONCEPT_TEMPLATE.reduce((topics, row) => {
  if (row.section) {
    topics.push({ title: row.concept, code: row.code, items: [] })
  } else {
    topics[topics.length - 1].items.push(row)
  }
  return topics
}, [])

export function emptySdgFields() {
  const fields = {}
  for (const row of SDG_CONCEPT_TEMPLATE) {
    if (!row.section) fields[row.concept] = ''
  }
  return fields
}

export function isSdgFieldsComplete(fields) {
  return SDG_CONCEPT_TEMPLATE
    .filter((row) => !row.section)
    .every((row) => (fields[row.concept] || '').trim())
}

export function sdgFieldsToList(fields) {
  return SDG_CONCEPT_TEMPLATE
    .filter((row) => !row.section)
    .map((row) => ({
      concept: row.concept,
      code: row.code,
      details: fields[row.concept] || '',
    }))
    .filter((row) => row.details.trim())
}

export function mergeSdgConcepts(fields, parsedList) {
  const next = { ...fields }
  const byConcept = new Map(
    SDG_CONCEPT_TEMPLATE.filter((r) => !r.section).map((r) => [r.concept.toLowerCase(), r.concept]),
  )
  const byCode = new Map(
    SDG_CONCEPT_TEMPLATE.filter((r) => !r.section && r.code).map((r) => [r.code.toLowerCase(), r.concept]),
  )
  for (const row of parsedList || []) {
    const conceptKey = String(row.concept || '').trim()
    const codeKey = String(row.code || '').trim()
    const mapped =
      (conceptKey && byConcept.get(conceptKey.toLowerCase())) ||
      (codeKey && byCode.get(codeKey.toLowerCase())) ||
      (conceptKey && byCode.get(conceptKey.toLowerCase()))
    if (mapped && row.details) next[mapped] = String(row.details)
  }
  return next
}

/** Columns for the metadata review grid when SDG is the active standard. */
export const SDG_METADATA_COLUMNS = SDG_CONCEPT_TEMPLATE.filter((row) => !row.section).map((row) => ({
  key: row.concept,
  label: row.concept,
  code: row.code,
  type: 'long',
  placeholder: SDG_FIELD_PLACEHOLDERS[row.concept] || `Details for ${row.concept}`,
  required: true,
}))
