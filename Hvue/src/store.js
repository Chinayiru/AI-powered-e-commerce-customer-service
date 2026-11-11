/**
 * 浏览器侧轻量会话存储。
 *
 * 工单 token 只保存在当前浏览器，用来恢复“我的工单”；它不替代服务端鉴权。
 * 坐席 token 默认是演示值，可在坐席页临时修改。
 */
import { reactive, watch } from 'vue'

const TICKETS_KEY = 'hvue.tickets.v1'
const USER_KEY = 'hvue.user.v1'
const AGENT_KEY = 'hvue.agentToken.v1'

function loadTickets() {
  try {
    const parsed = JSON.parse(localStorage.getItem(TICKETS_KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export const session = reactive({
  userId: localStorage.getItem(USER_KEY) || 'U001',
  agentToken: localStorage.getItem(AGENT_KEY) || 'demo-agent-token'
})

watch(
  () => session.userId,
  (value) => localStorage.setItem(USER_KEY, value)
)
watch(
  () => session.agentToken,
  (value) => localStorage.setItem(AGENT_KEY, value)
)

export const tickets = reactive(loadTickets())

watch(
  tickets,
  (value) => localStorage.setItem(TICKETS_KEY, JSON.stringify(value)),
  { deep: true }
)

export function rememberTicket(ticket) {
  const id = ticket.ticketId
  if (!id) return
  const index = tickets.findIndex((item) => item.ticketId === id)
  const previous = index >= 0 ? tickets[index] : {}
  const next = {
    ...previous,
    ...ticket,
    ticketToken: ticket.ticketToken || previous.ticketToken,
    updatedAt: new Date().toISOString()
  }
  if (index >= 0) tickets.splice(index, 1, next)
  else tickets.unshift(next)
}

export function tokenFor(ticketId) {
  return tickets.find((item) => item.ticketId === ticketId)?.ticketToken || ''
}

export function ticketFor(ticketId) {
  return tickets.find((item) => item.ticketId === ticketId) || null
}

export function recentTickets() {
  return [...tickets].sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))
}

export function forgetTicket(ticketId) {
  const index = tickets.findIndex((item) => item.ticketId === ticketId)
  if (index >= 0) tickets.splice(index, 1)
}
