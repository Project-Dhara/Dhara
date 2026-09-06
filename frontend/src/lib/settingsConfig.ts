const DATASET_ID_KEY = 'dhara.datasetIdConfig'
const METADATA_REQUIRED_KEY = 'dhara.metadataRequiredFields'

export const STATISTICS_OPTIONS = ['Vital Statistics', 'Labour Statistics', 'Industrial Statistics']

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
