'use strict'

const fs = require('fs')
const path = require('path')
const http = require('http')
const { run, spawnDetached } = require('./exec')
const { vendorDir, downloadCacheDir, OLLAMA_ORIGIN, DEFAULT_OLLAMA_MODEL } = require('./paths')

const OLLAMA_INSTALLER_NAMES = ['OllamaSetup.exe', 'OllamaSetup-windows.exe']

/** Official Windows installer download (ollama.com). */
const OLLAMA_DOWNLOAD_URL = 'https://ollama.com/download/OllamaSetup.exe'

function httpGetJson(url, timeoutMs = 10000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let data = ''
      res.on('data', (c) => { data += c })
      res.on('end', () => {
        try {
          resolve({ ok: res.statusCode === 200, status: res.statusCode, json: JSON.parse(data), raw: data })
        } catch {
          resolve({ ok: res.statusCode === 200, status: res.statusCode, json: null, raw: data })
        }
      })
    })
    req.on('error', (err) => resolve({ ok: false, error: err.message }))
    req.on('timeout', () => {
      req.destroy()
      resolve({ ok: false, error: 'timeout' })
    })
  })
}

async function ollamaTags() {
  return httpGetJson(`${OLLAMA_ORIGIN}/api/tags`)
}

async function isOllamaReady() {
  const tags = await ollamaTags()
  return {
    ok: Boolean(tags.ok),
    message: tags.ok ? 'Ollama is running' : 'Ollama is not reachable on 127.0.0.1:11434',
    tags: tags.json,
  }
}

function findInstallerInDir(dir) {
  if (!dir || !fs.existsSync(dir)) return null
  for (const name of OLLAMA_INSTALLER_NAMES) {
    const p = path.join(dir, name)
    if (fs.existsSync(p)) return p
  }
  const hit = fs.readdirSync(dir).find((e) => /ollama.*\.exe$/i.test(e))
  return hit ? path.join(dir, hit) : null
}

function findBundledOllamaInstaller() {
  return findInstallerInDir(vendorDir()) || findInstallerInDir(downloadCacheDir())
}

async function downloadOllamaInstaller(destPath, onProgress) {
  const https = require('https')
  await new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destPath)
    const get = (u, redirects = 0) => {
      https.get(u, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          if (redirects > 5) {
            reject(new Error('Too many redirects downloading Ollama'))
            return
          }
          get(res.headers.location, redirects + 1)
          return
        }
        if (res.statusCode !== 200) {
          reject(new Error(`Ollama download HTTP ${res.statusCode}`))
          return
        }
        const total = parseInt(res.headers['content-length'] || '0', 10)
        let got = 0
        res.on('data', (chunk) => {
          got += chunk.length
          if (onProgress && total) onProgress(got / total)
        })
        res.pipe(file)
        file.on('finish', () => file.close(resolve))
      }).on('error', reject)
    }
    get(OLLAMA_DOWNLOAD_URL)
  })
  return destPath
}

async function ensureOllamaInstaller(onProgress) {
  const bundled = findInstallerInDir(vendorDir())
  if (bundled) return { path: bundled, source: 'bundled' }
  const dest = path.join(downloadCacheDir(), 'OllamaSetup.exe')
  if (fs.existsSync(dest) && fs.statSync(dest).size > 1_000_000) {
    return { path: dest, source: 'cached' }
  }
  await downloadOllamaInstaller(dest, onProgress)
  return { path: dest, source: 'download', url: OLLAMA_DOWNLOAD_URL }
}

async function installOllama(installerPath) {
  const r = await run(installerPath, ['/SILENT'], { timeout: 600000, shell: false })
  return {
    ok: r.ok || r.code === 0,
    stdout: r.stdout,
    stderr: r.stderr,
    message: r.ok ? 'Ollama installer finished' : `Ollama install may need a moment: ${r.stderr || r.stdout}`,
  }
}

function startOllama() {
  const candidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Ollama', 'ollama.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Ollama', 'ollama app.exe'),
    'ollama',
  ]
  for (const exe of candidates) {
    if (exe === 'ollama') {
      spawnDetached('ollama', ['serve'])
      return { ok: true, path: 'ollama' }
    }
    if (fs.existsSync(exe)) {
      spawnDetached(exe, ['serve'])
      return { ok: true, path: exe }
    }
  }
  return { ok: false, message: 'ollama.exe not found' }
}

async function waitForOllama({ timeoutMs = 180000, intervalMs = 2000 } = {}) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const ready = await isOllamaReady()
    if (ready.ok) return ready
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return { ok: false, message: 'Timed out waiting for Ollama' }
}

async function pullModel(model = DEFAULT_OLLAMA_MODEL) {
  const r = await run('ollama', ['pull', model], { timeout: 600000 })
  return {
    ok: r.ok,
    stdout: r.stdout,
    stderr: r.stderr,
    message: r.ok ? `Pulled model ${model}` : `Failed to pull ${model}: ${r.stderr || r.stdout}`,
    model,
  }
}

module.exports = {
  OLLAMA_DOWNLOAD_URL,
  DEFAULT_OLLAMA_MODEL,
  ollamaTags,
  isOllamaReady,
  ensureOllamaInstaller,
  installOllama,
  startOllama,
  waitForOllama,
  pullModel,
}
