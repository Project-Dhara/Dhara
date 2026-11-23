'use strict'

const { spawn, execFile } = require('child_process')
const { promisify } = require('util')

const execFileAsync = promisify(execFile)

async function run(cmd, args = [], opts = {}) {
  const {
    cwd,
    env,
    timeout = 120000,
    shell = process.platform === 'win32',
  } = opts
  try {
    const { stdout, stderr } = await execFileAsync(cmd, args, {
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
  const child = spawn(cmd, args, {
    cwd: opts.cwd,
    env: { ...process.env, ...opts.env },
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
    shell: process.platform === 'win32',
  })
  child.unref()
  return child
}

module.exports = { run, spawnDetached }
