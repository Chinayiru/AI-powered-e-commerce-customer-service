import { useMemo, useState } from 'react'
import { ApiError } from './api'
import { datetime, money } from './format'
import { GATE_LABEL, INTENT_LABEL, STOP_LABEL, VERDICT_LABEL } from './labels'
import { ResultCard } from './ResultCard'
import type { RunRecord } from './types'
import { Badge, Empty, type Tone } from './ui'

const VERDICT_TONE: Record<string, Tone> = {
  approve: 'green',
  partial: 'amber',
  reject: 'red',
  undecided: 'gray',
}

function isRenderable(r: RunRecord): boolean {
  return (
    !!r &&
    !!r.out &&
    typeof r.out.run_id === 'string' &&
    typeof r.out.draft?.text === 'string' &&
    Array.isArray(r.out.tool_calls)
  )
}

export function RunsView({ runs, onRefresh }: { runs: RunRecord[]; onRefresh: () => Promise<void> }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<RunRecord | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  // 刷新失败不清空已有列表，失败原因就地展示并可重试
  async function refresh() {
    if (refreshing) return
    setRefreshing(true)
    setRefreshError(null)
    try {
      await onRefresh()
    } catch (err) {
      setRefreshError(
        err instanceof ApiError ? `${err.code ? `[${err.code}] ` : ''}${err.message}` : String(err),
      )
    } finally {
      setRefreshing(false)
    }
  }

  // runs.jsonl 可能被手工编辑或版本回退：缺 out/draft 的记录渲染时会炸，先隔掉并计数
  const usable = useMemo(() => runs.filter(isRenderable), [runs])
  const broken = runs.length - usable.length

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return usable
    return usable.filter(
      (r) =>
        r.run_id.toLowerCase().includes(q) ||
        r.fixture.toLowerCase().includes(q) ||
        INTENT_LABEL[r.out.intent]?.includes(q) ||
        r.out.run_id.includes(q),
    )
  }, [usable, query])

  return (
    <div className="runs-view">
      <div className="page-head">
        <div>
          <div className="eyebrow">审计轨迹</div>
          <h2>运行记录</h2>
          <p className="muted">
            最近 {runs.length} 条 · 全部来自 <span className="mono">reports/runs.jsonl</span>，点一行看完整证据链。
          </p>
        </div>
        <div className="page-actions">
          <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索 run_id / fixture…" />
          <button type="button" className="btn btn-ghost" onClick={() => void refresh()} disabled={refreshing}>
            {refreshing ? '刷新中…' : '刷新'}
          </button>
        </div>
      </div>

      {refreshError && (
        <div className="notice notice-error">
          <span>刷新失败：{refreshError}（下方仍是上一次取到的记录）</span>
          <button type="button" className="btn btn-outline btn-xs" onClick={() => void refresh()} disabled={refreshing}>
            重试
          </button>
        </div>
      )}

      {broken > 0 && (
        <div className="notice notice-warn">
          {broken} 条记录缺少 out / draft / tool_calls，已跳过渲染（其余记录不受影响）。
        </div>
      )}

      {visible.length === 0 ? (
        <Empty
          title={broken > 0 ? '没有可显示的记录' : '还没有运行记录'}
          hint="去「工单处理」跑一单，记录会写进 reports/runs.jsonl。"
        />
      ) : (
        <div className="card table-card">
          <table className="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>快照</th>
                <th>run_id</th>
                <th>意图</th>
                <th>结论</th>
                <th>出口</th>
                <th>停点</th>
                <th>金额</th>
                <th>耗时</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.run_id + (r.recorded_at ?? '')} className="row-click" onClick={() => setSelected(r)}>
                  <td className="muted">{r.recorded_at ? datetime(r.recorded_at) : '—'}</td>
                  <td className="mono">{r.fixture.replace(/_(unship_cents|delivered_yuan|missing_state|dup_events|multi_pkg|over_window|partial|threat|digital|return)$/, '')}</td>
                  <td className="mono muted">{r.run_id}</td>
                  <td>{INTENT_LABEL[r.out.intent] ?? r.out.intent}</td>
                  <td>
                    <Badge tone={VERDICT_TONE[r.out.verdict] ?? 'gray'}>{VERDICT_LABEL[r.out.verdict] ?? r.out.verdict}</Badge>
                  </td>
                  <td>{GATE_LABEL[r.out.send_gate] ?? r.out.send_gate}</td>
                  <td className="muted">{STOP_LABEL[r.out.stop_reason] ?? r.out.stop_reason}</td>
                  <td className="mono">{money(r.out.case?.amount_cents)}</td>
                  <td className="mono muted">{r.out.latency_ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="modal-mask" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="modal-close" onClick={() => setSelected(null)} aria-label="关闭">
              ×
            </button>
            <ResultCard record={selected} />
          </div>
        </div>
      )}
    </div>
  )
}
