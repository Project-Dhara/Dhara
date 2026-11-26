import { withAuthHeaders } from './auth'

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
  const cd = res.headers.get('Content-Disposition') || ''
  const match = /filename="?([^"]+)"?/i.exec(cd)
  const fallback = `${String(title || id).replace(/[/\\?%*:|"<>]/g, '_')}_release.zip`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = match?.[1] || fallback
  a.click()
  URL.revokeObjectURL(url)
}
