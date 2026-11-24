import * as net from 'node:net'
import { DharaError, MSG, Ports } from './types'
import { PREFERRED_API_PORT, PREFERRED_PG_PORT } from './paths'
import { log } from './logger'

const LOOPBACK = '127.0.0.1'

/** True if something already accepts TCP connections on loopback:port. */
function somethingListening(port: number, timeoutMs = 400): Promise<boolean> {
  return new Promise((resolve) => {
    const sock = net.connect({ host: LOOPBACK, port })
    const done = (v: boolean) => {
      sock.destroy()
      resolve(v)
    }
    sock.setTimeout(timeoutMs)
    sock.once('connect', () => done(true))
    sock.once('timeout', () => done(false))
    sock.once('error', () => done(false))
  })
}

/** True if we can bind loopback:port (also false on EACCES from Windows reserved ranges). */
function canBind(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.once('error', () => resolve(false))
    srv.listen({ port, host: LOOPBACK, exclusive: true }, () => {
      srv.close(() => resolve(true))
    })
  })
}

export async function isPortFree(port: number): Promise<boolean> {
  if (await somethingListening(port)) return false
  return canBind(port)
}

/** Ask the OS for an ephemeral loopback port (listen(0) pattern). */
export function allocateEphemeralPort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.once('error', reject)
    srv.listen({ port: 0, host: LOOPBACK, exclusive: true }, () => {
      const addr = srv.address()
      const port = typeof addr === 'object' && addr ? addr.port : 0
      srv.close(() => (port ? resolve(port) : reject(new Error('no port allocated'))))
    })
  })
}

async function pickPort(preferred: number, avoid: number[], label: string): Promise<number> {
  if (!avoid.includes(preferred) && (await isPortFree(preferred))) {
    log.info(`${label}: using preferred port ${preferred}`)
    return preferred
  }
  for (let attempt = 0; attempt < 8; attempt++) {
    const p = await allocateEphemeralPort()
    if (!avoid.includes(p)) {
      log.warn(`${label}: preferred port ${preferred} busy, falling back to ${p}`)
      return p
    }
  }
  throw new DharaError('PORT', MSG.port, `${label}: could not allocate a free loopback port`)
}

export interface PortOverrides {
  /** Reuse an already-running Postgres' port (adoption). */
  postgres?: number
  /** Reuse an already-running API's port (adoption). */
  api?: number
}

export async function allocatePorts(overrides: PortOverrides = {}): Promise<Ports> {
  try {
    const postgres =
      overrides.postgres ?? (await pickPort(PREFERRED_PG_PORT, [], 'postgres'))
    const api =
      overrides.api ?? (await pickPort(PREFERRED_API_PORT, [postgres], 'api'))
    return { postgres, api }
  } catch (err) {
    if (err instanceof DharaError) throw err
    throw new DharaError('PORT', MSG.port, err instanceof Error ? err.message : String(err))
  }
}

export { LOOPBACK }
