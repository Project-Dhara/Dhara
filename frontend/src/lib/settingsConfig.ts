const DATASET_ID_KEY = 'dhara.datasetIdConfig'
const METADATA_REQUIRED_KEY = 'dhara.metadataRequiredFields'
const METADATA_STANDARD_KEY = 'dhara.metadataStandard'

export const STATISTICS_OPTIONS = ['Vital Statistics', 'Labour Statistics', 'Industrial Statistics']

export const METADATA_STANDARD_OPTIONS = [
  { value: 'nmds', label: 'NMDS' },
  { value: 'sdg', label: 'Sustainable Development Goals' },
] as const

export type MetadataStandard = (typeof METADATA_STANDARD_OPTIONS)[number]['value']

export const DEFAULT_METADATA_STANDARD: MetadataStandard = 'nmds'

export const DEFAULT_DATASET_ID_CONFIG = {
  prefix: 'DDI_DES_DEL',
  separator: '_',
  statistics: 'Vital Statistics',
}

export const DEFAULT_METADATA_REQUIRED_FIELDS = {
  product: true,
  description: true,
  owner: true,
  autoTagDomain: false,
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore (e.g. localStorage disabled)
  }
}

export function getDatasetIdConfig() {
  return { ...DEFAULT_DATASET_ID_CONFIG, ...readJson(DATASET_ID_KEY, {}) }
}

export function setDatasetIdConfig(config: unknown) {
  writeJson(DATASET_ID_KEY, config)
}

export function getMetadataRequiredFields() {
  const stored = readJson<typeof DEFAULT_METADATA_REQUIRED_FIELDS | null>(METADATA_REQUIRED_KEY, null)
  if (!stored) return { ...DEFAULT_METADATA_REQUIRED_FIELDS }
  return stored
}

export function setMetadataRequiredFields(fields: unknown) {
  writeJson(METADATA_REQUIRED_KEY, fields)
}

function isMetadataStandard(value: unknown): value is MetadataStandard {
  return METADATA_STANDARD_OPTIONS.some((opt) => opt.value === value)
}

export function getMetadataStandard(): MetadataStandard {
  try {
    const raw = localStorage.getItem(METADATA_STANDARD_KEY)
    if (!raw) return DEFAULT_METADATA_STANDARD
    const parsed = JSON.parse(raw)
    return isMetadataStandard(parsed) ? parsed : DEFAULT_METADATA_STANDARD
  } catch {
    return DEFAULT_METADATA_STANDARD
  }
}

export function setMetadataStandard(standard: MetadataStandard) {
  writeJson(METADATA_STANDARD_KEY, standard)
}
