'use strict'

/**
 * Guided first-run / resume orchestrator.
 * Emits progress via onProgress({ step, message, percent, error? }).
 */

const preflight = require('./preflight')
const wsl = require('./wsl')
const docker = require('./docker')
const ollama = require('./ollama')
const compose = require('./compose')
const health = require('./health')
const { ensureSecrets, writeState, readState } = require('./store')
const { ensureDir, userDataRoot } = require('./paths')

async function runSetup({ useLocalLlm = true, resume = false, onProgress = () => {} } = {}) {
  const emit = (step, message, percent, extra = {}) => {
    onProgress({ step, message, percent, ...extra })
  }

  ensureDir(userDataRoot())
  writeState({ setupRunning: true, useLocalLlm: Boolean(useLocalLlm) })

  emit('preflight', 'Checking Windows, RAM, disk, virtualization, and ports…', 5)
  // If Docker is already up, drop leftover dhara-* containers first so Retry does not
  // fail preflight on "Ports in use: 5432" from a previous half-started stack.
  const earlyDocker = await docker.dockerInfo()
  if (earlyDocker.ok) {
    emit('preflight', 'Clearing any previous Dhara containers…', 4)
    await compose.removeStaleContainers()
  }
  const pf = await preflight.runPreflight()
  if (!pf.ok) {
    const fail = pf.checks.find((c) => !c.ok)
    writeState({ setupRunning: false, lastError: fail && fail.message })
    return { ok: false, stage: 'preflight', error: fail && fail.message, checks: pf.checks }
  }
  emit('preflight', 'Preflight passed', 12, { warnings: pf.warnings })

  // WSL memory cap for 8 GB hosts
  emit('wsl-config', 'Writing WSL memory limits for 8 GB RAM…', 15)
  wsl.writeWslConfig({ localLlm: useLocalLlm })

  if (!resume) {
    emit('wsl', 'Checking WSL2…', 18)
    const ready = await wsl.isWslReady()
    if (!ready.ok) {
      emit('wsl', 'Enabling WSL2 and Virtual Machine Platform (admin)…', 20)
      const en = await wsl.enableWslFeatures()
      if (en.needsReboot) {
        await wsl.scheduleResumeAfterReboot()
        writeState({ pendingResume: true, useLocalLlm })
        emit('reboot', 'A reboot is required to finish WSL. Dhara Setup will resume automatically after restart.', 25, {
          needsReboot: true,
        })
        return { ok: false, needsReboot: true, stage: 'wsl' }
      }
    } else {
      emit('wsl', 'WSL is ready', 22)
    }
  } else {
    emit('wsl', 'Resuming after reboot…', 22)
    writeState({ pendingResume: false })
  }

  emit('docker', 'Checking Docker Desktop…', 30)
  let info = await docker.dockerInfo()
  if (!info.ok) {
    emit('docker', 'Preparing Docker Desktop installer (bundled or official download)…', 32)
    const installer = await docker.ensureDockerInstaller((p) => {
      emit('docker', `Downloading Docker Desktop… ${Math.round(p * 100)}%`, 32 + Math.round(p * 8))
    })
    emit('docker', `Installing Docker Desktop from ${installer.source}…`, 42)
    const inst = await docker.installDockerDesktop(installer.path)
    if (!inst.ok) {
      writeState({ setupRunning: false, lastError: inst.message })
      return { ok: false, stage: 'docker-install', error: inst.message }
    }
    docker.startDockerDesktop()
    emit('docker', 'Waiting for Docker engine…', 48)
    const wait = await docker.waitForDocker({
      onTick: () => emit('docker', 'Waiting for Docker engine…', 50),
    })
    if (!wait.ok) {
      writeState({ setupRunning: false, lastError: wait.message })
      return { ok: false, stage: 'docker-wait', error: wait.message }
    }
  } else {
    emit('docker', 'Docker is running', 50)
  }

  if (useLocalLlm) {
    emit('ollama', 'Checking Ollama (local CPU LLM)…', 55)
    let ol = await ollama.isOllamaReady()
    if (!ol.ok) {
      emit('ollama', 'Preparing Ollama installer…', 56)
      const installer = await ollama.ensureOllamaInstaller((p) => {
        emit('ollama', `Downloading Ollama… ${Math.round(p * 100)}%`, 56 + Math.round(p * 6))
      })
      emit('ollama', `Installing Ollama from ${installer.source}…`, 63)
      await ollama.installOllama(installer.path)
      ollama.startOllama()
      ol = await ollama.waitForOllama()
      if (!ol.ok) {
        writeState({ setupRunning: false, lastError: ol.message })
        return { ok: false, stage: 'ollama', error: ol.message }
      }
    }
    emit('ollama', `Pulling small CPU model ${ollama.DEFAULT_OLLAMA_MODEL} (one-time)…`, 68)
    const pull = await ollama.pullModel()
    if (!pull.ok) {
      writeState({ setupRunning: false, lastError: pull.message })
      return { ok: false, stage: 'ollama-pull', error: pull.message }
    }
    emit('ollama', pull.message, 72)
  } else {
    emit('ollama', 'Skipping Ollama — configure a cloud API key later in Settings.', 55)
  }

  emit('secrets', 'Generating JWT and credential secrets…', 75)
  ensureSecrets({ useLocalLlm })

  emit('images', 'Loading Dhara container images (if bundled)…', 78)
  await compose.loadImageTarballs()

  emit('compose', 'Starting Dhara services (postgres, API, worker, UI)…', 82)
  const up = await compose.up()
  if (!up.ok) {
    const err = up.stderr || up.stdout || 'compose up failed'
    writeState({ setupRunning: false, lastError: err })
    return { ok: false, stage: 'compose', error: err }
  }

  emit('health', 'Waiting for API, worker, and UI…', 88)
  const healthy = await health.waitUntilHealthy({
    onTick: (t) => {
      emit(
        'health',
        `API: ${t.api && t.api.ok ? 'ok' : '…'} · worker: ${t.worker && t.worker.ok ? 'ok' : '…'} · UI: ${t.ui && t.ui.ok ? 'ok' : '…'}`,
        90,
      )
    },
  })
  if (!healthy.ok) {
    writeState({ setupRunning: false, lastError: healthy.message })
    return { ok: false, stage: 'health', error: healthy.message, detail: healthy }
  }

  writeState({
    setupRunning: false,
    setupComplete: true,
    useLocalLlm: Boolean(useLocalLlm),
    lastError: null,
  })
  emit('done', 'Dhara is ready.', 100)
  return { ok: true }
}

async function startStackOnly(onProgress = () => {}) {
  onProgress({ step: 'docker', message: 'Ensuring Docker is running…', percent: 20 })
  let info = await docker.dockerInfo()
  if (!info.ok) {
    docker.startDockerDesktop()
    const wait = await docker.waitForDocker()
    if (!wait.ok) return { ok: false, error: wait.message }
  }
  const state = readState()
  if (state.useLocalLlm) {
    const ol = await ollama.isOllamaReady()
    if (!ol.ok) {
      ollama.startOllama()
      await ollama.waitForOllama({ timeoutMs: 60000 })
    }
  }
  ensureSecrets({ useLocalLlm: state.useLocalLlm })
  onProgress({ step: 'compose', message: 'Starting services…', percent: 50 })
  const up = await compose.up()
  if (!up.ok) return { ok: false, error: up.stderr || up.stdout }
  onProgress({ step: 'health', message: 'Waiting until healthy…', percent: 75 })
  const healthy = await health.waitUntilHealthy()
  if (!healthy.ok) return { ok: false, error: healthy.message }
  onProgress({ step: 'done', message: 'Ready', percent: 100 })
  return { ok: true }
}

module.exports = { runSetup, startStackOnly }
