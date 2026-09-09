'use client'

import { useRef, useState } from 'react'

export default function FileUpload({
  onUpload,
  loading,
  label = 'Add dataset file',
  hint = 'XLSX, CSV — drag and drop or browse',
  selectedName,
  compact = false,
  accept: acceptExt = '.xlsx,.xls',
  extensionRegex = /\.(xlsx|xls)$/i,
}) {
  const inputRef = useRef()
  const [dragging, setDragging] = useState(false)

  const accept = (file) => {
    if (file && extensionRegex.test(file.name)) onUpload(file)
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={acceptExt}
        style={{ display: 'none' }}
        onChange={(e) => accept(e.target.files[0])}
        disabled={loading}
      />
      <div
        className={`overflow-hidden rounded-xl bg-teal shadow-card ${compact ? 'max-w-none' : 'max-w-[420px]'}`}
      >
        <div className="flex h-9 items-center border-b border-[#e6dcc8] bg-cream px-3">
          <span className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Upload</span>
        </div>
        <div className="p-2.5">
          <div
            className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed px-4 transition-colors
              ${compact ? 'h-[72px]' : 'h-[84px]'}
              ${dragging ? 'border-cream bg-forest-light/40' : 'border-white/25 bg-black/10 hover:border-cream/70 hover:bg-black/[.14]'}
              ${loading ? 'cursor-not-allowed opacity-60' : ''}`}
            onClick={() => !loading && inputRef.current.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              accept(e.dataTransfer.files[0])
            }}
          >
            <div className="text-center text-[15px] font-semibold text-cream">{loading ? 'Processing…' : label}</div>
            <div className="text-center text-[13px] text-cream/70">{selectedName || hint}</div>
          </div>
        </div>
      </div>
    </>
  )
}
