import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { app } from 'electron'

export type DharaPaths = {
  userDataRoot: string
  pgData: string
  objectStore: string
  logs: string
  runtimeConfig: string
  resourcesRoot: string
  postgresHome: string
  pythonHome: string
  backendRoot: string
  frontendRoot: string
  nodeHome: string
}

function ensureDir(dir: string): string {
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

export function resolveResourcesRoot(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'win-x64')
  }
  return path.join(app.getAppPath(), 'resources', 'win-x64')
}

function defaultUserDataRoot(): string {
  if (process.env.DHARA_USER_DATA) return process.env.DHARA_USER_DATA
  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
  return path.join(localAppData, 'Dhara')
}

export function resolveDharaPaths(): DharaPaths {
  const userDataRoot = ensureDir(defaultUserDataRoot())
  const resourcesRoot = resolveResourcesRoot()

  return {
    userDataRoot,
    pgData: ensureDir(path.join(userDataRoot, 'pgdata')),
    objectStore: ensureDir(path.join(userDataRoot, 'object_store')),
    logs: ensureDir(path.join(userDataRoot, 'logs')),
    runtimeConfig: path.join(userDataRoot, 'runtime.json'),
    resourcesRoot,
    postgresHome: path.join(resourcesRoot, 'pgsql'),
    pythonHome: path.join(resourcesRoot, 'python'),
    backendRoot: path.join(resourcesRoot, 'backend'),
    frontendRoot: path.join(resourcesRoot, 'frontend'),
    nodeHome: path.join(resourcesRoot, 'node'),
  }
}
