import type {
  Fixture,
  Meta,
  ReplayResult,
  RunRecord,
  RunRequestBody,
} from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

/** 当前操作人。写接口靠它鉴权；审批人身份由后端从它推导，前端不能自报 confirm。 */
export interface Operator {
  id: string
  token: string
}

const OPERATOR_KEY = 'aftersale.operator'

let operator: Operator | null = null

export function currentOperator(): Operator | null {
  return operator
}

export function setOperator(next: Operator | null): void {
  operator = next
}

export function loadStoredOperator(): Operator | null {
  try {
    const raw = sessionStorage.getItem(OPERATOR_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Operator>
    if (typeof parsed?.id !== 'string' || !parsed.id) return null
    if (typeof parsed?.token !== 'string' || !parsed.token) return null
    return { id: parsed.id, token: parsed.token }
  } catch {
    return null
  }
}

export function persistOperator(next: Operator | null): void {
  try {
    if (next) sessionStorage.setItem(OPERATOR_KEY, JSON.stringify(next))
    else sessionStorage.removeItem(OPERATOR_KEY)
  } catch {
    /* 隐私模式禁用 sessionStorage：本次会话仍可用内存态 */
  }
}

function authHeaders(): Record<string, string> {
  return operator
    ? { 'X-Operator-Id': operator.id, 'X-Operator-Token': operator.token }
    : {}
}

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

interface ErrorBody {
  detail?: unknown
  message?: unknown
  code?: unknown
  hint?: unknown
}

function fieldMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (!Array.isArray(detail)) return null
  const parts = detail.map((entry) => {
    if (typeof entry === 'string') return entry
    if (!entry || typeof entry !== 'object') return null
    const item = entry as { loc?: unknown; msg?: unknown; type?: unknown }
    const loc = Array.isArray(item.loc)
      ? item.loc.filter((x) => x !== 'body' && x !== 'query' && x !== 'path').join('.')
      : ''
    const msg =
      typeof item.msg === 'string' ? item.msg : typeof item.type === 'string' ? item.type : ''
    if (!msg) return null
    return loc ? `${loc}: ${msg}` : msg
  })
  const kept = parts.filter((x): x is string => !!x)
  return kept.length ? kept.join('；') : null
}

function describe(status: number, body: ErrorBody): string {
  const base =
    fieldMessage(body.detail) ??
    (typeof body.message === 'string' && body.message ? body.message : `HTTP ${status}`)
  // 400 的 hint 是排障提示，不能丢
  return typeof body.hint === 'string' && body.hint ? `${base}（${body.hint}）` : base
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...((init?.headers as Record<string, string> | undefined) ?? {}),
    },
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    let code: string | undefined
    try {
      const body = (await res.json()) as ErrorBody
      message = describe(res.status, body)
      if (typeof body.code === 'string') code = body.code
    } catch {
      /* 非 JSON 错误体：保留状态码 */
    }
    throw new ApiError(message, res.status, code)
  }
  return (await res.json()) as T
}

export const api = {
  meta: () => request<Meta>('/api/meta'),
  fixtures: () => request<{ items: Fixture[] }>('/api/fixtures'),
  runs: () => request<{ items: RunRecord[]; total: number }>('/api/runs?limit=200'),
  createRun: (body: RunRequestBody) =>
    request<{ record: RunRecord }>('/api/runs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  replay: (runId: string) =>
    request<ReplayResult>('/api/replay', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId }),
    }),
}
