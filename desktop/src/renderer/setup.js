'use strict'

const choice = document.getElementById('choice')
const progress = document.getElementById('progress')
const startBtn = document.getElementById('startBtn')
const retryBtn = document.getElementById('retryBtn')
const barFill = document.getElementById('barFill')
const stepTitle = document.getElementById('stepTitle')
const stepMsg = document.getElementById('stepMsg')
const logEl = document.getElementById('log')
const errorEl = document.getElementById('error')

let lastOpts = { useLocalLlm: true }

function appendLog(line) {
  logEl.textContent += `${line}\n`
  logEl.scrollTop = logEl.scrollHeight
}

function showProgress() {
  choice.classList.add('hidden')
  progress.classList.remove('hidden')
}

function onProgress(p) {
  if (!p) return
  showProgress()
  const pct = Math.max(0, Math.min(100, Number(p.percent) || 0))
  barFill.style.width = `${pct}%`
  stepTitle.textContent = p.step ? String(p.step) : 'Working…'
  stepMsg.textContent = p.message || ''
  if (p.message) appendLog(`[${pct}%] ${p.message}`)
  if (p.error || p.step === 'error') {
    errorEl.textContent = p.error || p.message || 'Setup failed'
    errorEl.classList.remove('hidden')
    retryBtn.classList.remove('hidden')
    startBtn.disabled = false
  }
  if (p.needsReboot) {
    stepMsg.textContent =
      (p.message || '') + ' The PC will restart in a few seconds; setup resumes automatically.'
  }
}

async function start(opts) {
  lastOpts = opts
  errorEl.classList.add('hidden')
  retryBtn.classList.add('hidden')
  startBtn.disabled = true
  showProgress()
  appendLog(opts.resume ? 'Resuming setup…' : 'Starting setup…')
  try {
    const result = await window.dharaDesktop.runSetup(opts)
    if (!result.ok && !result.needsReboot) {
      onProgress({
        step: result.stage || 'error',
        message: result.error || 'Setup failed',
        percent: 0,
        error: result.error,
      })
    }
  } catch (err) {
    onProgress({
      step: 'error',
      message: String(err && err.message ? err.message : err),
      percent: 0,
      error: String(err && err.message ? err.message : err),
    })
  }
}

startBtn.addEventListener('click', () => {
  const local = document.querySelector('input[name="llm"]:checked')?.value === 'local'
  start({ useLocalLlm: local, resume: false })
})

retryBtn.addEventListener('click', () => {
  start({ ...lastOpts, resume: false })
})

window.dharaDesktop.onProgress(onProgress)
window.dharaDesktop.onAutoResume((payload) => {
  start({ useLocalLlm: payload?.useLocalLlm !== false, resume: true })
})
