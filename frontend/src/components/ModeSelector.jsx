const MODE_CARDS = [
  {
    key: 'batch',
    title: 'Batch upload',
    blurb: 'Upload every dataset workbook for a release together with its metadata tag files.',
    bullets: ['Many dataset files at once', 'Metadata tag files included', 'DHARA pairs them for your review'],
    cta: 'Start batch upload',
  },
  {
    key: 'single',
    title: 'Single file upload',
    blurb: 'Upload one dataset workbook together with its metadata tag file.',
    bullets: ['One dataset file', 'One metadata tag file', 'DHARA prefills the metadata step for you'],
    cta: 'Start single upload',
  },
]

// Step-0 "Method" cards. Kept the mode/onModeChange contract from before —
// picking a card now also advances the console step via onPick. The KYDS
// summary/edit card used to live here but is now rendered by the parent
// (Console) across the whole Dataset Inventory stage — see KydsSummaryCard.
export default function ModeSelector({ mode, onModeChange, onPick }) {
  const choose = (key) => {
    onModeChange(key)
    onPick?.(key)
  }

  return (
    <div className="method-cards-wrap">
      <div className="method-cards">
        {MODE_CARDS.map((m) => (
          <div
            key={m.key}
            className={`method-card${mode === m.key ? ' method-card-active' : ''}`}
            onClick={() => choose(m.key)}
          >
            <div className="method-card-title">{m.title}</div>
            <div className="method-card-blurb">{m.blurb}</div>
            <div className="method-card-bullets">
              {m.bullets.map((b) => (
                <div className="method-card-bullet" key={b}>
                  <span className={`method-card-dot${m.key === 'single' ? ' method-card-dot-coral' : ''}`} />
                  <span>{b}</span>
                </div>
              ))}
            </div>
            <div className="method-card-cta">{m.cta} →</div>
          </div>
        ))}
      </div>
    </div>
  )
}
