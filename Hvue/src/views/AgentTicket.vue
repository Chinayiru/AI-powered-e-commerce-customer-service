<script setup>
// 坐席三栏工作台：左栏对话与工单元信息，中栏 AI 证据与政策校验，右栏草稿编辑。
// 所有写操作都携带 expectedVersion / requestId；并发冲突由服务端裁决，前端只展示错误。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ApiError,
  agentClose,
  agentHandoff,
  agentRegenerate,
  agentReply,
  agentSend,
  agentView,
  newRequestId
} from '../api'
import { session } from '../store'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()
const ticketId = computed(() => String(route.params.ticketId || ''))

const view = ref(null)
const loading = ref(false)
const error = ref('')
const errorCode = ref('')
const busy = ref('')
const toast = ref('')
const messageList = ref(null)

const draftText = ref('')
const reviewNote = ref('')
const replyText = ref('')
const handoffOpen = ref(false)
const handoffReason = ref('OUT_OF_SCOPE')

const REASONS = [
  { value: 'LOW_CONFIDENCE', label: '置信度过低' },
  { value: 'NO_EVIDENCE', label: '缺少政策依据' },
  { value: 'POLICY_BLOCKED', label: '政策不允许' },
  { value: 'TOOL_FAILED', label: '工具调用失败' },
  { value: 'AMBIGUOUS_ORDER', label: '订单指向不明确' },
  { value: 'ORDER_NOT_FOUND', label: '订单不存在' },
  { value: 'OUT_OF_SCOPE', label: '超出受理范围' },
  { value: 'USER_REQUESTED', label: '用户明确要求人工' },
  { value: 'INSUFFICIENT_INFO', label: '信息不足' }
]

const ticket = computed(() => view.value?.ticket || null)
const draft = computed(() => view.value?.draft || null)
const messages = computed(() => view.value?.messages || [])
const toolCalls = computed(() => view.value?.toolCalls || [])
const policy = computed(() => view.value?.policyCheck || null)
const citations = computed(() => draft.value?.citations || [])
const state = computed(() => ticket.value?.state || '')
const originalDraft = computed(() => draft.value?.replyDraft || '')
const edited = computed(() => draftText.value.trim() !== originalDraft.value.trim())
const needReview = computed(() => Boolean(view.value?.needHumanReview))
const tokenMissing = computed(() => !session.agentToken.trim())

const canSend = computed(
  () =>
    ['DRAFT_READY', 'TRANSFERRED'].includes(state.value) &&
    Boolean(draft.value) &&
    edited.value &&
    (!needReview.value || reviewNote.value.trim().length >= 5)
)
const canRegenerate = computed(() => state.value === 'DRAFT_READY')
const canHandoff = computed(() => ['AI_RUNNING', 'DRAFT_READY', 'WAITING_INPUT'].includes(state.value))
const canReply = computed(() => state.value === 'TRANSFERRED')
const canClose = computed(() => ['TRANSFERRED', 'REPLIED'].includes(state.value))

const confidencePercent = computed(() => {
  const value = view.value?.confidence
  return typeof value === 'number' ? Math.round(value * 100) : null
})

const suggestedAmount = computed(() => {
  const cents = draft.value?.suggestedAction?.amountCents
  return typeof cents === 'number' ? money(cents) : '—'
})

function money(cents) {
  return `¥${(Number(cents || 0) / 100).toFixed(2)}`
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

function reasonLabel(value) {
  return REASONS.find((item) => item.value === value)?.label || value || '—'
}

async function scrollToLatest() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function load() {
  if (!session.agentToken.trim()) {
    error.value = '请先填写坐席令牌。'
    errorCode.value = 'UNAUTHENTICATED'
    view.value = null
    return
  }
  loading.value = true
  error.value = ''
  errorCode.value = ''
  try {
    const data = await agentView(ticketId.value, session.agentToken.trim())
    view.value = data
    draftText.value = data.draft?.replyDraft || ''
    reviewNote.value = ''
    replyText.value = ''
    handoffReason.value = data.ticket?.transferReason || 'OUT_OF_SCOPE'
    await scrollToLatest()
  } catch (err) {
    view.value = null
    if (err instanceof ApiError) {
      error.value = err.message
      errorCode.value = err.code
    } else {
      error.value = '工单加载失败'
    }
  } finally {
    loading.value = false
  }
}

function showToast(message) {
  toast.value = message
  window.setTimeout(() => {
    if (toast.value === message) toast.value = ''
  }, 3200)
}

async function send() {
  if (!draft.value || busy.value) return
  if (!edited.value) {
    error.value = '请先修改草稿再发送；未编辑的默认草稿不能直接发给客户。'
    return
  }
  if (needReview.value && reviewNote.value.trim().length < 5) {
    error.value = '这张草稿需要复核说明，至少填写 5 个字。'
    return
  }
  busy.value = 'send'
  error.value = ''
  try {
    const payload = {
      text: draftText.value,
      draftVersion: draft.value.draftVersion,
      expectedVersion: ticket.value.version,
      requestId: newRequestId(),
      ...(reviewNote.value.trim() ? { reviewNote: reviewNote.value.trim() } : {})
    }
    const result = await agentSend(ticketId.value, session.agentToken.trim(), payload)
    showToast(
      result.state === 'CLOSED'
        ? '已模拟执行并关闭工单。'
        : '已受理，执行尚未完成；刷新后可查看最新状态。'
    )
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '发送失败，请刷新后重试。'
  } finally {
    busy.value = ''
  }
}

async function regenerate() {
  if (!canRegenerate.value || busy.value) return
  busy.value = 'regenerate'
  error.value = ''
  try {
    await agentRegenerate(ticketId.value, session.agentToken.trim(), {
      note: '坐席要求重新生成',
      expectedVersion: ticket.value.version,
      requestId: newRequestId()
    })
    showToast('已提交重新生成，正在刷新草稿。')
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '重新生成失败。'
  } finally {
    busy.value = ''
  }
}

async function handoff() {
  if (!canHandoff.value || busy.value) return
  busy.value = 'handoff'
  error.value = ''
  try {
    await agentHandoff(ticketId.value, session.agentToken.trim(), {
      reason: handoffReason.value,
      expectedVersion: ticket.value.version,
      requestId: newRequestId()
    })
    handoffOpen.value = false
    showToast('已转交人工处理。')
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '转交失败。'
  } finally {
    busy.value = ''
  }
}

async function reply() {
  const text = replyText.value.trim()
  if (!canReply.value || !text || busy.value) return
  busy.value = 'reply'
  error.value = ''
  try {
    await agentReply(ticketId.value, session.agentToken.trim(), {
      text,
      expectedVersion: ticket.value.version,
      requestId: newRequestId()
    })
    replyText.value = ''
    showToast('回复已发送，工单转为已回复。')
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '回复失败。'
  } finally {
    busy.value = ''
  }
}

async function close() {
  if (!canClose.value || busy.value) return
  if (!window.confirm('确认关闭这张工单吗？关闭后不能继续处理。')) return
  busy.value = 'close'
  error.value = ''
  try {
    await agentClose(ticketId.value, session.agentToken.trim(), {
      expectedVersion: ticket.value.version,
      requestId: newRequestId()
    })
    showToast('工单已关闭。')
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '关闭失败。'
  } finally {
    busy.value = ''
  }
}

onMounted(load)
watch(ticketId, load)
</script>

<template>
  <div class="page page--wide">
    <div class="page-head">
      <div>
        <div class="eyebrow">Agent Workspace</div>
        <h1 class="title">坐席工作台</h1>
        <p class="subtitle">
          助手只给建议与草稿；金额、政策与状态由 Java 裁决，坐席复核后才会模拟执行。
        </p>
      </div>
      <RouterLink class="btn" to="/agent">返回检索</RouterLink>
    </div>

    <div v-if="error" class="error-box" style="margin-bottom: 14px">
      <strong>!</strong>
      <span>{{ error }}</span>
      <button
        v-if="['UNAUTHENTICATED', 'FORBIDDEN_SCOPE'].includes(errorCode)"
        class="btn btn--small"
        type="button"
        style="margin-left: auto"
        @click="load"
      >
        重试
      </button>
    </div>

    <div v-if="tokenMissing" class="panel">
      <div class="panel-body grid">
        <div>
          <h2 style="font-size: 16px">需要坐席令牌</h2>
          <p class="subtitle">默认演示令牌是 demo-agent-token；可在下方修改后重试。</p>
        </div>
        <div class="form-row">
          <input v-model="session.agentToken" class="input" placeholder="X-Agent-Token" />
          <button class="btn btn--primary" type="button" @click="load">使用该令牌</button>
        </div>
      </div>
    </div>

    <div v-else-if="loading && !view" class="panel">
      <div class="panel-body empty"><strong>正在读取工单与草稿…</strong></div>
    </div>

    <template v-else-if="ticket">
      <div class="ticket-banner">
        <div class="ticket-banner-main">
          <span class="ticket-banner-id">{{ ticket.ticketId }}</span>
          <StatusPill :state="ticket.state" />
          <span class="ticket-banner-meta">
            {{ ticket.category === 'CONSULT' ? '咨询' : '售后' }} · v{{ ticket.version }} ·
            {{ ticket.orderNo || '无订单号' }} · {{ ticket.executionMode }}
          </span>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <span v-if="ticket.transferReason" class="pill pill--human">
            <span class="pill-dot"></span>{{ reasonLabel(ticket.transferReason) }}
          </span>
          <button class="btn btn--small" type="button" :disabled="loading" @click="load">
            {{ loading ? '刷新中…' : '刷新' }}
          </button>
        </div>
      </div>

      <div class="agent-grid">
        <!-- 左栏：对话与工单元信息 -->
        <div class="agent-col agent-col--sticky">
          <section class="panel">
            <div class="panel-head">
              <h2>工单信息</h2>
              <span class="hint">完整内部状态</span>
            </div>
            <div class="panel-body">
              <div class="meta-grid">
                <div class="meta-cell"><small>工单号</small><strong>{{ ticket.ticketId }}</strong></div>
                <div class="meta-cell"><small>类型</small><strong>{{ ticket.category === 'CONSULT' ? '咨询' : '售后' }}</strong></div>
                <div class="meta-cell"><small>订单号</small><strong>{{ ticket.orderNo || '—' }}</strong></div>
                <div class="meta-cell"><small>执行模式</small><strong>{{ ticket.executionMode }}</strong></div>
                <div class="meta-cell"><small>版本</small><strong>v{{ ticket.version }}</strong></div>
                <div class="meta-cell"><small>创建时间</small><strong>{{ formatTime(ticket.createdAt) }}</strong></div>
              </div>
            </div>
          </section>

          <section class="panel chat-panel">
            <div class="panel-head">
              <h2>对话记录</h2>
              <span class="hint">{{ messages.length }} 条 · 含系统消息</span>
            </div>
            <div ref="messageList" class="message-list" style="max-height: 42vh; min-height: 260px">
              <EmptyState v-if="!messages.length" title="暂无消息" description="客户还没有发送内容。" />
              <template v-for="message in messages" :key="message.id">
                <div v-if="message.role === 'SYSTEM'" class="message--system">{{ message.text }}</div>
                <div
                  v-else
                  class="message-row"
                  :class="{ 'message-row--customer': message.role === 'CUSTOMER' }"
                >
                  <span class="avatar">{{ message.role === 'CUSTOMER' ? '客' : '席' }}</span>
                  <div class="message-body">
                    <div class="message-meta">
                      {{ message.role === 'CUSTOMER' ? '客户' : '坐席' }} · {{ formatTime(message.createdAt) }}
                    </div>
                    <div class="message-bubble">{{ message.text }}</div>
                  </div>
                </div>
              </template>
            </div>
          </section>
        </div>

        <!-- 中栏：AI 建议、政策校验、工具轨迹 -->
        <div class="agent-col">
          <section class="panel">
            <div class="panel-head">
              <h2>助手建议</h2>
              <span v-if="view?.degraded" class="pill pill--wait"><span class="pill-dot"></span>降级结果</span>
            </div>
            <div class="panel-body grid">
              <div class="meta-grid">
                <div class="meta-cell">
                  <small>意图</small>
                  <strong>{{ view?.intent || '未返回' }}</strong>
                </div>
                <div class="meta-cell">
                  <small>回复类型</small>
                  <strong>{{ draft?.replyType || '—' }}</strong>
                </div>
              </div>

              <div class="confidence-wrap">
                <div class="confidence-value">
                  <span>置信度</span>
                  <strong>{{ confidencePercent === null ? '—' : `${confidencePercent}%` }}</strong>
                </div>
                <div class="confidence-track">
                  <div
                    class="confidence-fill"
                    :style="{ width: `${confidencePercent === null ? 0 : confidencePercent}%` }"
                  ></div>
                </div>
              </div>

              <div v-if="needReview" class="notice notice--warn">
                这张草稿需要人工复核说明。发送前必须填写至少 5 个字的复核依据。
              </div>

              <div class="side-row">
                <span>建议动作</span>
                <span>{{ draft?.suggestedAction?.action || 'NONE' }}</span>
              </div>
              <div class="side-row">
                <span>建议金额</span>
                <span>{{ suggestedAmount }}</span>
              </div>
              <div class="side-row">
                <span>草稿版本</span>
                <span>{{ draft ? `v${draft.draftVersion}` : '无草稿' }}</span>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>政策校验</h2>
              <StatusPill v-if="policy" :state="policy.allowed ? '已完成' : '待人工处理'" />
            </div>
            <div class="panel-body grid">
              <EmptyState v-if="!policy" title="没有政策结果" description="本工单未产生金额或政策决策。" />
              <template v-else>
                <div class="meta-grid">
                  <div class="meta-cell"><small>是否允许</small><strong>{{ policy.allowed ? '允许' : '不允许' }}</strong></div>
                  <div class="meta-cell"><small>规则码</small><strong>{{ policy.code || '—' }}</strong></div>
                  <div class="meta-cell"><small>政策版本</small><strong>{{ policy.policyVersion || '—' }}</strong></div>
                  <div class="meta-cell"><small>条款</small><strong>{{ policy.clauseId || '—' }}</strong></div>
                  <div class="meta-cell"><small>可退上限</small><strong>{{ policy.maxRefundableCents == null ? '—' : money(policy.maxRefundableCents) }}</strong></div>
                  <div class="meta-cell"><small>需人工确认</small><strong>{{ policy.needHumanConfirm ? '是' : '否' }}</strong></div>
                </div>
                <div v-if="!policy.allowed" class="notice notice--warn">
                  发送时会被 Java 规则引擎拦截；请改用转人工或与客户说明政策。
                </div>
              </template>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>工具调用</h2>
              <span class="hint">按步骤递增</span>
            </div>
            <div class="panel-body">
              <EmptyState v-if="!toolCalls.length" title="没有工具调用" description="本次生成未查询订单或物流。" />
              <div v-else class="tool-list">
                <div v-for="call in toolCalls" :key="`${call.step}-${call.name}`" class="tool-row">
                  <div>
                    <strong style="font-size: 12px">{{ call.step }}. {{ call.name }}</strong>
                    <small>{{ call.summary || '无摘要' }}</small>
                  </div>
                  <div style="text-align: right">
                    <span :class="call.ok ? 'tool-ok' : 'tool-fail'">
                      {{ call.ok ? 'OK' : (call.errorCode || 'FAILED') }}
                    </span>
                    <small>{{ call.latencyMs ?? '—' }} ms</small>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><h2>引用依据</h2></div>
            <div class="panel-body">
              <EmptyState v-if="!citations.length" title="没有引用" description="草稿未附政策条款。" />
              <div v-else class="citations">
                <div v-for="citation in citations" :key="`${citation.docId}#${citation.clauseId}`" class="citation">
                  {{ citation.title }}
                  <small>{{ citation.docId }}#{{ citation.clauseId || '—' }} · {{ citation.policyVersion }}</small>
                </div>
              </div>
            </div>
          </section>
        </div>

        <!-- 右栏：草稿修订与最终动作 -->
        <div class="agent-col">
          <section class="panel">
            <div class="panel-head">
              <h2>草稿复核</h2>
              <span v-if="draft" class="pill pill--draft"><span class="pill-dot"></span>v{{ draft.draftVersion }}</span>
            </div>
            <div class="panel-body draft-panel">
              <EmptyState
                v-if="!draft"
                title="暂无草稿"
                description="等待 AI 生成，或当前状态不允许生成草稿。"
              />

              <template v-else>
                <div class="draft-summary">
                  <span class="chip">{{ draft.replyType }}</span>
                  <span class="chip">{{ draft.suggestedAction?.action || 'NONE' }}</span>
                  <span v-if="draft.confidence != null" class="chip">置信度 {{ Math.round(draft.confidence * 100) }}%</span>
                  <span v-if="draft.superseded" class="chip">已失效</span>
                </div>

                <div class="field">
                  <label for="draftText">给客户的回复</label>
                  <textarea
                    id="draftText"
                    v-model="draftText"
                    class="textarea draft-textarea"
                    maxlength="500"
                    placeholder="修改后再发送…"
                  ></textarea>
                  <div class="char-count">{{ draftText.length }} / 500 · {{ edited ? '已修改' : '未修改，发送按钮已置灰' }}</div>
                </div>

                <div v-if="needReview" class="field">
                  <label for="reviewNote">复核说明（必填）</label>
                  <textarea
                    id="reviewNote"
                    v-model="reviewNote"
                    class="textarea"
                    maxlength="500"
                    rows="2"
                    placeholder="例如：已核对订单未发货，整单退款 5800 分，符合七天无理由。"
                  ></textarea>
                  <span class="hint">至少 5 个字；会写入审计日志。</span>
                </div>

                <div class="draft-toolbar">
                  <span class="hint">发送即代表坐席确认；Java 会再次校验版本与政策。</span>
                  <button
                    class="btn btn--primary"
                    type="button"
                    :disabled="!canSend || busy === 'send'"
                    @click="send"
                  >
                    {{ busy === 'send' ? '发送中…' : '确认发送' }}
                  </button>
                </div>

                <div class="action-grid">
                  <button
                    class="btn"
                    type="button"
                    :disabled="!canRegenerate || Boolean(busy)"
                    @click="regenerate"
                  >
                    重新生成
                  </button>
                  <button
                    class="btn"
                    type="button"
                    :disabled="!canHandoff || Boolean(busy)"
                    @click="handoffOpen = true"
                  >
                    转人工
                  </button>
                </div>
              </template>
            </div>
          </section>

          <section v-if="canReply" class="panel">
            <div class="panel-head"><h2>人工回复</h2></div>
            <div class="panel-body grid">
              <div class="field">
                <label for="replyText">回复客户</label>
                <textarea
                  id="replyText"
                  v-model="replyText"
                  class="textarea"
                  maxlength="500"
                  rows="3"
                  placeholder="说明已转人工、后续处理安排…"
                ></textarea>
              </div>
              <button class="btn btn--primary" type="button" :disabled="!replyText.trim() || Boolean(busy)" @click="reply">
                {{ busy === 'reply' ? '发送中…' : '发送人工回复' }}
              </button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><h2>其他动作</h2></div>
            <div class="panel-body grid">
              <button
                class="btn btn--danger"
                type="button"
                :disabled="!canClose || Boolean(busy)"
                @click="close"
              >
                {{ busy === 'close' ? '关闭中…' : '关闭工单' }}
              </button>
              <p class="hint">
                关闭只允许在“待人工”或“已回复”状态执行；退款执行失败时工单会停在“已确认”，需刷新查看。
              </p>
            </div>
          </section>
        </div>
      </div>
    </template>

    <div v-if="handoffOpen" class="modal-backdrop" @click.self="handoffOpen = false">
      <div class="modal">
        <div class="modal-head">
          <h2>转人工</h2>
          <button class="btn btn--small btn--ghost" type="button" @click="handoffOpen = false">关闭</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label for="reason">转交原因</label>
            <select id="reason" v-model="handoffReason" class="select">
              <option v-for="reason in REASONS" :key="reason.value" :value="reason.value">
                {{ reason.label }}（{{ reason.value }}）
              </option>
            </select>
            <span class="hint">原因会写入工单与审计日志，客户侧不会看到内部代码。</span>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="handoffOpen = false">取消</button>
          <button class="btn btn--primary" type="button" :disabled="busy === 'handoff'" @click="handoff">
            {{ busy === 'handoff' ? '转交中…' : '确认转交' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>
