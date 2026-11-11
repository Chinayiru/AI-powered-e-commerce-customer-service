/**
 * Java 控制面 API 客户端。
 *
 * 约定：
 * - 消费者写接口必须带 ticketToken，建单/订单列表使用演示头 X-User-Id；
 * - 坐席接口只认 X-Agent-Token；
 * - 所有写操作都由调用方生成 requestId，用于服务端幂等。
 */
const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'NETWORK_ERROR', retryable = false } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

const FRIENDLY = {
  INVALID_ARGS: '提交内容不合法，请检查后重试。',
  UNAUTHENTICATED: '身份已失效，请重新进入工单。',
  FORBIDDEN_SCOPE: '无权访问该工单。',
  ORDER_NOT_FOUND: '没有查到该订单，请核对订单号。',
  TICKET_NOT_FOUND: '没有找到该工单。',
  STATE_NOT_ALLOWED: '当前状态不允许这个操作。',
  DUPLICATE_REQUEST: '该订单已有进行中的售后单。',
  IDEMPOTENCY_CONFLICT: '同一个请求号被用于不同内容，请刷新后重试。',
  IN_PROGRESS: '请求正在处理中，请稍后再试。',
  STALE_DRAFT: '草稿已在其他页面更新，请刷新后重试。',
  STALE_STATE: '工单状态已变化，请刷新后重试。',
  POLICY_REJECTED: '政策校验未通过，无法发送。',
  REVIEW_NOTE_REQUIRED: '需要填写复核说明（至少 5 个字）。',
  TOOL_UNAVAILABLE: '订单工具暂时不可用，请稍后重试。',
  TOOL_TIMEOUT: '订单工具超时，请稍后重试。',
  AGENT_UNAVAILABLE: 'AI 服务暂时不可用，已按转人工处理。',
  PERSISTENCE_FAILED: '保存失败，请稍后重试。'
}

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...headers
      },
      body: body ? JSON.stringify(body) : undefined
    })
  } catch (error) {
    throw new ApiError('无法连接后端，请确认 Java 服务已在 8080 启动。', {
      code: 'NETWORK_ERROR',
      retryable: true
    })
  }

  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }

  if (!response.ok) {
    const code = data?.code || `HTTP_${response.status}`
    throw new ApiError(FRIENDLY[code] || data?.message || `请求失败（${response.status}）`, {
      status: response.status,
      code,
      retryable: Boolean(data?.retryable)
    })
  }
  return data
}

export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function listOrders(userId) {
  return request('/me/orders', { headers: { 'X-User-Id': userId } })
}

export function createTicket({ userId, category, text, orderNo, requestId }) {
  return request('/tickets', {
    method: 'POST',
    headers: { 'X-User-Id': userId },
    body: {
      category,
      text,
      ...(orderNo ? { orderNo } : {}),
      requestId
    }
  })
}

export function getTicket(ticketId, token) {
  return request(`/tickets/${encodeURIComponent(ticketId)}`, {
    headers: { Authorization: `Bearer ${token}` }
  })
}

export function addMessage(ticketId, token, text, requestId) {
  return request(`/tickets/${encodeURIComponent(ticketId)}/messages`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: { text, requestId }
  })
}

export function cancelTicket(ticketId, token, requestId, expectedVersion) {
  return request(`/tickets/${encodeURIComponent(ticketId)}/cancel`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: { requestId, expectedVersion }
  })
}

export function agentView(ticketId, agentToken) {
  return request(`/agent/tickets/${encodeURIComponent(ticketId)}`, {
    headers: { 'X-Agent-Token': agentToken }
  })
}

export function agentSend(ticketId, agentToken, payload) {
  return request(`/agent/tickets/${encodeURIComponent(ticketId)}/send`, {
    method: 'POST',
    headers: { 'X-Agent-Token': agentToken },
    body: payload
  })
}

export function agentRegenerate(ticketId, agentToken, payload) {
  return request(`/agent/tickets/${encodeURIComponent(ticketId)}/regenerate`, {
    method: 'POST',
    headers: { 'X-Agent-Token': agentToken },
    body: payload
  })
}

export function agentHandoff(ticketId, agentToken, payload) {
  return request(`/agent/tickets/${encodeURIComponent(ticketId)}/handoff`, {
    method: 'POST',
    headers: { 'X-Agent-Token': agentToken },
    body: payload
  })
}

export function agentReply(ticketId, agentToken, payload) {
  return request(`/agent/tickets/${encodeURIComponent(ticketId)}/reply`, {
    method: 'POST',
    headers: { 'X-Agent-Token': agentToken },
    body: payload
  })
}

export function agentClose(ticketId, agentToken, payload) {
  return request(`/agent/tickets/${encodeURIComponent(ticketId)}/close`, {
    method: 'POST',
    headers: { 'X-Agent-Token': agentToken },
    body: payload
  })
}
