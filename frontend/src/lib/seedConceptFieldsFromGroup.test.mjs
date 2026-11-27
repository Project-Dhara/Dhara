/**
 * Run: node src/lib/seedConceptFieldsFromGroup.test.mjs  (from frontend/)
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

// Load CJS/ESM interop via dynamic import of the .js source
const { seedConceptFieldsFromGroup } = await import('./seedConceptFieldsFromGroup.js')

const emptyFields = () => ({ Title: '', Description: '', Geography: '' })
const mergeConcepts = (base, list) => {
  const next = { ...base }
  for (const row of list) {
    const key = row.concept || row.field
    if (key && row.details != null) next[key] = String(row.details)
    else if (key && row.value != null) next[key] = String(row.value)
  }
  return next
}

const fromNmds = seedConceptFieldsFromGroup(
  {
    metadata: { product: 'P' },
    nmds_concepts: {
      standard: 'nmds',
      concepts: [
        { concept: 'Title', details: 'Bus stats' },
        { concept: 'Geography', details: 'Delhi' },
      ],
    },
  },
  emptyFields,
  mergeConcepts,
)
assert.equal(fromNmds.Title, 'Bus stats')
assert.equal(fromNmds.Geography, 'Delhi')

const fromDict = seedConceptFieldsFromGroup(
  {
    nmds_concepts: {
      standard: 'nmds',
      concepts: { Title: 'T2', Description: 'D2' },
    },
  },
  emptyFields,
  mergeConcepts,
)
assert.equal(fromDict.Title, 'T2')
assert.equal(fromDict.Description, 'D2')

console.log('seedConceptFieldsFromGroup.test.mjs: all passed')

// silence unused
void createRequire
