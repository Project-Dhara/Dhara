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
        className={`flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[#c9bda6] bg-[#FFFCF6] px-4 cursor-pointer
          ${compact ? 'h-[84px] max-w-none' : 'h-[84px] max-w-[420px]'}
          ${dragging ? 'border-teal bg-sage' : ''}
          ${loading ? 'opacity-60 cursor-not-allowed' : ''}`}
        onClick={() => !loading && inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          accept(e.dataTransfer.files[0])
        }}
      >
        <div className="text-center text-[15px] font-semibold text-teal">{loading ? 'Processing…' : label}</div>
        <div className="text-center text-[13px] text-[#8E9398]">{selectedName || hint}</div>
      </div>
    </>
  )
}