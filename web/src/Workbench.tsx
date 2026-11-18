import { useEffect, useRef, useState } from 'react'
import { ApiError, api, type Operator } from './api'
import { datetime, money } from './format'
import { ORDER_STATUS_LABEL, PLATFORM_LABEL } from './labels'
import { ResultCard } from './ResultCard'
import type { Fixture, Meta, Platform, RunRecord } from './types'
import { Badge, Empty } from './ui'

interface PendingRun {
  fixture: string
  text: string | null
  confirm: string | null
  budget: number
  timeout_ms: number
  delay_ms: number
  client_token: string
}

/** 一次用户动作一个 token；重试复用同一个，后端据此去重。 */
function newClientToken(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function Workbench({
  fixtures,
  meta,
  operator,
  onRan,
}: {
  fixtures: Fixture[]
  meta: Meta | null
  operator: Operator | null
  onRan: (record: RunRecord) => void
}) {
  const [platform, setPlatform] = useState<'all' | Platform>('all')
  const [short, setShort] = useState<string | null>(fixtures[0]?.short ?? null)
  const [text, setText] = useState('')
  const [budget, setBudget] = useState(6000)
  const [timeoutMs, setTimeoutMs] = useState(30000)
  const [delayMs, setDelayMs] = useState(0)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingRun | null>(null)
  // 切快照或再次运行时自增；异步结果回来若 token 已过期就直接丢弃，避免串面板
  const runToken = useRef(0)
  // 同步闸门：setState 要等下一次渲染，双击会在禁用生效前触发第二次
  const busy = useRef(false)

  const selected = fixtures.find((f) => f.short === short) ?? null
  const visible = fixtures.filter((f) => platform === 'all' || f.platform === platform)

  useEffect(() => {
    runToken.current += 1
    busy.current = false
    setRunning(false)
    setPending(null)
    setText(selected?.text ?? '')
    setResult(null)
    setError(null)
  }, [selected?.short])

  async function submit(payload: PendingRun) {
    if (busy.current) return
    busy.current = true
    const token = ++runToken.current
    setRunning(true)
    setError(null)
    try {
      const res = await api.createRun(payload)
      if (token !== runToken.current) return // 已切快照，旧结果作废
      setResult(res.record)
      setPending(null)
      onRan(res.record)
    } catch (err) {
      if (token !== runToken.current) return
      // 留住原请求（同一个 client_token）：点重试不会重复执行
      setPending(payload)
      setError(err instanceof ApiError ? `${err.code ? `[${err.code}] ` : ''}${err.message}` : String(err))
    } finally {
      busy.current = false
      if (token === runToken.current) setRunning(false)
    }
  }

  function execute(withConfirm: boolean) {
    if (busy.current || !selected) return
    // 审批人只能是自己：confirm 由已登录身份推导，服务端还会再核一遍
    if (withConfirm && !operator) {
      setError('请先在顶部登录操作人，再执行人工确认')
      return
    }
    if (!Number.isFinite(budget) || budget < 1) {
      setError('token_budget 必须是 ≥ 1 的整数')
      return
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1) {
      setError('timeout_ms 必须是 ≥ 1 的整数')
      return
    }
    if (!Number.isFinite(delayMs) || delayMs < 0) {
      setError('delay_ms 不能为负')
      return
    }

    void submit({
      fixture: selected.short,
      text: text.trim() || null,
      confirm: withConfirm && operator ? `human:${operator.id}` : null,
      budget,
      timeout_ms: timeoutMs,
      delay_ms: delayMs,
      client_token: newClientToken(),
    })
  }

  return (
    <div className="workbench">
      <aside className="fixture-pane card">
        <div className="pane-head">
          <h2>工单快照</h2>
          <span className="muted">{visible.length} / {fixtures.length}</span>
        </div>
        <div className="seg">
          {(['all', 'taobao', 'douyin'] as const).map((p) => (
            <button
              key={p}
              type="button"
              className={platform === p ? 'seg-item seg-active' : 'seg-item'}
              onClick={() => setPlatform(p)}
            >
              {p === 'all' ? '全部' : PLATFORM_LABEL[p]}
            </button>
          ))}
        </div>
        <ul className="fixture-list">
          {visible.map((f) => (
            <li key={f.stem}>
              <button
                type="button"
                className={f.short === short ? 'fixture fixture-active' : 'fixture'}
                onClick={() => setShort(f.short)}
              >
                <span className="fixture-top">
                  <span className="mono fixture-id">{f.short}</span>
                  <Badge tone={f.platform === 'taobao' ? 'amber' : 'indigo'} outline>
                    {PLATFORM_LABEL[f.platform]}
                  </Badge>
                </span>
                <span className="fixture-sub">
                  {f.order ? (
                    <>
                      <span>{ORDER_STATUS_LABEL[f.order.status] ?? f.order.status}</span>
                      <span className="mono">{money(f.order.paid_cents)}</span>
                    </>
                  ) : (
                    <span className="danger">快照不可用 {f.error}</span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div className="detail-pane">
        {!selected && <Empty title="选择一个工单快照" hint="左侧 10 个 fixture 覆盖脏数据、超窗、威胁、类目排除等场景。" />}
        {selected && (
          <>
            <section className="card">
              <div className="pane-head">
                <div>
                  <div className="eyebrow">订单快照</div>
                  <h2 className="mono">{selected.order_ref ?? '无订单引用'}</h2>
                </div>
                {selected.order?.platform_anomaly && <Badge tone="red">平台数据异常</Badge>}
              </div>

              {!selected.order ? (
                <div className="notice notice-warn">
                  快照无法归一化：<span className="mono">{selected.error}</span>。流水线会把它降级为转人工，不会猜状态。
                </div>
              ) : (
                <>
                  <div className="kv-grid">
                    <div className="kv">
                      <span className="kv-label">订单状态</span>
                      <span className="kv-value">{ORDER_STATUS_LABEL[selected.order.status] ?? selected.order.status}</span>
                    </div>
                    <div className="kv">
                      <span className="kv-label">实付</span>
                      <span className="kv-value mono">{money(selected.order.paid_cents)}</span>
                    </div>
                    <div className="kv">
                      <span className="kv-label">下单</span>
                      <span className="kv-value">{datetime(selected.order.created_at)}</span>
                    </div>
                    <div className="kv">
                      <span className="kv-label">签收</span>
                      <span className="kv-value">{datetime(selected.order.signed_at)}</span>
                    </div>
                  </div>

                  <h3 className="subhead">商品</h3>
                  <table className="table table-compact">
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>标题</th>
                        <th>数量</th>
                        <th>单价</th>
                        <th>类目</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.order.items.map((it) => (
                        <tr key={it.sku}>
                          <td className="mono">{it.sku}</td>
                          <td>{it.title}</td>
                          <td className="mono">{it.qty}</td>
                          <td className="mono">{money(it.unit_cents)}</td>
                          <td>
                            <span className="tag">{it.category}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  <h3 className="subhead">包裹（{selected.order.shipments.length}）</h3>
                  {selected.order.shipments.length === 0 && <p className="muted">无物流记录（未发货或平台未回传）。</p>}
                  {selected.order.shipments.map((s) => (
                    <div key={s.package_id} className="shipment">
                      <div className="shipment-head">
                        <span className="mono">{s.package_id || '—'}</span>
                        <span>{s.carrier}</span>
                        <span className="mono muted">{s.tracking_no}</span>
                        <Badge tone={s.delivered_at ? 'green' : 'gray'} outline>
                          {s.delivered_at ? '已签收' : '未签收'}
                        </Badge>
                      </div>
                      <div className="shipment-meta">
                        <span>发货 {datetime(s.shipped_at)}</span>
                        <span>签收 {datetime(s.delivered_at)}</span>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </section>

            <section className="card">
              <div className="pane-head">
                <h2>工单与参数</h2>
                <span className="muted">{text.length} / 2000</span>
              </div>
              <textarea
                className="ticket-text"
                value={text}
                onChange={(e) => setText(e.target.value.slice(0, 2000))}
                rows={4}
                placeholder="工单原文"
              />
              <p className="hint">
                改写会原样送进 pipeline（记录里保留脱敏副本）。
                {meta?.provider === 'scripted' ? (
                  <>
                    当前 <span className="mono">ScriptedProvider</span> 按订单号取固定剧本，意图不会随文本变化；
                    在 <span className="mono">.env</span> 配置真实模型后才由文本驱动。
                  </>
                ) : (
                  <>
                    当前 <span className="mono">{meta?.provider}/{meta?.model}</span>{' '}
                    逐单读文本输出 JSON，意图随文本变化；调用失败按超时/降级收敛到人工闸门。
                  </>
                )}
              </p>

              <div className="run-controls">
                <label className="field">
                  <span>人工确认人（来自登录身份）</span>
                  <input
                    className="mono"
                    value={operator ? `human:${operator.id}` : ''}
                    readOnly
                    placeholder="未登录"
                  />
                </label>
                <button type="button" className="btn btn-primary" onClick={() => execute(false)} disabled={running || !selected.order}>
                  {running ? '运行中…' : '运行（草案）'}
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => execute(true)}
                  disabled={running || !selected.order || !operator}
                  title={operator ? undefined : '先登录操作人'}
                >
                  人工确认后运行
                </button>
              </div>
              <p className="hint">
                第二条会以 <span className="mono">human:{operator?.id ?? '...'}</span> 走不可逆迁移；
                身份对不上服务端直接 403，没有确认人时打款一律不执行（NG-1）。
              </p>

              <details className="advanced">
                <summary>预算 / 超时 / 延迟</summary>
                <div className="advanced-grid">
                  <label className="field">
                    <span>token_budget</span>
                    <input
                      type="number"
                      value={budget}
                      min={1}
                      onChange={(e) => setBudget(Number(e.target.value))}
                      onBlur={() => setBudget((v) => (Number.isFinite(v) && v >= 1 ? Math.trunc(v) : 1))}
                    />
                  </label>
                  <label className="field">
                    <span>timeout_ms</span>
                    <input
                      type="number"
                      value={timeoutMs}
                      min={1}
                      onChange={(e) => setTimeoutMs(Number(e.target.value))}
                      onBlur={() => setTimeoutMs((v) => (Number.isFinite(v) && v >= 1 ? Math.trunc(v) : 30000))}
                    />
                  </label>
                  <label className="field">
                    <span>delay_ms</span>
                    <input
                      type="number"
                      value={delayMs}
                      min={0}
                      onChange={(e) => setDelayMs(Number(e.target.value))}
                      onBlur={() => setDelayMs((v) => (Number.isFinite(v) && v >= 0 ? Math.trunc(v) : 0))}
                    />
                  </label>
                </div>
                <p className="hint">
                  把 delay 调到大于 timeout 可复现 <span className="mono">timeout</span>；budget 调到 200 可复现
                  <span className="mono"> budget_exhausted</span>。
                </p>
              </details>

              {error && (
                <div className="notice notice-error">
                  <span>{error}</span>
                  {pending && (
                    <button
                      type="button"
                      className="btn btn-outline btn-xs"
                      onClick={() => void submit(pending)}
                      disabled={running}
                    >
                      {running ? '重试中…' : '用同一请求重试'}
                    </button>
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </div>

      <div className="result-pane">
        {result ? <ResultCard record={result} /> : <Empty title="尚未运行" hint="选择快照 → 运行，结果会落 runs.jsonl 并出现在「运行记录」里。" />}
      </div>
    </div>
  )
}
