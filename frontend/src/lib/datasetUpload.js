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

function fileFromBytes(name, bytes, file) {
  const raw = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  if (!raw.byteLength) {
    throw new Error(
      `${name} is empty (0 bytes). If it is a OneDrive/SharePoint cloud-only file, open it once in Excel to download it, or copy it to Desktop/Downloads and upload that copy.`,
    )
  }
  return new File([raw], name, {
    type: (file && file.type) || 'application/octet-stream',
    lastModified: (file && file.lastModified) || Date.now(),
  })
}

/**
 * Read file bytes into a new File so multipart uploads carry a real body.
 * In Dhara Desktop (Electron), File.arrayBuffer() often returns 0 bytes even for
 * real Excel files — prefer reading via the desktop bridge (disk path).
 */
export async function materializeFile(file) {
  if (!file) throw new Error('No file selected')

  const desktop =
    typeof window !== 'undefined' && window.dharaDesktop && typeof window.dharaDesktop.readUploadFile === 'function'
      ? window.dharaDesktop
      : null

  if (desktop) {
    try {
      const got = await desktop.readUploadFile(file)
      return fileFromBytes(got.name || file.name, got.bytes, file)
    } catch (err) {
      const why = err && err.message ? err.message : String(err)
      // Disk said empty / missing — do not fall back to empty browser File.
      if (/empty on disk|not found|unsupported upload|too large/i.test(why)) {
        throw new Error(why)
      }
      // Path resolution failed — try browser read below.
    }
  }

  let buf
  try {
    buf = await file.arrayBuffer()
  } catch (err) {
    const why = err && err.message ? err.message : String(err)
    throw new Error(
      `${file.name}: could not read file (${why}). Copy it to a local folder and try again.`,
    )
  }
  return fileFromBytes(file.name, buf, file)
}

export async function materializeFiles(files) {
  const list = Array.from(files || [])
  const out = []
  for (const f of list) out.push(await materializeFile(f))
  return out
}

/** Dedup key — include lastModified so size-0 Electron picks still allow distinct files. */
export function samePendingFile(a, b) {
  if (!a || !b || a.name !== b.name) return false
  if (a.size !== b.size) return false
  return (a.lastModified || 0) === (b.lastModified || 0)
}

function appendDatasetIdConfig(fd) {
  fd.append('dataset_id_config', JSON.stringify(datasetIdConfigPayload()))
}

async function readUploadError(res) {
  const err = await res.json().catch(() => ({}))
  const detail = typeof err.detail === 'string'
    ? err.detail
    : Array.isArray(err.detail)
      ? err.detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
      : ''
  return detail || `Upload failed (HTTP ${res.status})`
}

export async function uploadDatasetBatch(files) {
  const ready = await materializeFiles(files)
  const fd = new FormData()
  ready.forEach((f) => fd.append('files', f))
  appendDatasetIdConfig(fd)
  const res = await fetch(
    '/api/upload/batch',
    withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })),
  )
  if (!res.ok) throw new Error(await readUploadError(res))
  return res.json()
}

/** Append files to an existing extract/batch job; prior tables are kept. */
export async function appendDatasetBatch(jobId, files) {
  const ready = await materializeFiles(files)
  const fd = new FormData()
  ready.forEach((f) => fd.append('files', f))
  appendDatasetIdConfig(fd)
  const res = await fetch(
    `/api/upload/batches/${encodeURIComponent(jobId)}/files`,
    withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })),
  )
  if (!res.ok) throw new Error(await readUploadError(res))
  return res.json()
}
