import { useRef, useState } from 'react'
import { api } from './api'
import { datetime, money } from './format'
import {
  AFTERSALES_LABEL,
  CASE_STATUS_LABEL,
  GATE_LABEL,
  INTENT_LABEL,
  REASON_LABEL,
  STOP_LABEL,
  VERDICT_LABEL,
} from './labels'
import type { RunRecord } from './types'
import { Badge, CopyButton, JsonBlock, KV, type Tone } from './ui'

const VERDICT_TONE: Record<string, Tone> = {
  approve: 'green',
  partial: 'amber',
  reject: 'red',
  undecided: 'gray',
}

const STOP_TONE: Record<string, Tone> = {
  finalized: 'green',
  degraded: 'red',
  timeout: 'amber',
  budget_exhausted: 'amber',
  invalid_output: 'red',
  rejected: 'gray',
}

export function ResultCard({ record, allowReplay = true }: { record: RunRecord; allowReplay?: boolean }) {
  const out = record.out
  const [replay, setReplay] = useState<{ drift: string[]; error?: string } | null>(null)
  const [replaying, setReplaying] = useState(false)
  // 回放是只读的，但连点会打出一串请求；同步 ref 挡住第二次
  const replayBusy = useRef(false)

  async function runReplay() {
    if (replayBusy.current) return
    replayBusy.current = true
    setReplaying(true)
    try {
      const res = await api.replay(record.run_id)
      setReplay({ drift: res.drift })
    } catch (err) {
      setReplay({ drift: [], error: err instanceof Error ? err.message : String(err) })
    } finally {
      replayBusy.current = false
      setReplaying(false)
    }
  }

  return (
    <section className="result">
      <header className="result-head">
        <div>
          <div className="eyebrow">处置结果</div>
          <div className="run-id mono">{out.run_id}</div>
        </div>
        <div className="result-badges">
          <Badge tone={VERDICT_TONE[out.verdict] ?? 'gray'}>{VERDICT_LABEL[out.verdict] ?? out.verdict}</Badge>
          <Badge tone={out.send_gate === 'auto' ? 'green' : 'amber'} outline>
            {GATE_LABEL[out.send_gate] ?? out.send_gate}
          </Badge>
          <Badge tone={STOP_TONE[out.stop_reason] ?? 'gray'} outline>
            {STOP_LABEL[out.stop_reason] ?? out.stop_reason}
          </Badge>
        </div>
      </header>

      {out.stop_reason !== 'finalized' && (
        <div className="notice notice-warn">
          本单未定稿：<span className="mono">{out.stop_reason}</span>
          {out.draft.risk_flags.length > 0 && <> · 风险标记 {out.draft.risk_flags.join(' / ')}</>}
        </div>
      )}

      <div className="kv-grid">
        <KV label="意图">{INTENT_LABEL[out.intent] ?? out.intent}</KV>
        <KV label="售后类型">{out.aftersales_type ? AFTERSALES_LABEL[out.aftersales_type] : '—'}</KV>
        <KV label="售后单">
          {out.case ? (
            <span>
              {CASE_STATUS_LABEL[out.case.status] ?? out.case.status}
              <span className="muted mono"> · {out.case.case_id}</span>
            </span>
          ) : (
            '未建单（只读路径）'
          )}
        </KV>
        <KV label="金额">{money(out.case?.amount_cents)}</KV>
        <KV label="耗时">{out.latency_ms} ms</KV>
        <KV label="Token">
          {out.usage.input_tokens} in / {out.usage.output_tokens} out
          {out.usage.estimated ? <span className="muted">（估算）</span> : null}
        </KV>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>出口草稿</h3>
          <CopyButton text={out.draft.text} label="复制话术" />
        </div>
        <p className={`draft${out.draft.text ? '' : ' draft-empty'}`}>
          {out.draft.text || '（空草稿：本单在出口前降级，未生成半截话术）'}
        </p>
        {out.draft.citations.length > 0 && (
          <ul className="citations">
            {out.draft.citations.map((c, i) => (
              <li key={`${c.qa_id ?? 'tool'}-${i}`}>
                <Badge tone="indigo" outline>
                  {c.source === 'kb' ? `KB ${c.qa_id ?? ''}` : 'TOOL'}
                </Badge>
                <span>{c.quote}</span>
              </li>
            ))}
          </ul>
        )}
        {out.draft.risk_flags.length > 0 && (
          <div className="flags">
            {out.draft.risk_flags.map((f) => (
              <Badge key={f} tone="red" outline>
                {f}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>规则依据</h3>
          {allowReplay && (
            <button type="button" className="btn btn-ghost btn-xs" onClick={runReplay} disabled={replaying}>
              {replaying ? '回放中…' : '回放校验'}
            </button>
          )}
        </div>
        <div className="reasons">
          {out.reason_codes.map((code) => (
            <span key={code} className="reason">
              <span className="reason-zh">{REASON_LABEL[code] ?? code}</span>
              <span className="reason-code mono">{code}</span>
            </span>
          ))}
        </div>
        {replay && (
          <div className={`notice ${replay.error || replay.drift.length ? 'notice-warn' : 'notice-ok'}`}>
            <span>
              {replay.error
                ? `回放失败：${replay.error}`
                : replay.drift.length === 0
                  ? '回放一致：用记录的 policy / prompt 版本重算，无字段漂移。'
                  : `回放漂移：${replay.drift.join(' / ')}`}
            </span>
            {replay.error && (
              <button type="button" className="btn btn-outline btn-xs" onClick={() => void runReplay()} disabled={replaying}>
                {replaying ? '回放中…' : '重试'}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>工具轨迹</h3>
          <span className="muted">{out.tool_calls.length} 次调用</span>
        </div>
        <table className="table table-compact">
          <thead>
            <tr>
              <th>#</th>
              <th>工具</th>
              <th>结果</th>
              <th>耗时</th>
              <th>参数指纹</th>
            </tr>
          </thead>
          <tbody>
            {out.tool_calls.map((t) => (
              <tr key={t.step}>
                <td className="mono">{t.step}</td>
                <td className="mono">{t.name}</td>
                <td>
                  {t.ok ? <Badge tone="green" outline>ok</Badge> : <Badge tone="red" outline>{t.error_code ?? 'error'}</Badge>}
                </td>
                <td className="mono">{t.latency_ms} ms</td>
                <td className="mono muted">{t.args_digest || '—'}</td>
              </tr>
            ))}
            {out.tool_calls.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  无工具调用
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="result-foot">
        <span className="muted mono">
          {out.model} · prompt {out.prompt_version} · policy {out.policy_version}
        </span>
        {record.recorded_at && <span className="muted">记录于 {datetime(record.recorded_at)}</span>}
      </div>

      {record.trace && Object.keys(record.trace).length > 0 && (
        <JsonBlock summary="策略输入 / 结论（trace）" value={record.trace} />
      )}
      <JsonBlock summary="完整运行记录（TicketOut）" value={record} />
    </section>
  )
}
