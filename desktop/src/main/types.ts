export type ServiceState = 'stopped' | 'starting' | 'running' | 'stopping' | 'error'

export type StepId =
  | 'preflight'
  | 'adopt'
  | 'ports'
  | 'secrets'
  | 'postgres-init'
  | 'postgres-start'
  | 'backup'
  | 'migrate'
  | 'api'
  | 'worker'
  | 'ready'
  | 'stopping'
  | 'stopped'
  | 'error'

export interface ProgressEvent {
  step: StepId
  message: string
  /** 0–100 */
  percent: number
  /** Soft warning line (e.g. low RAM) — does not stop startup. */
  warning?: string
  /** Plain-language error to show to the user. */
  error?: string
}

export interface Ports {
  postgres: number
  api: number
}

/** Names of supervised processes. */
export type ServiceName = 'postgres' | 'api' | 'worker'

export type RamProfile = 'standard' | 'large'

export interface ServiceStatus {
  state: ServiceState
  ports: Ports | null
  origin: string | null
  pids: Partial<Record<ServiceName, number>>
  workerRestarts: number
  lastError: string | null
}

/** Error with a user-facing message distinct from the technical detail. */
export class DharaError extends Error {
  readonly code: string
  readonly userMessage: string

  constructor(code: string, userMessage: string, detail?: string) {
    super(detail ? `${userMessage} (${detail})` : userMessage)
    this.name = 'DharaError'
    this.code = code
    this.userMessage = userMessage
  }
}

export const MSG = {
  elevated:
    'Dhara cannot run with administrator rights because its database refuses to start that way. ' +
    'Close Dhara and open it again normally (do not use “Run as administrator”).',
  port:
    'Dhara could not open a local network port. Close other apps using that port or restart the PC, then try again.',
  database:
    'Dhara could not start its local database. Use “Open logs folder” and contact support.',
  databaseLocked:
    'Dhara’s database appears to be in use by another program. Close other copies of Dhara (check the system tray and Task Manager), then try again.',
  disk:
    'Not enough free disk space to back up your data before updating. Free some space and try again.',
  backupFailed:
    'Dhara could not back up your data before updating, so the update was not applied. Use “Open logs folder” for details.',
  migrateFailed:
    'Dhara could not set up or update its data. If you already had data, it was backed up first (see the backups folder). Use “Open logs folder” and contact support.',
  pgvectorMissing:
    'This build of Dhara is missing a required database component (pgvector), so its data cannot be set up. Please reinstall Dhara or contact support.',
  api: 'Dhara’s local service did not start correctly. Use “Open logs folder” and contact support.',
  runtimeMissing:
    'Dhara’s bundled components are missing or damaged. Please reinstall Dhara.',
  secretsMissing:
    'Dhara found existing data but its local settings file (runtime.json) is missing, so the database password is unknown. ' +
    'Restore runtime.json from a copy, or contact support before removing any data.',
} as const
