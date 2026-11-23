'use strict'

const fs = require('fs')
const path = require('path')
const { run, spawnDetached } = require('./exec')
const { vendorDir } = require('./paths')

/** Official Docker Desktop Windows installer filename when bundled in vendor/. */
const DOCKER_INSTALLER_NAMES = [
  'Docker Desktop Installer.exe',
  'DockerDesktopInstaller.exe',
  'docker-desktop-installer.exe',
]

/** Verified official download (Docker docs). Used only when not bundled. */
const DOCKER_DESKTOP_DOWNLOAD_URL =
  'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'

async function dockerInfo() {
  const r = await run('docker', ['info'], { timeout: 60000 })
  return {
    ok: r.ok,
    stdout: r.stdout,
    stderr: r.stderr,
    message: r.ok ? 'Docker engine is running' : 'Docker engine is not reachable',
  }
}

async function dockerComposeVersion() {
  const r = await run('docker', ['compose', 'version'])
  return {
    ok: r.ok,
    stdout: r.stdout,
    message: r.ok ? String(r.stdout).trim() : 'docker compose not available',
  }
}

function findBundledDockerInstaller() {
  const dir = vendorDir()
  if (!fs.existsSync(dir)) return null
  for (const name of DOCKER_INSTALLER_NAMES) {
    const p = path.join(dir, name)
    if (fs.existsSync(p)) return p
  }
  const entries = fs.readdirSync(dir)
  const hit = entries.find((e) => /docker.*installer.*\.exe$/i.test(e))
  return hit ? path.join(dir, hit) : null
}

async function downloadDockerInstaller(destPath, onProgress) {
  // Real official URL only — no placeholders.
  const https = require('https')
  const url = require('url')
  await new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destPath)
    const get = (u, redirects = 0) => {
      https.get(u, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          if (redirects > 5) {
            reject(new Error('Too many redirects downloading Docker Desktop'))
            return
          }
          get(res.headers.location, redirects + 1)
          return
        }
        if (res.statusCode !== 200) {
          reject(new Error(`Docker Desktop download HTTP ${res.statusCode}`))
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
    get(DOCKER_DESKTOP_DOWNLOAD_URL)
  })
  return destPath
}

async function ensureDockerInstaller(onProgress) {
  const bundled = findBundledDockerInstaller()
  if (bundled) return { path: bundled, source: 'bundled' }
  const dest = path.join(vendorDir(), 'Docker Desktop Installer.exe')
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  if (fs.existsSync(dest) && fs.statSync(dest).size > 1_000_000) {
    return { path: dest, source: 'cached' }
  }
  await downloadDockerInstaller(dest, onProgress)
  return { path: dest, source: 'download', url: DOCKER_DESKTOP_DOWNLOAD_URL }
}

async function installDockerDesktop(installerPath) {
  // Quiet install per Docker Desktop Windows docs.
  const r = await run(installerPath, ['install', '--quiet', '--accept-license'], {
    timeout: 600000,
    shell: false,
  })
  return {
    ok: r.ok || r.code === 0,
    stdout: r.stdout,
    stderr: r.stderr,
    message: r.ok
      ? 'Docker Desktop installer finished'
      : `Docker Desktop install failed: ${r.stderr || r.stdout}`,
  }
}

function startDockerDesktop() {
  const candidates = [
    path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Docker', 'Docker', 'Docker Desktop.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Docker', 'Docker', 'Docker Desktop.exe'),
  ]
  for (const exe of candidates) {
    if (exe && fs.existsSync(exe)) {
      spawnDetached(exe, [])
      return { ok: true, path: exe }
    }
  }
  return { ok: false, message: 'Docker Desktop.exe not found after install' }
}

async function waitForDocker({ timeoutMs = 300000, intervalMs = 3000, onTick } = {}) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const info = await dockerInfo()
    const compose = await dockerComposeVersion()
    if (onTick) onTick({ info, compose, elapsed: Date.now() - start })
    if (info.ok && compose.ok) {
      return { ok: true, info, compose }
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return { ok: false, message: 'Timed out waiting for Docker engine' }
}

module.exports = {
  DOCKER_DESKTOP_DOWNLOAD_URL,
  dockerInfo,
  dockerComposeVersion,
  findBundledDockerInstaller,
  ensureDockerInstaller,
  installDockerDesktop,
  startDockerDesktop,
  waitForDocker,
}
