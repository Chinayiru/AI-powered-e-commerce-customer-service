import { useCallback, useEffect, useState } from 'react'
import {
  api,
  ApiError,
  loadStoredOperator,
  persistOperator,
  setOperator as setApiOperator,
  type Operator,
} from './api'
import { EvalView } from './EvalView'
import { OperatorBar } from './OperatorBar'
import { RunsView } from './RunsView'
import type { Fixture, Meta, RunRecord } from './types'
import { Workbench } from './Workbench'

type Tab = 'workbench' | 'runs' | 'eval'

const TABS: { key: Tab; label: string }[] = [
  { key: 'workbench', label: '工单处理' },
  { key: 'runs', label: '运行记录' },
  { key: 'eval', label: '评测与基线' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('workbench')
  const [meta, setMeta] = useState<Meta | null>(null)
  const [fixtures, setFixtures] = useState<Fixture[]>([])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [operator, setOperatorState] = useState<Operator | null>(loadStoredOperator)

  // 身份是写接口的前提：fetcher 每次请求都读这个模块级状态
  useEffect(() => {
    setApiOperator(operator)
  }, [operator])

  function changeOperator(next: Operator | null) {
    persistOperator(next)
    setOperatorState(next)
  }

  const boot = useCallback(async () => {
    setError(null)
    try {
      const [m, f, r] = await Promise.all([api.meta(), api.fixtures(), api.runs()])
      setMeta(m)
      setFixtures(f.items)
      setRuns(r.items)
      setReady(true)
    } catch (err) {
      setReady(false)
      setError(
        err instanceof ApiError
          ? `${err.message}（确认后端已启动：python -m app.api.server）`
          : `无法连接后端：${String(err)}`,
      )
    }
  }, [])

  useEffect(() => {
    void boot()
  }, [boot])

  const refreshRuns = useCallback(async () => {
    // 失败向上抛：RunsView 自己展示「刷新失败 + 重试」，并保留旧列表
    const r = await api.runs()
    setRuns(r.items)
    setMeta((prev) => (prev ? { ...prev, runs_count: r.items.length } : prev))
  }, [])

  function onRan(record: RunRecord) {
    setRuns((prev) => [record, ...prev.filter((r) => r.run_id !== record.run_id || r.recorded_at !== record.recorded_at)])
    setMeta((prev) => (prev ? { ...prev, runs_count: prev.runs_count + 1 } : prev))
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">售</div>
          <div>
            <div className="brand-title">售后工单处置台</div>
            <div className="brand-sub">人工确认 · 策略定结论 · 草稿过闸门</div>
          </div>
        </div>

        <nav className="nav">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={tab === t.key ? 'nav-item nav-active' : 'nav-item'}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.key === 'runs' && runs.length > 0 && <span className="nav-count">{runs.length}</span>}
            </button>
          ))}
        </nav>

        <div className="chips">
          <span className={`status-dot ${ready ? 'status-ok' : 'status-off'}`} />
          <span className="muted">{ready ? 'API 在线' : 'API 离线'}</span>
          {meta && (
            <>
              <span className="chip mono">{meta.provider}/{meta.model}</span>
              <span className="chip mono">policy {meta.policy.version}</span>
              <span className="chip mono">prompt {meta.prompt_version}</span>
            </>
          )}
          {operator ? (
            <span className="chip mono operator-chip">
              操作人 {operator.id}
              <button
                type="button"
                className="btn btn-ghost btn-xs"
                onClick={() => changeOperator(null)}
                title="退出后写接口一律 401"
              >
                退出
              </button>
            </span>
          ) : (
            <span className="chip mono">未登录操作人</span>
          )}
        </div>
      </header>

      <main className="main">
        {error && (
          <div className="notice notice-error">
            {error}
            <button type="button" className="btn btn-ghost btn-xs" onClick={() => void boot()}>
              重试
            </button>
          </div>
        )}

        {!ready && !error && (
          <div className="loading">
            <span className="spinner" /> 正在读取契约与服务状态…
          </div>
        )}

        {ready && !operator && <OperatorBar onLogin={changeOperator} />}

        {ready && tab === 'workbench' && (
          <Workbench fixtures={fixtures} meta={meta} operator={operator} onRan={onRan} />
        )}
        {ready && tab === 'runs' && <RunsView runs={runs} onRefresh={refreshRuns} />}
        {ready && tab === 'eval' && <EvalView meta={meta} />}
      </main>
    </div>
  )
}
