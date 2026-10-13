import { withAuthHeaders } from './auth'
import { withLlmKeyHeaders } from './llmKey'
import { datasetIdConfigPayload } from './settingsConfig'

const DATASET_EXT = /\.(pdf|xlsx|xls|csv)$/i

export function isDatasetFile(name) {
  return DATASET_EXT.test(name || '')
}

export function datasetSourceKind(name) {
  const n = (name || '').toLowerCase()
  if (/\.pdf$/i.test(n)) return 'pdf'
  if (/\.csv$/i.test(n)) return 'csv'
  if (/\.(xlsx|xls)$/i.test(n)) return 'excel'
  return null
}

/** True when the legacy single-PDF upload path should be used (exactly one PDF, nothing else). */
export function useSinglePdfUpload(files) {
  return files?.length === 1 && /\.pdf$/i.test(files[0]?.name || '')
}

function appendDatasetIdConfig(fd) {
  fd.append('dataset_id_config', JSON.stringify(datasetIdConfigPayload()))
}

export async function uploadDatasetBatch(files) {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  appendDatasetIdConfig(fd)
  const res = await fetch(
    '/api/upload/batch',
    withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })),
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = typeof err.detail === 'string'
      ? err.detail
      : Array.isArray(err.detail)
        ? err.detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
        : ''
    throw new Error(detail || `Upload failed (HTTP ${res.status})`)
  }
  return res.json()
}
