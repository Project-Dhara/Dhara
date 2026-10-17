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
  buildMultiLevelHeaderRows,
  buildEditorHeaderRows,
  columnHeaderPathForDisplay,
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

// Frequency × 3 stacks + appendix (Mean/SD/CV): banners must merge right from
// Range into empty Freq/% — never left into the empty Sl.No. gutter.
const freqCols = [
  { name: 'Sl.No.' }, { name: 'Range' }, { name: 'Freq.' }, { name: '% of Freq.' },
  { name: 'Sl.No.' }, { name: 'Range' }, { name: 'Freq.' }, { name: '% of Freq.' },
  { name: 'Sl.No.' }, { name: 'Range' }, { name: 'Freq' }, { name: '% of Freq.' },
  { name: 'Sl.No.' }, { name: 'Range' }, { name: 'Freq' }, { name: '% of Freq.' },
]
const freqRows = [
  ['14', '1300 - 1399', '8', '0.41', '44', '4300 - 4399', '44', '2.26', '74', '7300 - 7399', '4', '0.21', null, 'Mean', null, null],
  ['15', '1400 - 1499', '3', '0.15', '45', '4400 - 4499', '37', '1.90', '75', '7400 - 7499', '3', '0.15', null, 'Paddy', '3537.521', null],
  ['16', '1500 - 1599', '1', '0.05', '46', '4500 - 4599', '28', '1.44', '76', '7500 - 7599', '1', '0.05', null, 'Rice', '2324.151', null],
  ['17', '1600 - 1699', '2', '0.10', '47', '4600 - 4699', '20', '1.03', '77', '7600 - 7699', '2', '0.10', null, 'Standard Deviation', null, null],
  ['18', '1700 - 1799', '1', '0.05', '48', '4700 - 4799', '15', '0.77', '78', '7700 - 7799', '1', '0.05', null, 'Paddy', '1620.158', null],
  ['21', '2000 - 2099', '1', '0.05', '51', '5000 - 5099', '8', '0.41', '81', '8000 - 8099', '1', '0.05', null, 'Coefficient of variation (CV)', null, null],
  ['22', '2100 - 2199', '1', '0.05', '52', '5100 - 5199', '6', '0.31', '82', '8100 - 8199', '1', '0.05', null, '45.80', null, null],
]
const freqSpans = buildBodyCellSpans(freqRows, freqCols)
for (const r of [0, 3, 5, 6]) {
  const s = freqSpans[r][13]
  assert(s && (s.colSpan || 1) >= 2, `appendix row ${r}: Mean/SD/CV must colspan right from Range`)
  assert(
    freqSpans[r][12] && (freqSpans[r][12].colSpan || 1) === 1,
    `appendix row ${r}: must not left-merge into empty Sl.No. gutter`,
  )
  assert(freqSpans[r][14] == null, `appendix row ${r}: Freq covered by rightward banner merge`)
}
assert((freqSpans[1][13]?.colSpan || 1) === 1, 'Paddy label stays unmerged')
assert(freqSpans[1][14] && !isNaN(Number(freqRows[1][14])), 'Paddy value stays in Freq column')

// Preview must not invent a parent row from ``Leaf (note)`` — match view/edit.
const unitCol = { name: 'Area (in Ha)', header_path: ['Area (in Ha)'] }
assert(
  JSON.stringify(columnHeaderPathForDisplay(unitCol)) === JSON.stringify(['Area (in Ha)']),
  'Area (in Ha) must stay a single leaf in preview',
)
const qualCol = { name: 'MALE (DOMICILIARY)', header_path: ['MALE (DOMICILIARY)'] }
assert(
  JSON.stringify(columnHeaderPathForDisplay(qualCol)) === JSON.stringify(['MALE (DOMICILIARY)']),
  'bracket qualifier must not become a fake parent when not in header_path',
)
const nested = {
  name: 'MALE (DOMICILIARY)',
  header_group: 'DOMICILIARY',
  header_path: ['DOMICILIARY', 'MALE (DOMICILIARY)'],
}
assert(
  JSON.stringify(columnHeaderPathForDisplay(nested)) === JSON.stringify(['DOMICILIARY', 'MALE']),
  'redundant (GROUP) on leaf still stripped when parent exists',
)
const previewH = buildMultiLevelHeaderRows([unitCol, qualCol])
const editorH = buildEditorHeaderRows([unitCol, qualCol])
assert(previewH.depth === 1 && editorH.depth === 1, 'preview/editor depth must match for flat paren leaves')

console.log('check_body_cell_spans: ok')
