import { withAuthHeaders } from './auth'

function saveZipBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function filenameFromResponse(res, title, id) {
  const cd = res.headers.get('Content-Disposition') || ''
  const match = /filename="?([^"]+)"?/i.exec(cd)
  const fallback = `${String(title || id).replace(/[/\\?%*:|"<>]/g, '_')}_release.zip`
  return match?.[1] || fallback
}

/**
 * Download the published release ZIP for a metadata group
 * (tables + Metadata + NMDS sheets per workbook).
 * @returns {Promise<void>}
 */
export async function downloadCatalogueGroupZip(metadataId, title = '') {
  const id = String(metadataId || '').trim()
  if (!id) {
    throw new Error('No published release id to download')
  }
  const res = await fetch(
    `/api/catalogue/groups/${encodeURIComponent(id)}/download`,
    withAuthHeaders(),
  )
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `Download failed (${res.status})`)
  }
  const blob = await res.blob()
  saveZipBlob(blob, filenameFromResponse(res, title, id))
}

/**
 * Download one ZIP for every table across all metadata groups in a publish session.
 * @param {string[]} metadataIds
 * @param {string} [title]
 * @returns {Promise<void>}
 */
export async function downloadCatalogueGroupsZip(metadataIds, title = '') {
  const ids = (Array.isArray(metadataIds) ? metadataIds : [metadataIds])
    .map((id) => String(id || '').trim())
    .filter(Boolean)
  const unique = [...new Set(ids)]
  if (!unique.length) {
    throw new Error('No published release ids to download')
  }
  if (unique.length === 1) {
    return downloadCatalogueGroupZip(unique[0], title)
  }
  const res = await fetch(
    '/api/catalogue/groups/download',
    withAuthHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metadata_ids: unique }),
    }),
  )
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `Download failed (${res.status})`)
  }
  const blob = await res.blob()
  saveZipBlob(blob, filenameFromResponse(res, title, unique[0]))
}
