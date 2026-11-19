import { useState, type ReactNode } from 'react'

export type Tone = 'green' | 'amber' | 'red' | 'gray' | 'indigo'

export function Badge({
  tone = 'gray',
  children,
  outline = false,
}: {
  tone?: Tone
  children: ReactNode
  outline?: boolean
}) {
  return <span className={`badge badge-${tone}${outline ? ' badge-outline' : ''}`}>{children}</span>
}

export function KV({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="kv">
      <span className="kv-label">{label}</span>
      <span className={`kv-value${mono ? ' mono' : ''}`}>{children}</span>
    </div>
  )
}

export function CopyButton({ text, label = '复制' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setDone(true)
    window.setTimeout(() => setDone(false), 1400)
  }

  return (
    <button type="button" className="btn btn-ghost btn-xs" onClick={copy} disabled={!text}>
      {done ? '已复制' : label}
    </button>
  )
}

export function JsonBlock({ value, summary = '原始 JSON' }: { value: unknown; summary?: string }) {
  return (
    <details className="json-block">
      <summary>{summary}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {hint && <div className="empty-hint">{hint}</div>}
    </div>
  )
}
