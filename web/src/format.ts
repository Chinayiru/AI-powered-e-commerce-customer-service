export function money(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return '—'
  return `¥${(cents / 100).toFixed(2)}`
}

export function datetime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function count(n: number): string {
  return new Intl.NumberFormat('zh-CN').format(n)
}

export function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}
