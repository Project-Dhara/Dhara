// Copies non-TypeScript renderer assets next to the compiled output (dist/renderer).
import { cpSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const outDir = join(root, 'dist', 'renderer')
mkdirSync(outDir, { recursive: true })

cpSync(join(root, 'src', 'renderer'), outDir, { recursive: true })

const logo = join(root, 'resources', 'logo.png')
if (existsSync(logo)) {
  cpSync(logo, join(outDir, 'logo.png'))
}
console.log('Copied renderer assets to', outDir)
