'use strict'

const os = require('os')
const fs = require('fs')
const { run } = require('./exec')

const MIN_RAM_GB = 8
const MIN_DISK_GB = 20
const MIN_WIN10_BUILD = 19045
const MIN_WIN11_BUILD = 22631

function totalRamGb() {
  return Math.round((os.totalmem() / (1024 ** 3)) * 10) / 10
}

function freeRamGb() {
  return Math.round((os.freemem() / (1024 ** 3)) * 10) / 10
}

function freeDiskGb(targetPath) {
  try {
    const s = fs.statfsSync(targetPath || process.cwd())
    return Math.round(((s.bavail * s.bsize) / (1024 ** 3)) * 10) / 10
  } catch {
    return null
  }
}

async function windowsBuild() {
  if (process.platform !== 'win32') {
    return { ok: false, message: 'Dhara Desktop v1 supports Windows only.' }
  }
  const r = await run('powershell.exe', [
    '-NoProfile',
    '-Command',
    '[System.Environment]::OSVersion.Version.Build',
  ])
  const build = parseInt(String(r.stdout || '').trim(), 10)
  if (!Number.isFinite(build)) {
    return { ok: false, message: 'Could not read Windows build number.', build: null }
  }
  // Win11 starts at 22000; require 23H2 (22631). Win10 require 22H2 (19045).
  const isWin11 = build >= 22000
  const min = isWin11 ? MIN_WIN11_BUILD : MIN_WIN10_BUILD
  if (build < min) {
    return {
      ok: false,
      build,
      message: `Windows build ${build} is too old. Need ${isWin11 ? 'Windows 11 23H2+' : 'Windows 10 22H2+'} (build ≥ ${min}).`,
    }
  }
  return { ok: true, build, message: `Windows build ${build}` }
}

async function virtualizationEnabled() {
  if (process.platform !== 'win32') return { ok: true, message: 'n/a' }
  const r = await run('powershell.exe', [
    '-NoProfile',
    '-Command',
    "(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled",
  ])
  const v = String(r.stdout || '').trim().toLowerCase()
  if (v === 'true') return { ok: true, message: 'Firmware virtualization enabled' }
  if (v === 'false') {
    return {
      ok: false,
      message:
        'Hardware virtualization is disabled in BIOS/UEFI. Enable Intel VT-x / AMD-V, then reboot.',
    }
  }
  return { ok: true, message: 'Virtualization status unknown — continuing' }
}

async function portInUse(port) {
  if (process.platform !== 'win32') {
    const r = await run('bash', ['-lc', `ss -ltn 'sport = :${port}' | tail -n +2`])
    return Boolean(String(r.stdout || '').trim())
  }
  const r = await run('powershell.exe', [
    '-NoProfile',
    '-Command',
    `@(Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue).Count`,
  ])
  const n = parseInt(String(r.stdout || '').trim(), 10)
  return Number.isFinite(n) && n > 0
}

async function checkPorts(ports = [8080, 8000, 5432]) {
  const busy = []
  for (const p of ports) {
    if (await portInUse(p)) busy.push(p)
  }
  if (busy.length) {
    return {
      ok: false,
      busy,
      message: `Ports in use: ${busy.join(', ')}. Stop IIS/Skype/local Postgres or remapping is required.`,
    }
  }
  return { ok: true, busy: [], message: 'Ports 8080, 8000, 5432 are free' }
}

async function pageFileWarning() {
  if (process.platform !== 'win32') return { ok: true, warn: false, message: '' }
  const r = await run('powershell.exe', [
    '-NoProfile',
    '-Command',
    '(Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue | Measure-Object).Count',
  ])
  const n = parseInt(String(r.stdout || '').trim(), 10)
  if (Number.isFinite(n) && n === 0) {
    return {
      ok: true,
      warn: true,
      message: 'Windows page file appears disabled. Enable it for smoother PDF/LLM spikes on 8 GB RAM.',
    }
  }
  return { ok: true, warn: false, message: 'Page file present or unknown' }
}

async function runPreflight() {
  const checks = []
  const win = await windowsBuild()
  checks.push({ id: 'windows', ...win })

  const ram = totalRamGb()
  const free = freeRamGb()
  checks.push({
    id: 'ram',
    ok: ram >= MIN_RAM_GB,
    message:
      ram >= MIN_RAM_GB
        ? `System RAM ${ram} GB (free ~${free} GB). Close other apps during setup if free RAM is low.`
        : `Only ${ram} GB RAM detected. Dhara Desktop needs at least ${MIN_RAM_GB} GB.`,
    ram,
    free,
  })

  const disk = freeDiskGb(process.env.SystemDrive || 'C:\\')
  checks.push({
    id: 'disk',
    ok: disk == null || disk >= MIN_DISK_GB,
    message:
      disk == null
        ? 'Could not measure free disk'
        : disk >= MIN_DISK_GB
          ? `Free disk ~${disk} GB`
          : `Only ~${disk} GB free. Need at least ${MIN_DISK_GB} GB.`,
    disk,
  })

  const virt = await virtualizationEnabled()
  checks.push({ id: 'virtualization', ...virt })

  const ports = await checkPorts()
  checks.push({ id: 'ports', ...ports })

  const page = await pageFileWarning()
  checks.push({ id: 'pagefile', ...page })

  const failed = checks.filter((c) => c.ok === false)
  return {
    ok: failed.length === 0,
    checks,
    warnings: checks.filter((c) => c.warn),
  }
}

module.exports = {
  runPreflight,
  totalRamGb,
  freeRamGb,
  checkPorts,
  MIN_RAM_GB,
  MIN_DISK_GB,
}
