import * as fs from 'node:fs'
import { safeStorage } from 'electron'
import { log } from './logger'
import { files } from './paths'

export interface StoredAuth {
  token: string
  user: unknown
}

const MAX_TOKEN_CHARS = 16 * 1024
const MAX_USER_JSON_CHARS = 64 * 1024

/**
 * Desktop session storage. localStorage is scoped to http://127.0.0.1:<port>, so a port fallback
 * would otherwise sign the user out. The token + user blob are encrypted with Electron safeStorage
 * (Windows DPAPI) and kept in %LOCALAPPDATA%\Dhara\auth.bin.
 */
export function getAuth(): StoredAuth | null {
  const p = files.authBlob()
  if (!fs.existsSync(p)) return null
  if (!safeStorage.isEncryptionAvailable()) return null
  try {
    const plain = safeStorage.decryptString(fs.readFileSync(p))
    const parsed = JSON.parse(plain) as StoredAuth
    if (typeof parsed?.token !== 'string' || !parsed.token) return null
    return { token: parsed.token, user: parsed.user ?? null }
  } catch (err) {
    log.warn(`auth blob unreadable, discarding: ${err instanceof Error ? err.message : String(err)}`)
    clearAuth()
    return null
  }
}

export function setAuth(value: unknown): boolean {
  if (!safeStorage.isEncryptionAvailable()) {
    log.warn('safeStorage unavailable — refusing to persist auth in plain text')
    return false
  }
  const v = value as Partial<StoredAuth> | null
  if (!v || typeof v.token !== 'string' || !v.token || v.token.length > MAX_TOKEN_CHARS) {
    throw new Error('Invalid auth payload')
  }
  const userJson = JSON.stringify(v.user ?? null)
  if (userJson.length > MAX_USER_JSON_CHARS) throw new Error('Auth user payload too large')
  const blob = safeStorage.encryptString(JSON.stringify({ token: v.token, user: v.user ?? null }))
  const p = files.authBlob()
  const tmp = `${p}.tmp`
  fs.writeFileSync(tmp, blob, { mode: 0o600 })
  fs.renameSync(tmp, p)
  return true
}

export function clearAuth(): void {
  try {
    fs.rmSync(files.authBlob(), { force: true })
  } catch (err) {
    log.warn(`could not delete auth blob: ${String(err)}`)
  }
}
