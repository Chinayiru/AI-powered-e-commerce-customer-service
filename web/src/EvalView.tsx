import { datetime, pct } from './format'
import type { Meta } from './types'
import { Badge, Empty, KV, type Tone } from './ui'
import { AC_STATUS_LABEL, AC_TITLE } from './labels'

const AC_TONE: Record<string, Tone> = {
  passed: 'green',
  failed: 'red',
  self: 'amber',
  skipped: 'gray',
}

export function EvalView({ meta }: { meta: Meta | null }) {
  const baseline = meta?.baseline ?? null
  const retrieval = meta?.retrieval ?? null
  const threshold = meta?.retrieval_threshold ?? null

  const acEntries = baseline ? Object.entries(baseline.ac_results) : []
  const acTotal = acEntries.length
  const acIssues = acEntries.filter(([, status]) => status !== 'passed')
  const allPassed = acIssues.length === 0

  return (
    <div className="eval-view">
      <div className="page-head">
        <div>
          <div className="eyebrow">证据与基线</div>
          <h2>评测与基线</h2>
          <p className="muted">
            数字全部来自 <span className="mono">reports/</span>；<span className="mono">provider=scripted</span> 只证明管线通，不代表语义能力。
          </p>
        </div>
      </div>

      {!baseline && !retrieval && (
        <Empty
          title="还没有评测产物"
          hint="python -m app.eval.seal 生成 baseline_v0.json；python -m app.eval.retrieval --compare 生成 retrieval_v0.json。"
        />
      )}

      {baseline && (
        <section className="card">
          <div className="pane-head">
            <div>
              <div className="eyebrow">封存基线</div>
              <h3>
                基线 {baseline.baseline} <span className="muted">· {baseline.dataset}</span>
              </h3>
            </div>
            <Badge tone={allPassed ? 'green' : 'red'}>
              {allPassed ? `全部 ${acTotal} 条 AC 已通过` : `${acIssues.length} 条 AC 未通过`}
            </Badge>
          </div>

          {!allPassed && (
            <div className="notice notice-error">
              该基线已作废，数字不可引用：{acIssues
                .map(([code, status]) => `${code} ${AC_STATUS_LABEL[status] ?? status}`)
                .join('、')}
            </div>
          )}

          <div className="kv-grid kv-grid-3">
            <KV label="git sha" mono>
              <span title={baseline.git_sha}>{baseline.git_sha.slice(0, 12)}</span>
            </KV>
            <KV label="封存时间">{datetime(baseline.created_at)}</KV>
            <KV label="fixture 数">{baseline.fixture_count}</KV>
            <KV label="policy_version" mono>
              {baseline.policy_version}
            </KV>
            <KV label="prompt_version" mono>
              {baseline.prompt_version}
            </KV>
            <KV label="provider" mono>
              {baseline.provider}
            </KV>
            <KV label="fixture hash" mono>
              <span title={baseline.fixture_manifest_hash}>{baseline.fixture_manifest_hash}</span>
            </KV>
            <KV label="kb hash" mono>
              <span title={baseline.kb_hash}>{baseline.kb_hash.slice(0, 16)}…</span>
            </KV>
            <KV label="query hash" mono>
              <span title={baseline.query_hash}>{baseline.query_hash.slice(0, 16)}…</span>
            </KV>
          </div>

          <h3 className="subhead">AC {acTotal} 条</h3>
          <div className="ac-grid">
            {acEntries.map(([code, status]) => (
              <div key={code} className={`ac-tile ac-${status}`}>
                <div className="ac-top">
                  <span className="mono ac-code">{code}</span>
                  <Badge tone={AC_TONE[status] ?? 'gray'} outline>
                    {AC_STATUS_LABEL[status] ?? status}
                  </Badge>
                </div>
                <div className="ac-title">{AC_TITLE[code] ?? ''}</div>
              </div>
            ))}
          </div>
          <p className="hint">{baseline.note}</p>
        </section>
      )}

      {retrieval && (
        <section className="card">
          <div className="pane-head">
            <div>
              <div className="eyebrow">检索评测</div>
              <h3>
                recall@{retrieval.k} · {retrieval.dataset} 集 · {retrieval.keyword.n_queries} 条标注查询
              </h3>
            </div>
            <Badge tone={retrieval.vector_enabled ? 'green' : 'gray'} outline>
              向量通道 {retrieval.vector_enabled ? '开启' : '关闭'}
            </Badge>
          </div>

          <div className="bars">
            {[retrieval.keyword, retrieval.hybrid].map((arm) => (
              <div key={arm.retriever} className="bar-row">
                <span className="bar-label mono">{arm.retriever}</span>
                <span className="bar-track">
                  <span className="bar-fill" style={{ width: `${Math.max(2, arm.recall_at_5 * 100)}%` }} />
                </span>
                <span className="bar-value mono">{pct(arm.recall_at_5)}</span>
                <span className="muted mono">
                  {arm.n_hits}/{arm.n_queries}
                </span>
              </div>
            ))}
            <div className="bar-note">
              delta = <span className="mono">{retrieval.delta_pt.toFixed(3)}</span>
              （recall@5 差值，不是百分点）
              {threshold != null && (
                <>
                  {' '}· 阈值 <span className="mono">{threshold.toFixed(3)}</span>
                </>
              )}
              {' → '}
              {retrieval.vector_enabled ? '达到阈值，向量通道开启' : '未达阈值，向量通道关闭（已实现未采用）'}
            </div>
          </div>

          <h3 className="subhead">关键词通道漏检（{retrieval.keyword.misses.length}）</h3>
          <table className="table table-compact">
            <thead>
              <tr>
                <th>query</th>
                <th>文本</th>
                <th>gold</th>
                <th>top5</th>
              </tr>
            </thead>
            <tbody>
              {retrieval.keyword.misses.map((m) => (
                <tr key={m.query_id}>
                  <td className="mono">{m.query_id}</td>
                  <td>{m.query}</td>
                  <td className="mono">{m.gold.join(', ')}</td>
                  <td className="mono muted">{m.top5.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">{retrieval.note}</p>
          <p className="muted mono">
            生成于 {datetime(retrieval.generated_at)} · provider={retrieval.provider}
          </p>
        </section>
      )}

      <section className="card">
        <div className="pane-head">
          <h3>复现命令</h3>
        </div>
        <pre className="code-block">{`python -m pytest -q                     # 契约 + 验收 + API
python -m app.eval.retrieval --compare  # 检索对比
python -m app.eval.seal                 # 全绿才封存基线`}</pre>
      </section>
    </div>
  )
}
