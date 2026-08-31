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
        className={`file-drop${compact ? ' file-drop-compact' : ''}${dragging ? ' file-drop-drag' : ''}${loading ? ' file-drop-disabled' : ''}`}
        onClick={() => !loading && inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          accept(e.dataTransfer.files[0])
        }}
      >
        <div className="file-drop-title">{loading ? 'Processing…' : label}</div>
        <div className="file-drop-hint">{selectedName || hint}</div>
      </div>
    </>
  )
}
