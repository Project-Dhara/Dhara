'use client'

import { useEffect, useState } from 'react'
import { ArrowRight, Check } from 'lucide-react'
import Button from './ui/Button'

// Confirmation screen after Continue to publish writes the release to
// Postgres. API/MCP URLs here are still display placeholders.

const PUBLISH_STEPS = [
  'Validating harmonised columns',
  'Writing metadata record',
  'Registering API endpoint',
  'Registering MCP endpoint',
]

const MCP_TOOLS = ['search_datasets', 'get_table', 'get_metadata']

export default function Publish({ datasetLabel, metadataId, hasKey, onGoSettings, onGoDashboard, onUploadAnother, onGoCatalogue }) {
  const [publishing, setPublishing] = useState(true)
  const [doneSteps, setDoneSteps] = useState(0)
  const [access, setAccess] = useState('Public')
  const [licence, setLicence] = useState('GODL — India')
  const [version, setVersion] = useState('v1')
  const [copied, setCopied] = useState(null)

  useEffect(() => {
    if (!publishing) return
    if (doneSteps >= PUBLISH_STEPS.length) {
      const t = setTimeout(() => setPublishing(false), 350)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setDoneSteps((n) => n + 1), 450)
    return () => clearTimeout(t)
  }, [publishing, doneSteps])

  const idBase = metadataId || 'DHARA_NEW_RELEASE'
  const apiUrl = `https://catalogue.dhara.people+ai.org/api/datasets/${idBase}`
  const mcpUrl = 'https://catalogue.dhara.people+ai.org/mcp'

  const copy = (label, text) => {
    navigator.clipboard?.writeText(text).catch(() => {})
    setCopied(label)
    setTimeout(() => setCopied(null), 1500)
  }

  const selectClass = 'h-[42px] rounded-md border border-line bg-white px-3 font-sans text-[15px] text-ink'
  const fieldLabelClass = 'text-[13px] font-semibold text-ink'

  if (publishing) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center gap-[26px]">
        <div className="relative flex h-[84px] w-[84px] items-center justify-center rounded-full bg-sage">
          <div className="absolute -inset-3 animate-ping rounded-full border-2 border-green" />
          <div className="absolute -inset-3 animate-ping rounded-full border-2 border-teal [animation-delay:400ms]" />
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#e6f0e6] text-[#3d7a3d]">
            <Check className="h-6 w-6" strokeWidth={2.5} aria-hidden />
          </div>
        </div>
        <div className="font-display text-[24px] font-medium text-ink">Publishing to the catalogue…</div>
        <div className="text-[15px] text-ink-soft">Almost there — this only takes a moment.</div>
        <div className="flex min-w-[320px] flex-col gap-2.5">
          {PUBLISH_STEPS.map((label, i) => (
            <div className="flex items-center gap-2.5 text-sm text-ink" key={label}>
              <span className={`flex h-[22px] w-[22px] flex-none items-center justify-center rounded-full text-xs font-semibold ${i < doneSteps ? 'bg-sage text-[#3d7a3d]' : 'bg-cream text-[#8E9398]'}`}>
                {i < doneSteps ? <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden /> : i + 1}
              </span>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-5 rounded-[10px] bg-sage px-[22px] py-[18px]">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-[#4a5f3c]">{datasetLabel}</div>
          <div className="text-[19px] font-semibold text-[#3d5230]">Published to the catalogue</div>
          <div className="text-sm text-[#4a5f3c]">This release is now discoverable via the API and MCP endpoint below.</div>
        </div>
        <button className="inline-flex h-10 items-center gap-1.5 rounded-md border border-[#b9cfa9] bg-white px-4 text-sm font-semibold text-[#3d5230]" onClick={onGoCatalogue}>
          Open in catalogue
          <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-3.5">
        <div className="flex min-w-0 flex-col gap-3 rounded-[10px] border border-line bg-white p-5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-[#8E9398]"><span className="h-2 w-2 flex-none rounded-sm bg-green" />API endpoint</div>
          <div className="text-sm leading-relaxed text-ink-soft">Fetch the harmonised table as JSON or CSV.</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 truncate rounded-md border border-line bg-[#F7F3EA] px-2.5 py-2.5 text-[11.5px] text-ink">{apiUrl}</div>
            <button className="flex h-[34px] flex-none items-center rounded-md border border-line bg-white px-3.5 text-[13px] font-semibold text-teal" onClick={() => copy('api', apiUrl)}>{copied === 'api' ? 'Copied' : 'Copy'}</button>
          </div>
          <div className="text-[11.5px] text-[#8E9398]">GET · token in Authorization header</div>
        </div>

        <div className="flex min-w-0 flex-col gap-3 rounded-[10px] border border-line bg-white p-5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-[#8E9398]"><span className="h-2 w-2 flex-none rounded-sm bg-teal" />MCP endpoint</div>
          <div className="text-sm leading-relaxed text-ink-soft">Point an assistant at the catalogue and it can query this release.</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 truncate rounded-md border border-line bg-[#F7F3EA] px-2.5 py-2.5 text-[11.5px] text-ink">{mcpUrl}</div>
            <button className="flex h-[34px] flex-none items-center rounded-md border border-line bg-white px-3.5 text-[13px] font-semibold text-teal" onClick={() => copy('mcp', mcpUrl)}>{copied === 'mcp' ? 'Copied' : 'Copy'}</button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {MCP_TOOLS.map((t) => <span className="rounded-full border border-line bg-cream px-2.5 py-1 text-[11.5px] text-ink-soft" key={t}>{t}</span>)}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-[10px] border border-line bg-white px-[22px] py-5">
        <div className="flex items-center gap-2.5 text-xs uppercase tracking-wide text-[#8E9398]">
          <span className="h-2 w-2 flex-none rounded-sm bg-yellow" />
          <span>Metadata summary</span>
          <span className="rounded-full bg-[rgba(242,194,48,0.28)] px-2.5 py-0.5 text-[11px] font-semibold normal-case tracking-normal text-[#6b5406]">{hasKey ? 'Model-generated' : 'Awaiting model key'}</span>
        </div>
        {hasKey ? (
          <div className="text-[14.5px] leading-relaxed text-ink [text-wrap:pretty]">
            Registered records for {datasetLabel}, harmonised to standard concepts and code lists during classification. Ready for downstream API and MCP consumption.
          </div>
        ) : (
          <div className="flex items-center justify-between gap-5 rounded-lg border border-dashed border-line bg-cream px-4 py-3.5 text-sm text-ink-soft">
            <span>A written summary is generated from the metadata with your own model key. The dataset publishes without it.</span>
            <Button variant="secondary" size="sm" onClick={onGoSettings}>Add model key</Button>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-3.5 rounded-[10px] border border-line bg-white px-[22px] py-5">
        <div className="text-[15px] font-semibold text-ink">Release details</div>
        <div className="grid grid-cols-[1fr_1.4fr_0.6fr] gap-4">
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Access</label>
            <select className={selectClass} value={access} onChange={(e) => setAccess(e.target.value)}>
              <option value="Public">Public</option>
              <option value="Restricted">Restricted — on request</option>
              <option value="Internal">Internal to department</option>
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Licence</label>
            <select className={selectClass} value={licence} onChange={(e) => setLicence(e.target.value)}>
              <option value="GODL — India">Government Open Data Licence — India</option>
              <option value="CC BY 4.0">CC BY 4.0</option>
              <option value="Departmental terms">Departmental terms</option>
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={fieldLabelClass}>Version</label>
            <input className={selectClass} type="text" value={version} onChange={(e) => setVersion(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <Button onClick={onGoDashboard}>Back to dashboard</Button>
        <Button variant="secondary" onClick={onUploadAnother}>Upload another</Button>
      </div>
    </div>
  )
}