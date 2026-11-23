'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { app } = require('electron')

const APP_DIR_NAME = 'Dhara'

function userDataRoot() {
  // Prefer LOCALAPPDATA\Dhara on Windows; fall back to Electron userData.
  if (process.platform === 'win32') {
    const local = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
    return path.join(local, APP_DIR_NAME)
  }
  return path.join(app.getPath('userData'))
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

function resourcesRoot() {
  // Packaged: process.resourcesPath; dev: desktop/
  if (app.isPackaged) {
    return process.resourcesPath
  }
  return path.join(__dirname, '..', '..')
}

function vendorDir() {
  // Packaged installers / image tarballs shipped with the app (read-only under Program Files).
  return path.join(resourcesRoot(), 'vendor')
}

function downloadCacheDir() {
  // Writable cache for downloaded installers — never mkdir under Program Files (EPERM).
  return ensureDir(path.join(userDataRoot(), 'downloads'))
}

function composeFile() {
  const packaged = path.join(resourcesRoot(), 'docker-compose.desktop.yml')
  if (fs.existsSync(packaged)) return packaged
  return path.join(__dirname, '..', '..', 'docker-compose.desktop.yml')
}

function initSqlFile() {
  const a = path.join(resourcesRoot(), 'resources', 'init-pgvector.sql')
  if (fs.existsSync(a)) return a
  return path.join(__dirname, '..', '..', 'resources', 'init-pgvector.sql')
}

function envFilePath() {
  return path.join(userDataRoot(), '.env')
}

function stateFilePath() {
  return path.join(userDataRoot(), 'setup-state.json')
}

function wslConfigPath() {
  // Docker Desktop reads %USERPROFILE%\.wslconfig
  return path.join(os.homedir(), '.wslconfig')
}

const UI_ORIGIN = 'http://127.0.0.1:8080'
const API_ORIGIN = 'http://127.0.0.1:8000'
const OLLAMA_ORIGIN = 'http://127.0.0.1:11434'
const DEFAULT_OLLAMA_MODEL = 'qwen2.5:1.5b-instruct'
const LLM_BASE_URL_FROM_DOCKER = 'http://host.docker.internal:11434/v1'

module.exports = {
  APP_DIR_NAME,
  userDataRoot,
  ensureDir,
  resourcesRoot,
  vendorDir,
  downloadCacheDir,
  composeFile,
  initSqlFile,
  envFilePath,
  stateFilePath,
  wslConfigPath,
  UI_ORIGIN,
  API_ORIGIN,
  OLLAMA_ORIGIN,
  DEFAULT_OLLAMA_MODEL,
  LLM_BASE_URL_FROM_DOCKER,
}
