'use strict'

const crypto = require('crypto')
const fs = require('fs')
const {
  ensureDir,
  userDataRoot,
  envFilePath,
  stateFilePath,
  LLM_BASE_URL_FROM_DOCKER,
  DEFAULT_OLLAMA_MODEL,
} = require('./paths')

function readState() {
  ensureDir(userDataRoot())
  const p = stateFilePath()
  if (!fs.existsSync(p)) return {}
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'))
  } catch {
    return {}
  }
}

function writeState(patch) {
  ensureDir(userDataRoot())
  const next = { ...readState(), ...patch, updatedAt: new Date().toISOString() }
  fs.writeFileSync(stateFilePath(), JSON.stringify(next, null, 2), 'utf8')
  return next
}

function parseEnvFile(text) {
  const out = {}
  for (const line of String(text || '').split(/\r?\n/)) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const i = t.indexOf('=')
    if (i < 0) continue
    out[t.slice(0, i).trim()] = t.slice(i + 1).trim()
  }
  return out
}

function formatEnv(obj) {
  return Object.entries(obj)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n') + '\n'
}

function readEnv() {
  const p = envFilePath()
  if (!fs.existsSync(p)) return {}
  return parseEnvFile(fs.readFileSync(p, 'utf8'))
}

function writeEnv(patch) {
  ensureDir(userDataRoot())
  const next = { ...readEnv(), ...patch }
  fs.writeFileSync(envFilePath(), formatEnv(next), 'utf8')
  return next
}

function ensureSecrets({ useLocalLlm } = {}) {
  const env = readEnv()
  if (!env.JWT_SECRET || env.JWT_SECRET === 'change_me_to_a_random_secret') {
    env.JWT_SECRET = crypto.randomBytes(32).toString('hex')
  }
  if (!env.LLM_CREDENTIALS_KEY) {
    // Fernet key: url-safe base64 of 32 bytes (cryptography.Fernet compatible).
    env.LLM_CREDENTIALS_KEY = crypto.randomBytes(32).toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
  }
  env.ENABLE_SIGNUP = env.ENABLE_SIGNUP || 'true'
  env.DHARA_IMAGE_POSTGRES = env.DHARA_IMAGE_POSTGRES || 'pgvector/pgvector:pg16'
  env.DHARA_IMAGE_BACKEND = env.DHARA_IMAGE_BACKEND || 'dhara-backend:desktop'
  env.DHARA_IMAGE_FRONTEND = env.DHARA_IMAGE_FRONTEND || 'dhara-frontend:desktop'
  env.DHARA_SELF_HOSTED_MODEL = env.DHARA_SELF_HOSTED_MODEL || DEFAULT_OLLAMA_MODEL

  if (useLocalLlm) {
    env.LLM_BASE_URL = LLM_BASE_URL_FROM_DOCKER
    env.LLM_MODEL = env.LLM_MODEL || DEFAULT_OLLAMA_MODEL
  } else if (useLocalLlm === false) {
    // Explicit cloud-later path: clear desktop LLM_BASE_URL so Settings cloud key wins.
    env.LLM_BASE_URL = ''
    env.LLM_MODEL = ''
  }

  writeEnv(env)
  return env
}

module.exports = {
  readState,
  writeState,
  readEnv,
  writeEnv,
  ensureSecrets,
}
