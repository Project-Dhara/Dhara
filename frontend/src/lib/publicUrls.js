/**
 * Public absolute URLs for copy-paste Access API / MCP links.
 * Prefer the browser origin so the link matches whatever host is serving
 * the app (local, Cloud Run, custom domain). Optional NEXT_PUBLIC_APP_ORIGIN
 * overrides when the UI is behind a different public hostname.
 */
export function publicOrigin() {
  const fromEnv = (process.env.NEXT_PUBLIC_APP_ORIGIN || '').replace(/\/$/, '')
  if (fromEnv) return fromEnv
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin
  }
  return ''
}

export function publicMcpUrl() {
  const origin = publicOrigin()
  return origin ? `${origin}/mcp` : '/mcp'
}

export function publicApiDatasetsUrl(metadataId) {
  const origin = publicOrigin()
  const path = `/api/v1/datasets?metadata_id=${encodeURIComponent(metadataId || '')}`
  return origin ? `${origin}${path}` : path
}
