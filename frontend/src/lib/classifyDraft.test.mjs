/**
 * Node-runnable unit checks for classify draft helpers.
 * Run: node src/lib/classifyDraft.test.mjs  (from frontend/)
 */
import assert from 'node:assert/strict'
import {
  CLASSIFY_DRAFT_KEY,
  clearClassifyDraft,
  loadClassifyDraft,
  metadataIdsMatch,
  overlayClassifyDraft,
  saveClassifyDraft,
} from './classifyDraft.js'

const mem = new Map()
globalThis.sessionStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => { mem.set(k, String(v)) },
  removeItem: (k) => { mem.delete(k) },
}

mem.clear()
assert.equal(metadataIdsMatch(['b', 'a'], ['a', 'b']), true)
assert.equal(metadataIdsMatch(['a'], ['a', 'b']), false)
assert.equal(metadataIdsMatch([], ['a']), false)

clearClassifyDraft()
assert.equal(loadClassifyDraft(), null)

saveClassifyDraft({
  metadataIds: ['META-1'],
  selectedCol: 'Occupation',
  columnCodes: { Occupation: [{ value: 'x', code: '1', definition: 'd' }] },
  ncoMatchesByCol: { Occupation: { x: { title: 'T' } } },
  lgdMatchesByCol: {},
  harmRows: {},
  harmDirty: {},
  aliasVerified: {},
  ruleState: {},
  openRule: null,
})
assert.ok(mem.get(CLASSIFY_DRAFT_KEY))
const loaded = loadClassifyDraft()
assert.equal(loaded.selectedCol, 'Occupation')
assert.equal(loaded.columnCodes.Occupation[0].code, '1')

const server = {
  selectedCol: 'Sector',
  columnCodes: {
    Occupation: [{ value: 'x', code: '', definition: '' }],
    Sector: [{ value: 's', code: '9', definition: 'sec' }],
  },
  ncoMatchesByCol: {},
  lgdMatchesByCol: {},
  harmRows: { club1: [{ value: 'h' }] },
  harmDirty: {},
  aliasVerified: {},
  ruleState: {},
  openRule: null,
}
const over = overlayClassifyDraft(server, loaded, ['META-1'])
assert.ok(over)
assert.equal(over.selectedCol, 'Occupation')
assert.equal(over.columnCodes.Occupation[0].code, '1')
assert.equal(over.columnCodes.Sector[0].code, '9')
assert.equal(over.ncoMatchesByCol.Occupation.x.title, 'T')

assert.equal(overlayClassifyDraft(server, loaded, ['META-OTHER']), null)

clearClassifyDraft()
assert.equal(loadClassifyDraft(), null)

console.log('classifyDraft.test.mjs: all passed')
