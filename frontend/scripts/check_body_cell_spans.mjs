/**
 * Regression checks for buildBodyCellSpans (sparse measure rowspans).
 * Run from frontend/: node scripts/check_body_cell_spans.mjs
 * Requires esbuild + a lucide-react stub (created next to this script).
 */
import { createRequire } from 'module'
import { execSync } from 'child_process'
import { writeFileSync, mkdirSync } from 'fs'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const stubDir = join(__dirname, '.stubs')
mkdirSync(stubDir, { recursive: true })
writeFileSync(
  join(stubDir, 'lucide-react.js'),
  'module.exports = { ArrowDown:()=>null, ArrowUp:()=>null, Minus:()=>null }\n',
)
const out = join(stubDir, 'pdfReviewHelpers.cjs')
execSync(
  `npx --yes esbuild ${join(__dirname, '../src/lib/pdfReviewHelpers.js')} `
    + `--bundle --platform=node --format=cjs --outfile=${out} `
    + `--alias:lucide-react=${join(stubDir, 'lucide-react.js')}`,
  { stdio: 'inherit', cwd: join(__dirname, '..') },
)

const require = createRequire(import.meta.url)
const {
  buildBodyCellSpans,
  reconcileBodyMergesWithAutoInfer,
  resolveDisplayBodySpans,
} = require(out)

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

const columns = [
  { name: 'Sl.No.' }, { name: 'Name of Block' }, { name: 'Nutmeg' },
  { name: 'Sesamum' }, { name: 'Drumstick' }, { name: 'Papaya' },
]
const rows = [
  ['KANNUR', null, null, null, null, null],
  ['1', 'Edakkad', '0.088', null, '105.252', '493.001'],
  ['5', 'Kannur', '0.114', '0.121', '63.935', '270.687'],
  ['6', 'Kuthuparamba', '0.452', null, '77.102', '378.273'],
  ['7', 'Panoor', '0.366', null, '57.532', '226.48'],
  ['9', 'Peravur', '27.4', '0.214', '102.352', '421.087'],
  [null, 'Block Total', '113.284', '1.702', '1504.985', '7556.451'],
]
const spans = buildBodyCellSpans(rows, columns)
for (let r = 0; r < rows.length; r += 1) {
  const s = spans[r][3]
  assert(!s || (s.rowSpan || 1) === 1, `Sesamum must not rowspan at row ${r}`)
}
assert((spans[6][0]?.colSpan || 1) >= 2, 'Block Total should merge Sl.No + Name')

const pop = buildBodyCellSpans(
  [['1', 'Ward A', '5000'], [null, null, null], [null, null, null], ['2', 'Ward B', '3000']],
  [{ name: 'Sl.No.' }, { name: 'Name' }, { name: 'Population' }],
)
assert((pop[0][2]?.rowSpan || 1) === 3, 'True stub-continuation measure rowspan kept')
assert(pop[3][2]?.rowSpan === 1, 'New Sl.No. ends population span')

// Persisted explicit Sesamum rowspan must reconcile back to Original auto-infer.
const staleExplicit = [{ r: 2, c: 3, rowSpan: 3, colSpan: 1 }]
const reconciled = reconcileBodyMergesWithAutoInfer(rows, columns, staleExplicit, true)
assert(reconciled.mergesExplicit === false, 'stale measure rowspan must unlock')
const originalSpans = resolveDisplayBodySpans(rows, columns, [], false)
const previewSpans = resolveDisplayBodySpans(
  rows, columns, reconciled.cellMerges, reconciled.mergesExplicit,
)
for (let r = 0; r < rows.length; r += 1) {
  for (let c = 0; c < columns.length; c += 1) {
    const a = originalSpans[r]?.[c]
    const b = previewSpans[r]?.[c]
    assert(
      JSON.stringify(a) === JSON.stringify(b),
      `original/preview diverge at ${r},${c}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`,
    )
  }
}
assert((previewSpans[2]?.[3]?.rowSpan || 1) === 1, 'no false Sesamum rowspan after reconcile')

console.log('check_body_cell_spans: ok')
