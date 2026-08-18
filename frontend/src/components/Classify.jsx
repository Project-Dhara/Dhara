import { useState } from 'react'

// Mock-only "Transformation & Harmonisation" step — local state only, no
// backend calls. The real catalogue write already happened at the
// Metadata Workspace step.

// Classified columns — each column DHARA recognized, its standard concept,
// and the code list read from the data. Code and definition are editable
// (a steward may want to rename/annotate them); value is what was actually
// found in the source data, so it stays fixed.
const CLASSIFIED_COLUMNS = [
  {
    name: 'District', concept: 'Geography (LGD)', note: 'registration units',
    codes: [
      { code: 'mcd', value: 'mcd', definition: 'municipal corporation of delhi' },
      { code: 'ndmc', value: 'ndmc', definition: 'new delhi municipal council' },
      { code: 'dcb', value: 'delhi cantt', definition: 'delhi cantonment board' },
    ],
  },
  {
    name: 'area', concept: 'Area type', note: 'urban / rural split',
    codes: [
      { code: 'urban', value: 'urban', definition: 'within municipal limits' },
      { code: 'rural', value: 'rural', definition: 'outside municipal limits' },
    ],
  },
  {
    name: 'Place of occurence', concept: 'Place of occurrence', note: 'institutional status',
    codes: [
      { code: 'inst', value: 'institutional', definition: 'occurred in a hospital or care facility' },
      { code: 'non_inst', value: 'non-institutional', definition: 'occurred outside a care facility' },
    ],
  },
  {
    name: 'Gender', concept: 'Sex', note: 'standard sex code list',
    codes: [
      { code: 'M', value: 'male', definition: 'male' },
      { code: 'F', value: 'female', definition: 'female' },
      { code: 'O', value: 'other', definition: 'other / not stated' },
    ],
  },
]

const RULE_DEFS = [
  ['sex', 'Gender values → standard code list', 'MALE → Male · FEMALE → Female · OTHER → Other', '3 of 3 matched'],
  ['age', 'Age columns → one age_group field', 'Three wide columns folded into age_group with three bands', 'wide → long'],
  ['occ', 'Occupation → NCO-2015 divisions', '5 of 6 values matched. SERVICE WORKERS needs a division picked.', '1 needs review'],
  ['geo', 'Geography → LGD codes', 'National Capital Territory of Delhi → state code 07', '1 of 1 matched'],
  ['num', 'Numeric formats', 'Thousands separators stripped, blank cells read as 0', '40 cells changed'],
]

const MAP_DEFS = {
  sex: { sourceHead: 'Value in file', targetHead: 'Standard code', rows: [['MALE', 'Male', '18 rows'], ['FEMALE', 'Female', '18 rows'], ['OTHER', 'Other', '4 rows']] },
  age: { sourceHead: 'Column in file', targetHead: 'age_group band', rows: [['AGE_LESS_THAN_15', '0–14', 'integer'], ['AGE_15_24', '15–24', 'integer'], ['AGE_25_34', '25–34', 'integer']] },
  occ: { sourceHead: 'Occupation in file', targetHead: 'NCO-2015 division', rows: [
    ['PROFESSIONAL / TECHNICAL', '2 — Professionals', '4 rows'], ['ADMINISTRATIVE, EXECUTIVE', '1 — Managers', '3 rows'],
    ['CLERICAL WORKERS', '4 — Clerical support', '2 rows'], ['SALE WORKERS', '5 — Service and sales', '2 rows'],
    ['SERVICE WORKERS', '', '6 rows'], ['NOT STATED', '', '1 row']] },
  geo: { sourceHead: 'Geography in file', targetHead: 'LGD code', rows: [['NATIONAL CAPITAL TERRITORY OF DELHI', '07 — NCT of Delhi', 'state']] },
  num: { sourceHead: 'Pattern found', targetHead: 'Read as', rows: [['1,232', '1232', '12 cells'], ['(blank)', '0', '6 cells'], ['-', '0', '2 cells']] },
}
const AI_FILL = { occ: { 'SERVICE WORKERS': '5 — Service and sales', 'NOT STATED': '0 — Not stated' } }

const TAGS = ['births', 'registration', 'sex', 'age group', 'occupation', 'Delhi', 'CRS', 'annual']

export default function Classify({ datasetLabel, onContinue }) {
  const [classified, setClassified] = useState(false)
  const [selectedCol, setSelectedCol] = useState(CLASSIFIED_COLUMNS[0].name)
  const [columnCodes, setColumnCodes] = useState(() =>
    Object.fromEntries(CLASSIFIED_COLUMNS.map((c) => [c.name, c.codes.map((row) => ({ ...row }))]))
  )
  const [savedCodes, setSavedCodes] = useState(columnCodes)
  const [openRule, setOpenRule] = useState(null)
  const [ruleState, setRuleState] = useState({}) // id -> 'skip' | undefined
  const [maps, setMaps] = useState({}) // id -> { src: target }
  const [taxonomy, setTaxonomy] = useState({ sector: 'Demography', theme: 'Vital Statistics', product: 'Delhi Vital Statistics' })

  const activeColumn = CLASSIFIED_COLUMNS.find((c) => c.name === selectedCol)
  const activeCodes = columnCodes[selectedCol] || []
  const columnDirty = JSON.stringify(columnCodes[selectedCol]) !== JSON.stringify(savedCodes[selectedCol])

  const setCodeField = (rowIndex, field, value) => {
    setColumnCodes((prev) => ({
      ...prev,
      [selectedCol]: prev[selectedCol].map((row, i) => (i === rowIndex ? { ...row, [field]: value } : row)),
    }))
  }
  const saveColumnCodes = () => {
    setSavedCodes((prev) => ({ ...prev, [selectedCol]: columnCodes[selectedCol].map((row) => ({ ...row })) }))
  }

  const mapValue = (id, src, dflt) => {
    const m = maps[id] || {}
    return m[src] !== undefined ? m[src] : dflt
  }
  const setMapValue = (id, src) => (e) => {
    const v = e.target.value
    setMaps((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), [src]: v } }))
  }
  const ruleFilled = (id) => MAP_DEFS[id].rows.every(([src, dflt]) => String(mapValue(id, src, dflt)).trim())
  const ruleDone = (id) => ruleState[id] === 'skip' || ruleFilled(id)
  const classReady = classified && RULE_DEFS.every(([id]) => ruleDone(id))

  const aiFillRule = (id) => {
    const next = {}
    MAP_DEFS[id].rows.forEach(([src, dflt]) => {
      const cur = mapValue(id, src, dflt)
      next[src] = String(cur).trim() ? cur : ((AI_FILL[id] && AI_FILL[id][src]) || '')
    })
    setMaps((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), ...next } }))
  }

  return (
    <div className="classify-step">
      <div className="classify-run-card">
        <div>
          <div className="classify-run-eyebrow">{datasetLabel}</div>
          <div className="classify-run-title">Classify columns and harmonise values</div>
          <div className="classify-run-blurb">DHARA reads every column, proposes a standard concept and drafts code-list mappings for review.</div>
        </div>
        <button className="classify-run-btn" onClick={() => setClassified(true)}>
          {classified ? 'Re-run classification' : 'Run classification'}
        </button>
      </div>

      {classified && (
        <>
          <div className="classify-card classcols-card">
            <div className="classify-card-head">
              <span>Classified columns</span>
              <span className="classify-card-note">{CLASSIFIED_COLUMNS.length} columns · pick one to check its code list</span>
            </div>

            <div className="classcols-chips">
              {CLASSIFIED_COLUMNS.map((c) => (
                <div
                  key={c.name}
                  className={`classcols-chip${c.name === selectedCol ? ' classcols-chip-active' : ''}`}
                  onClick={() => setSelectedCol(c.name)}
                >
                  <div className="classcols-chip-name">{c.name}</div>
                  <div className="classcols-chip-count">{c.codes.length} codes</div>
                </div>
              ))}
            </div>

            {activeColumn && (
              <>
                <div className="classcols-detail-head">
                  <div>
                    <span className="classcols-detail-name">{activeColumn.name}</span>
                    <span className="classcols-detail-concept">{activeColumn.concept}</span>
                  </div>
                  <div className="classcols-detail-meta">{activeCodes.length} values · {activeColumn.note}</div>
                </div>

                <div className="classcols-table">
                  <div className="classcols-table-head">
                    <div>Code</div><div>Value</div><div>Definition</div>
                  </div>
                  {activeCodes.map((row, i) => (
                    <div className="classcols-row" key={i}>
                      <input
                        className="classcols-input"
                        type="text"
                        value={row.code}
                        onChange={(e) => setCodeField(i, 'code', e.target.value)}
                      />
                      <div className="classcols-value">{row.value}</div>
                      <input
                        className="classcols-input"
                        type="text"
                        value={row.definition}
                        onChange={(e) => setCodeField(i, 'definition', e.target.value)}
                      />
                    </div>
                  ))}
                </div>

                <div className="classcols-footer">
                  <span className="classcols-footer-hint">Code and definition can be edited. Values come from the data and stay fixed.</span>
                  <button className="classcols-save-btn" disabled={!columnDirty} onClick={saveColumnCodes}>Save changes</button>
                </div>
              </>
            )}
          </div>

          <div className="classify-card">
            <div className="classify-card-head">
              <span>Harmonisation</span>
              <span className="classify-card-note">{RULE_DEFS.filter(([id]) => ruleDone(id)).length} of {RULE_DEFS.length} ready</span>
            </div>
            {RULE_DEFS.map(([id, title, detail, count]) => {
              const open = openRule === id
              const done = ruleDone(id)
              const skipped = ruleState[id] === 'skip'
              return (
                <div className="classify-rule" key={id}>
                  <div className="classify-rule-head" onClick={() => setOpenRule(open ? null : id)}>
                    <span className={`classify-rule-dot${done ? ' classify-rule-dot-done' : ''}`} />
                    <div className="classify-rule-text">
                      <div className="classify-rule-title">{title}</div>
                      <div className="classify-rule-detail">{detail}</div>
                    </div>
                    <span className={`classify-rule-status${done ? ' classify-rule-status-done' : ''}`}>
                      {skipped ? 'Skipped' : done ? 'Ready' : 'Needs review'}
                    </span>
                    <span className="classify-rule-count">{count}</span>
                    <span className={`classify-rule-chev${open ? ' classify-rule-chev-open' : ''}`}>▾</span>
                  </div>
                  {open && (
                    <div className="classify-rule-body">
                      <div className="classify-rule-actions">
                        <button className="classify-ai-btn" onClick={() => aiFillRule(id)}>✨ AI-fill blanks</button>
                        <button className="classify-clear-btn" onClick={() => setMaps((prev) => ({ ...prev, [id]: {} }))}>Clear</button>
                        <button className="classify-skip-btn" onClick={() => setRuleState((prev) => ({ ...prev, [id]: prev[id] === 'skip' ? undefined : 'skip' }))}>
                          {skipped ? 'Unskip' : 'Skip this rule'}
                        </button>
                      </div>
                      <div className="classify-map-table">
                        <div className="classify-map-head">
                          <div>#</div>
                          <div>{MAP_DEFS[id].sourceHead}</div>
                          <div>{MAP_DEFS[id].targetHead}</div>
                          <div>Match</div>
                        </div>
                        {MAP_DEFS[id].rows.map(([src, dflt, meta], i) => {
                          const val = mapValue(id, src, dflt)
                          const filled = String(val).trim().length > 0
                          return (
                            <div className="classify-map-row" key={src}>
                              <div className="classify-map-n">{i + 1}</div>
                              <div className="classify-map-source">
                                <div>{src}</div>
                                <div className="classify-map-source-meta">{meta}</div>
                              </div>
                              <input
                                className="classify-map-input"
                                type="text"
                                value={val}
                                onChange={setMapValue(id, src)}
                                placeholder="type a value…"
                              />
                              <div className="classify-map-mark">{filled ? '✓' : '—'}</div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="classify-card classify-taxonomy-card">
            <div className="classify-card-title">Catalogue placement</div>
            <div className="classify-taxonomy-grid">
              <div className="classify-field">
                <label className="classify-label">Sector</label>
                <select className="classify-select" value={taxonomy.sector} onChange={(e) => setTaxonomy((p) => ({ ...p, sector: e.target.value }))}>
                  {['Demography', 'Labour and Employment', 'Health', 'Agriculture'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="classify-field">
                <label className="classify-label">Theme</label>
                <select className="classify-select" value={taxonomy.theme} onChange={(e) => setTaxonomy((p) => ({ ...p, theme: e.target.value }))}>
                  {['Vital Statistics', 'Civil Registration', 'Workforce'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div className="classify-field">
                <label className="classify-label">Data product</label>
                <select className="classify-select" value={taxonomy.product} onChange={(e) => setTaxonomy((p) => ({ ...p, product: e.target.value }))}>
                  {['Delhi Vital Statistics', 'Delhi Labour Statistics', 'New data product'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
            </div>
            <div className="classify-tag-list">
              {TAGS.map((t) => <span className="classify-tag-chip" key={t}>{t}</span>)}
            </div>
          </div>
        </>
      )}

      <div className="classify-continue-row">
        <button className="console-primary-btn" disabled={!classReady} onClick={onContinue}>Continue to publish →</button>
        <span className="classify-continue-hint">
          {classified ? (classReady ? 'All rules ready.' : 'Fill in or skip the remaining rules to continue.') : 'Run classification to continue.'}
        </span>
      </div>
    </div>
  )
}
