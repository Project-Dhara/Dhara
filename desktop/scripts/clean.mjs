// Removes compiled output (dist/) and installer output (release/). Does not touch resources/win-x64.
import { rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
for (const d of ['dist', 'release']) {
  rmSync(join(root, d), { recursive: true, force: true })
}
console.log('Cleaned dist/ and release/')
