import { useState } from 'react'
import type { Operator } from './api'

/**
 * 操作人登录：身份只来自这里（请求头），不从输入框里的 confirm 自报。
 * 令牌由服务端 AFTERSALE_OPERATORS 配置，形如 `alice:tok-alice,bob:tok-bob`。
 */
export function OperatorBar({ onLogin }: { onLogin: (operator: Operator) => void }) {
  const [id, setId] = useState('')
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const nextId = id.trim()
    const nextToken = token.trim()
    if (!nextId || !nextToken) {
      setError('操作人 ID 与令牌都要填；令牌来自 .env 的 AFTERSALE_OPERATORS')
      return
    }
    setError(null)
    onLogin({ id: nextId, token: nextToken })
  }

  return (
    <form className="notice operator-login" onSubmit={submit}>
      <div className="operator-title">
        请先以操作人身份登录
        <span className="muted">
          写接口校验 <span className="mono">X-Operator-Id / X-Operator-Token</span>
          ；审批人由服务端按身份写入，前端不能替别人确认。
        </span>
      </div>
      <div className="operator-fields">
        <label className="field">
          <span>操作人</span>
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder="demo1" autoComplete="username" />
        </label>
        <label className="field">
          <span>令牌</span>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="tok-demo1"
            autoComplete="current-password"
          />
        </label>
        <button type="submit" className="btn btn-primary">
          登录
        </button>
      </div>
      {error && <div className="operator-error">{error}</div>}
    </form>
  )
}
