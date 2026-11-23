'use strict'

const fs = require('fs')
const { run, spawnDetached } = require('./exec')
const { wslConfigPath } = require('./paths')
const { writeState, readState } = require('./store')

/** Cap WSL VM memory for 8 GB hosts (~4.5 GB; tighter if local LLM). */
function writeWslConfig({ localLlm } = {}) {
  const memory = localLlm ? '4GB' : '5GB'
  const content = `[wsl2]
memory=${memory}
processors=2
swap=2GB
localhostForwarding=true
`
  const p = wslConfigPath()
  fs.writeFileSync(p, content, 'utf8')
  return { path: p, memory }
}

async function wslVersion() {
  const r = await run('wsl.exe', ['--version'])
  const text = `${r.stdout}\n${r.stderr}`
  const m = text.match(/WSL\s+version:\s*([\d.]+)/i) || text.match(/([\d]+)\.([\d]+)\.([\d]+)/)
  return { ok: r.ok || /version/i.test(text), text, match: m && m[0] }
}

async function isWslReady() {
  const ver = await wslVersion()
  if (!ver.ok) return { ok: false, message: 'WSL is not installed or not on PATH.' }
  const list = await run('wsl.exe', ['-l', '-v'])
  return {
    ok: list.ok || /VERSION/i.test(list.stdout + list.stderr),
    message: 'WSL present',
    detail: list.stdout || list.stderr,
  }
}

async function enableWslFeatures() {
  // Requires elevation. Uses DISM — real Windows commands, no dummy URLs.
  const features = [
    'Microsoft-Windows-Subsystem-Linux',
    'VirtualMachinePlatform',
  ]
  const results = []
  for (const name of features) {
    const r = await run('dism.exe', [
      '/online',
      `/Enable-Feature`,
      `/FeatureName:${name}`,
      '/All',
      '/NoRestart',
    ], { timeout: 300000 })
    results.push({ name, ok: r.ok || /already|enabled/i.test(r.stdout + r.stderr), stdout: r.stdout, stderr: r.stderr })
  }
  // Also run wsl --install --no-distribution when available (Win11+).
  const install = await run('wsl.exe', ['--install', '--no-distribution'], { timeout: 300000 })
  const needsReboot =
    results.some((x) => /restart|reboot/i.test(x.stdout + x.stderr)) ||
    /restart|reboot/i.test(install.stdout + install.stderr) ||
    install.code === 3010

  if (needsReboot) {
    writeState({ pendingResume: 'after-wsl', resumeStep: 'docker' })
  }
  return { results, install, needsReboot }
}

function scheduleResumeAfterReboot() {
  const state = readState()
  // RunOnce under HKCU — resumes Dhara after reboot without dummy links.
  const exe = process.execPath
  const args = '--resume-setup'
  return run('reg.exe', [
    'add',
    'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce',
    '/v',
    'DharaDesktopSetup',
    '/t',
    'REG_SZ',
    '/d',
    `"${exe}" ${args}`,
    '/f',
  ]).then((r) => ({ ok: r.ok, state }))
}

function requestReboot() {
  spawnDetached('shutdown.exe', ['/r', '/t', '5', '/c', 'Dhara Setup: reboot to finish WSL install'])
}

module.exports = {
  writeWslConfig,
  wslVersion,
  isWslReady,
  enableWslFeatures,
  scheduleResumeAfterReboot,
  requestReboot,
}
