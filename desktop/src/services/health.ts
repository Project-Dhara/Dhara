import http from 'node:http'
import net from 'node:net'

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function waitForTcp(
  host: string,
  port: number,
  timeoutMs = 60_000,
  intervalMs = 400,
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastError = 'not attempted'
  while (Date.now() < deadline) {
    try {
      await new Promise<void>((resolve, reject) => {
        const socket = net.connect({ host, port }, () => {
          socket.end()
          resolve()
        })
        socket.on('error', reject)
        socket.setTimeout(1500, () => {
          socket.destroy()
          reject(new Error('timeout'))
        })
      })
      return
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err)
      await sleep(intervalMs)
    }
  }
  throw new Error(`Timed out waiting for ${host}:${port} (${lastError})`)
}

export async function waitForHttpOk(
  url: string,
  timeoutMs = 120_000,
  intervalMs = 500,
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastError = 'not attempted'
  while (Date.now() < deadline) {
    try {
      const status = await httpGetStatus(url)
      if (status >= 200 && status < 300) return
      lastError = `HTTP ${status}`
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err)
    }
    await sleep(intervalMs)
  }
  throw new Error(`Timed out waiting for ${url} (${lastError})`)
}

function httpGetStatus(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      res.resume()
      resolve(res.statusCode || 0)
    })
    req.on('error', reject)
    req.setTimeout(3000, () => {
      req.destroy(new Error('timeout'))
    })
  })
}

export async function allocatePort(preferred: number): Promise<number> {
  if (await isPortFree(preferred)) return preferred
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      if (!addr || typeof addr === 'string') {
        server.close()
        reject(new Error('Failed to allocate ephemeral port'))
        return
      }
      const port = addr.port
      server.close(() => resolve(port))
    })
    server.on('error', reject)
  })
}

function isPortFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.once('error', () => resolve(false))
    server.once('listening', () => {
      server.close(() => resolve(true))
    })
    server.listen(port, '127.0.0.1')
  })
}
