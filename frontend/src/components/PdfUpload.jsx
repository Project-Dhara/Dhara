'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import FileUpload from './FileUpload'
import ErrorBanner from './ui/ErrorBanner'
import Button from './ui/Button'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'

// Upload only. Processing progress and review now live on their own routed
// pages (/console/processing/:jobId, /console/review/:jobId) -- this
// component's only job is picking a file, POSTing it, and navigating away.
export default function PdfUpload() {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const router = useRouter()

  const handleUpload = async (file) => {
    setError('')
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/pdf/upload', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(err.detail || 'Upload failed')
      }
      const { job_id } = await res.json()
      router.push(`/console/processing/${job_id}`)
    } catch (e) {
      setError(e.message)
      setUploading(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-[760px] flex-col gap-3">
      <FileUpload
        onUpload={handleUpload}
        loading={uploading}
        label="Drop your file here"
        hint="Drag and drop or browse"
        accept=".pdf"
        extensionRegex={/\.pdf$/i}
      />

      {error && (
        <div className="flex flex-col gap-2">
          <ErrorBanner>{error}</ErrorBanner>
          <Button variant="secondary" size="sm" className="self-start" onClick={() => setError('')}>Try again</Button>
        </div>
      )}
    </div>
  )
}
