'use strict'

const fs = require('fs')
const path = require('path')
const { spawn, execFile } = require('child_process')
const { promisify } = require('util')

const execFileAsync = promisify(execFile)

let cachedDockerExe = null

/**
 * Prefer docker.exe over a PATH `docker` / `docker.cmd` shim.
 * Spawning .cmd with args that contain spaces is unreliable on Windows and can
 * produce errors like: unknown docker command: "compose Rahul\\AppData\\..."
 */
function resolveDockerExe() {
  if (cachedDockerExe) return cachedDockerExe
  if (process.platform !== 'win32') {
    cachedDockerExe = 'docker'
    return cachedDockerExe
  }
  const pf = process.env.ProgramFiles || 'C:\\Program Files'
  const candidates = [
    path.join(pf, 'Docker', 'Docker', 'resources', 'bin', 'docker.exe'),
    path.join(pf, 'Docker', 'Docker', 'resources', 'com.docker.cli.exe'),
  ]
  for (const c of candidates) {
    if (c && fs.existsSync(c)) {
      cachedDockerExe = c
      return cachedDockerExe
    }
  }
  cachedDockerExe = 'docker'
  return cachedDockerExe
}

function resolveCmd(cmd) {
  if (cmd === 'docker' || cmd === 'docker.exe') return resolveDockerExe()
  return cmd
}

async function run(cmd, args = [], opts = {}) {
  const {
    cwd,
    env,
    timeout = 120000,
    // Never default to shell:true on Windows — cmd concatenates args without quoting,
    // which breaks paths with spaces (e.g. C:\Users\Sunny Rahul\...) and PowerShell $vars.
    shell = false,
  } = opts
  const file = resolveCmd(cmd)
  try {
    const { stdout, stderr } = await execFileAsync(file, args, {
      cwd,
      env: { ...process.env, ...env },
      timeout,
      maxBuffer: 10 * 1024 * 1024,
      windowsHide: true,
      shell,
    })
    return {
      ok: true,
      code: 0,
      stdout: String(stdout || ''),
      stderr: String(stderr || ''),
    }
  } catch (err) {
    return {
      ok: false,
      code: typeof err.code === 'number' ? err.code : 1,
      stdout: String(err.stdout || ''),
      stderr: String(err.stderr || err.message || ''),
      error: err,
    }
  }
}

function spawnDetached(cmd, args = [], opts = {}) {
  const child = spawn(resolveCmd(cmd), args, {
    cwd: opts.cwd,
    env: { ...process.env, ...opts.env },
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
    // Match run(): pass args verbatim so paths with spaces stay intact.
    shell: opts.shell === true,
  })
  child.unref()
  return child
}

module.exports = { run, spawnDetached, resolveDockerExe }
