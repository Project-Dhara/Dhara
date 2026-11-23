'use strict'

const http = require('http')
const { API_ORIGIN, UI_ORIGIN } = require('./paths')
const { ps, workerLogs } = require('./compose')

function httpGet(url, timeoutMs = 8000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let data = ''
      res.on('data', (c) => { data += c })
      res.on('end', () => {
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, body: data })
      })
    })
    req.on('error', (err) => resolve({ ok: false, error: err.message }))
    req.on('timeout', () => {
      req.destroy()
      resolve({ ok: false, error: 'timeout' })
    })
  })
}

async function checkApiReady() {
  const r = await httpGet(`${API_ORIGIN}/api/ready`)
  let json = null
  try { json = JSON.parse(r.body || '{}') } catch { /* ignore */ }
  const postgres = Boolean(json && json.checks && json.checks.postgres)
  const pgvector = Boolean(json && json.checks && json.checks.pgvector)
  return {
    ok: r.ok && json && json.status === 'ready' && postgres,
    postgres,
    pgvector,
    status: r.status,
    body: json,
    message: r.ok && postgres
      ? `API ready (pgvector=${pgvector})`
      : `API not ready: ${r.error || r.status}`,
  }
}

async function checkUi() {
  const home = await httpGet(`${UI_ORIGIN}/`)
  const live = await httpGet(`${UI_ORIGIN}/api/live`)
  return {
    ok: home.ok && live.ok,
    home: home.status,
    live: live.status,
    message: home.ok && live.ok
      ? 'UI and /api/live proxy OK'
      : `UI check failed (home=${home.status}, live=${live.status})`,
  }
}

async function checkWorker() {
  const status = await ps()
  const logs = await workerLogs()
  const text = `${status.stdout}\n${logs.stdout}\n${logs.stderr}`
  const up = /dhara-worker/i.test(text) && /running|up/i.test(text)
  const started = /Job worker started|job_worker|polling/i.test(text) || up
  return {
    ok: up || started,
    message: up || started
      ? 'Worker container is up'
      : 'Worker not confirmed — check docker compose logs worker',
    detail: text.slice(0, 2000),
  }
}

async function waitUntilHealthy({ timeoutMs = 300000, intervalMs = 4000, onTick } = {}) {
  const start = Date.now()
  let last = {}
  while (Date.now() - start < timeoutMs) {
    const api = await checkApiReady()
    const worker = await checkWorker()
    const ui = api.ok ? await checkUi() : { ok: false, message: 'Waiting for API first' }
    last = { api, worker, ui }
    if (onTick) onTick(last)
    if (api.ok && worker.ok && ui.ok) {
      return { ok: true, ...last }
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return { ok: false, message: 'Timed out waiting for Dhara stack health', ...last }
}

module.exports = {
  checkApiReady,
  checkUi,
  checkWorker,
  waitUntilHealthy,
  httpGet,
}
