import crypto from 'node:crypto'
import fs from 'node:fs'
import type { DharaPaths } from './paths'

export type RuntimeConfig = {
  jwtSecret: string
  pgPassword: string
  pgUser: string
  pgDatabase: string
  preferredPgPort: number
  preferredBackendPort: number
  preferredUiPort: number
}

const DEFAULTS: Omit<RuntimeConfig, 'jwtSecret' | 'pgPassword'> = {
  pgUser: 'dhara',
  pgDatabase: 'dhara',
  preferredPgPort: 55432,
  preferredBackendPort: 18000,
  preferredUiPort: 18080,
}

export function loadOrCreateRuntimeConfig(paths: DharaPaths): RuntimeConfig {
  if (fs.existsSync(paths.runtimeConfig)) {
    const raw = JSON.parse(fs.readFileSync(paths.runtimeConfig, 'utf8')) as Partial<RuntimeConfig>
    return {
      ...DEFAULTS,
      jwtSecret: String(raw.jwtSecret || crypto.randomBytes(32).toString('hex')),
      pgPassword: String(raw.pgPassword || crypto.randomBytes(18).toString('base64url')),
      pgUser: String(raw.pgUser || DEFAULTS.pgUser),
      pgDatabase: String(raw.pgDatabase || DEFAULTS.pgDatabase),
      preferredPgPort: Number(raw.preferredPgPort || DEFAULTS.preferredPgPort),
      preferredBackendPort: Number(raw.preferredBackendPort || DEFAULTS.preferredBackendPort),
      preferredUiPort: Number(raw.preferredUiPort || DEFAULTS.preferredUiPort),
    }
  }

  const created: RuntimeConfig = {
    ...DEFAULTS,
    jwtSecret: crypto.randomBytes(32).toString('hex'),
    pgPassword: crypto.randomBytes(18).toString('base64url'),
  }
  fs.writeFileSync(paths.runtimeConfig, JSON.stringify(created, null, 2), 'utf8')
  return created
}

export function databaseUrl(cfg: RuntimeConfig, pgPort: number): string {
  const user = encodeURIComponent(cfg.pgUser)
  const pass = encodeURIComponent(cfg.pgPassword)
  return `postgresql://${user}:${pass}@127.0.0.1:${pgPort}/${cfg.pgDatabase}`
}
