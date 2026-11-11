import fs from 'node:fs'
import path from 'node:path'
import type { RuntimeConfig } from '../main/config'
import type { DharaPaths } from '../main/paths'
import { waitForTcp } from './health'
import { FileLogger } from './logger'
import { runOnce, spawnLogged, type ManagedProcess } from './process'

function bin(postgresHome: string, name: string): string {
  return path.join(postgresHome, 'bin', `${name}.exe`)
}

function markerPath(paths: DharaPaths): string {
  return path.join(paths.pgData, 'DHARA_INITIALIZED')
}

export async function startPostgres(
  paths: DharaPaths,
  cfg: RuntimeConfig,
  port: number,
  logger: FileLogger,
): Promise<ManagedProcess> {
  const initdb = bin(paths.postgresHome, 'initdb')
  const pgCtl = bin(paths.postgresHome, 'pg_ctl')
  const psql = bin(paths.postgresHome, 'psql')
  const postgres = bin(paths.postgresHome, 'postgres')

  for (const exe of [initdb, pgCtl, psql, postgres]) {
    if (!fs.existsSync(exe)) {
      throw new Error(
        `Bundled Postgres binary missing: ${exe}. Run desktop/scripts/fetch-win-deps.ps1 on a Windows build host.`,
      )
    }
  }

  const firstBoot = !fs.existsSync(path.join(paths.pgData, 'PG_VERSION'))
  if (firstBoot) {
    logger.info(`Initializing Postgres data directory at ${paths.pgData}`)
    const pwFile = path.join(paths.userDataRoot, '.pgpass-init')
    fs.writeFileSync(pwFile, cfg.pgPassword, 'utf8')
    try {
      await runOnce(
        initdb,
        [
          '-D',
          paths.pgData,
          '-U',
          cfg.pgUser,
          '-A',
          'password',
          '--pwfile',
          pwFile,
          '-E',
          'UTF8',
          '--locale=C',
        ],
        { cwd: paths.postgresHome, env: process.env },
        logger,
        'initdb',
      )
    } finally {
      try {
        fs.unlinkSync(pwFile)
      } catch {
        /* ignore */
      }
    }

    const conf = path.join(paths.pgData, 'postgresql.conf')
    fs.appendFileSync(
      conf,
      `\n# Dhara desktop overrides\nlisten_addresses = '127.0.0.1'\nport = ${port}\n`,
      'utf8',
    )
  } else {
    const conf = path.join(paths.pgData, 'postgresql.conf')
    let text = fs.readFileSync(conf, 'utf8')
    if (/^port\s*=/m.test(text)) {
      text = text.replace(/^port\s*=.*/m, `port = ${port}`)
    } else {
      text += `\nport = ${port}\n`
    }
    if (!/listen_addresses\s*=/.test(text)) {
      text += `\nlisten_addresses = '127.0.0.1'\n`
    }
    fs.writeFileSync(conf, text, 'utf8')
  }

  logger.info(`Starting Postgres on 127.0.0.1:${port}`)
  const managed = spawnLogged(
    'postgres',
    postgres,
    ['-D', paths.pgData, '-p', String(port), '-h', '127.0.0.1'],
    {
      cwd: paths.postgresHome,
      env: {
        ...process.env,
        PGDATA: paths.pgData,
      },
    },
    logger,
  )

  await waitForTcp('127.0.0.1', port, 90_000)

  if (!fs.existsSync(markerPath(paths))) {
    logger.info('Creating database and enabling pgvector')
    const psqlEnv = { ...process.env, PGPASSWORD: cfg.pgPassword }
    await runOnce(
      psql,
      [
        '-h',
        '127.0.0.1',
        '-p',
        String(port),
        '-U',
        cfg.pgUser,
        '-d',
        'postgres',
        '-c',
        `CREATE DATABASE ${cfg.pgDatabase} OWNER ${cfg.pgUser};`,
      ],
      { cwd: paths.postgresHome, env: psqlEnv },
      logger,
      'create-database',
    ).catch((err) => {
      logger.info(`create-database note: ${err instanceof Error ? err.message : String(err)}`)
    })

    const initSqlPath = path.join(paths.backendRoot, 'db', 'init-pgvector.sql')
    const vectorSql = fs.existsSync(initSqlPath)
      ? fs.readFileSync(initSqlPath, 'utf8')
      : 'CREATE EXTENSION IF NOT EXISTS vector;'

    await runOnce(
      psql,
      [
        '-h',
        '127.0.0.1',
        '-p',
        String(port),
        '-U',
        cfg.pgUser,
        '-d',
        cfg.pgDatabase,
        '-v',
        'ON_ERROR_STOP=1',
        '-c',
        vectorSql,
      ],
      { cwd: paths.postgresHome, env: psqlEnv },
      logger,
      'create-extension-vector',
    )

    fs.writeFileSync(markerPath(paths), new Date().toISOString(), 'utf8')
  }

  return managed
}

export async function stopPostgres(
  managed: ManagedProcess | null,
  paths: DharaPaths,
  logger: FileLogger,
): Promise<void> {
  if (!managed) return
  const pgCtl = bin(paths.postgresHome, 'pg_ctl')
  if (fs.existsSync(pgCtl)) {
    try {
      await runOnce(
        pgCtl,
        ['-D', paths.pgData, '-m', 'fast', 'stop'],
        { cwd: paths.postgresHome, env: process.env },
        logger,
        'pg_ctl-stop',
      )
      return
    } catch (err) {
      logger.info(`pg_ctl stop failed, killing process: ${err instanceof Error ? err.message : String(err)}`)
    }
  }
  await managed.stop('SIGTERM')
}
