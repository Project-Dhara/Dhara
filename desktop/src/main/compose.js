'use strict'

const fs = require('fs')
const path = require('path')
const { run } = require('./exec')
const { composeFile, vendorDir, userDataRoot, ensureDir, initSqlFile } = require('./paths')
const { readEnv } = require('./store')

function composeEnv() {
  return { ...process.env, ...readEnv() }
}

function projectDir() {
  // Work directory with compose + init SQL for volume mount relative paths.
  const dir = ensureDir(path.join(userDataRoot(), 'compose'))
  const srcCompose = composeFile()
  const destCompose = path.join(dir, 'docker-compose.desktop.yml')
  fs.copyFileSync(srcCompose, destCompose)

  const resDir = ensureDir(path.join(dir, 'resources'))
  const sqlSrc = initSqlFile()
  if (fs.existsSync(sqlSrc)) {
    fs.copyFileSync(sqlSrc, path.join(resDir, 'init-pgvector.sql'))
  }
  return dir
}

function composeArgs(extra) {
  const dir = projectDir()
  return [
    'compose',
    '-f',
    path.join(dir, 'docker-compose.desktop.yml'),
    '--project-directory',
    dir,
    ...extra,
  ]
}

async function compose(cmdArgs, opts = {}) {
  const dir = projectDir()
  const r = await run('docker', composeArgs(cmdArgs), {
    cwd: dir,
    env: composeEnv(),
    timeout: opts.timeout || 600000,
  })
  return r
}

async function removeStaleContainers() {
  await run('docker', [
    'rm', '-f',
    'dhara-postgres', 'dhara-backend', 'dhara-worker', 'dhara-frontend', 'dhara-app',
  ])
}

async function loadImageTarballs() {
  const dir = vendorDir()
  if (!fs.existsSync(dir)) return { ok: true, loaded: [], message: 'No vendor dir — will use pull/build tags' }
  const tars = fs.readdirSync(dir).filter((f) => /\.tar(\.gz)?$/i.test(f))
  const loaded = []
  for (const name of tars) {
    const p = path.join(dir, name)
    const r = await run('docker', ['load', '-i', p], { timeout: 600000 })
    loaded.push({ name, ok: r.ok, stderr: r.stderr })
  }
  return { ok: loaded.every((x) => x.ok) || loaded.length === 0, loaded }
}

async function up() {
  await removeStaleContainers()
  const load = await loadImageTarballs()
  const r = await compose(['up', '-d'], { timeout: 600000 })
  if (!r.ok) {
    await removeStaleContainers()
    const retry = await compose(['up', '-d'], { timeout: 600000 })
    return { ...retry, load }
  }
  return { ...r, load }
}

async function down({ volumes = false } = {}) {
  const args = ['down']
  if (volumes) args.push('-v')
  return compose(args)
}

async function ps() {
  return compose(['ps'], { timeout: 60000 })
}

async function workerLogs() {
  return compose(['logs', '--tail', '80', 'worker'], { timeout: 60000 })
}

module.exports = {
  up,
  down,
  ps,
  workerLogs,
  loadImageTarballs,
  removeStaleContainers,
  projectDir,
}
