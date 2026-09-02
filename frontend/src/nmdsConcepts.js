// NMDS 2.0 concept metadata template — one row per "Concept Name" from the
// standard nmds_concept_meta_data sheet. Rows with no `parent` are section
// headers (rendered as dividers, no input); the rest are fields the user
// fills in (or that get prefilled from an uploaded concept metadata file).
export const NMDS_CONCEPT_TEMPLATE = [
  { item_no: '1', concept: 'Contact', section: true },
  { item_no: '1.1', concept: 'Contact Organisation' },
  { item_no: '1.2', concept: 'Compiling agency' },
  { item_no: '1.3', concept: 'Custodian agency' },
  { item_no: '1.4', concept: 'Contact Details' },

  { item_no: '2', concept: 'Data description and Presentation', section: true },
  { item_no: '2.1', concept: 'Data description' },
  { item_no: '2.2', concept: 'System of Classification' },
  { item_no: '2.3', concept: 'International/National Standards classification etc' },
  { item_no: '2.4', concept: 'Sector coverage' },
  { item_no: '2.5', concept: 'Concepts and definitions' },
  { item_no: '2.6', concept: 'Unit of compilation' },
  { item_no: '2.7', concept: 'Population coverage' },
  { item_no: '2.8', concept: 'Reference Period' },
  { item_no: '2.9', concept: 'Duration and Period of enumeration' },
  { item_no: '2.10', concept: 'Sample size / Dataset size' },
  { item_no: '2.11', concept: 'Data Confidentiality' },

  { item_no: '3', concept: 'Institutional Mandate', section: true },
  { item_no: '3.1', concept: 'Legal acts and other agreements' },
  { item_no: '3.2', concept: 'Data sharing/Data Dissemination' },
  { item_no: '3.3', concept: 'Release calendar' },
  { item_no: '3.4', concept: 'Frequency of dissemination' },
  { item_no: '3.5', concept: 'Data access' },

  { item_no: '4', concept: 'Quality Management', section: true },
  { item_no: '4.1', concept: 'Documentation on methodology' },
  { item_no: '4.2', concept: 'Quality documentation' },
  { item_no: '4.3', concept: 'Quality assurance' },

  { item_no: '5', concept: 'Accuracy and Reliability', section: true },
  { item_no: '5.1', concept: 'Sampling error' },
  { item_no: '5.2', concept: 'Measures of reliability' },

  { item_no: '6', concept: 'Timeliness', section: true },
  { item_no: '6.1', concept: 'Timeliness' },

  { item_no: '7', concept: 'Coherence/Comparability', section: true },
  { item_no: '7.1', concept: 'Comparability – over time' },
  { item_no: '7.2', concept: 'Coherence' },

  { item_no: '8', concept: 'Data Processing', section: true },
  { item_no: '8.1', concept: 'Source data type' },
  { item_no: '8.2', concept: 'Frequency of data collection' },
  { item_no: '8.3', concept: 'Mode and method of data collection method' },
  { item_no: '8.4', concept: 'Data validation' },
  { item_no: '8.5', concept: 'Data compilation' },
  { item_no: '8.6', concept: 'Data identifier(s)' },

  { item_no: '9', concept: 'Metadata Update', section: true },
  { item_no: '9.1', concept: 'Metadata last posted' },
  { item_no: '9.2', concept: 'Metadata last update' },
]

// Groups the flat template into one topic per section header, each holding
// its own sub-items — lets the NMDS concept step show one topic at a time
// instead of one long scroll of every concept.
export const NMDS_TOPICS = NMDS_CONCEPT_TEMPLATE.reduce((topics, row) => {
  if (row.section) {
    topics.push({ item_no: row.item_no, title: row.concept, items: [] })
  } else {
    topics[topics.length - 1].items.push(row)
  }
  return topics
}, [])

export function emptyNmdsFields() {
  const fields = {}
  for (const row of NMDS_CONCEPT_TEMPLATE) {
    if (!row.section) fields[row.concept] = ''
  }
  return fields
}

export function isNmdsFieldsComplete(fields) {
  return NMDS_CONCEPT_TEMPLATE
    .filter((row) => !row.section)
    .every((row) => (fields[row.concept] || '').trim())
}

// Turns the {concept: details} field map back into the flat list shape the
// backend already understands (see backend/metadata_excel.py parse_concepts).
export function nmdsFieldsToList(fields) {
  return NMDS_CONCEPT_TEMPLATE
    .filter((row) => !row.section)
    .map((row) => ({ item_no: row.item_no, concept: row.concept, details: fields[row.concept] || '' }))
    .filter((row) => row.details.trim())
}

// Merges a parsed concept list (from an uploaded file, keyed by concept
// name) into a {concept: details} field map, filling in only known concepts.
export function mergeNmdsConcepts(fields, parsedList) {
  const next = { ...fields }
  for (const row of parsedList || []) {
    const concept = row.concept
    if (concept && concept in next && row.details) next[concept] = String(row.details)
  }
  return next
}
