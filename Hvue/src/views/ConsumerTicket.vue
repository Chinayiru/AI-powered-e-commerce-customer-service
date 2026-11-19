<script setup>
// 客户会话页：凭 ticketToken 拉取 ConsumerTicketView，只渲染 displayState 与客户/坐席消息。
// createdTicket 表示咨询已升级为关联售后单，需要记住新单 token 才能继续访问。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError, addMessage, cancelTicket, getTicket, newRequestId } from '../api'
import { rememberTicket, session, tokenFor } from '../store'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()
const ticketId = computed(() => String(route.params.ticketId || ''))

const view = ref(null)
const loading = ref(false)
const error = ref('')
const sending = ref(false)
const cancelling = ref(false)
const draft = ref('')
const manualToken = ref('')
const createdTicket = ref(null)
const messageList = ref(null)
const token = ref(tokenFor(ticketId.value))

const messages = computed(() => view.value?.messages || [])
const reply = computed(() => view.value?.reply || '')
const canCancel = computed(() => {
  if (!view.value) return false
  return !['已完成', '已取消'].includes(view.value.displayState)
})
const isWaitingHuman = computed(() => view.value?.displayState === '待人工处理')

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

async function scrollToLatest() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function load() {
  token.value = tokenFor(ticketId.value)
  if (!token.value) {
    error.value = ''
    view.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    view.value = await getTicket(ticketId.value, token.value)
    await scrollToLatest()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '工单加载失败'
  } finally {
    loading.value = false
  }
}

function saveManualToken() {
  const value = manualToken.value.trim()
  if (!value) return
  rememberTicket({ ticketId: ticketId.value, ticketToken: value, userId: session.userId })
  manualToken.value = ''
  load()
}

async function send() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  sending.value = true
  error.value = ''
  createdTicket.value = null
  try {
    const result = await addMessage(ticketId.value, token.value, text, newRequestId())
    draft.value = ''
    if (result.createdTicket) {
      createdTicket.value = result.createdTicket
      rememberTicket({ ...result.createdTicket, userId: session.userId })
    }
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '发送失败，请稍后重试。'
  } finally {
    sending.value = false
  }
}

async function cancel() {
  if (!view.value || cancelling.value) return
  if (!window.confirm('确认撤销这张工单吗？撤销后不能继续对话。')) return
  cancelling.value = true
  error.value = ''
  try {
    await cancelTicket(ticketId.value, token.value, newRequestId(), view.value.version)
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '撤销失败，请刷新后重试。'
  } finally {
    cancelling.value = false
  }
}

onMounted(load)
watch(ticketId, load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">客户会话</div>
        <h1 class="title">我的工单</h1>
        <p class="subtitle">在这里补充信息、查看助手回复；退款等动作仍需人工坐席确认。</p>
      </div>
      <RouterLink class="btn" to="/">返回首页</RouterLink>
    </div>

    <div v-if="error" class="error-box" style="margin-bottom: 14px">
      <strong>!</strong><span>{{ error }}</span>
    </div>

    <div v-if="!token" class="panel">
      <div class="panel-body grid">
        <div>
          <h2 style="font-size: 16px">需要工单访问凭证</h2>
          <p class="subtitle">
            浏览器里没有找到 {{ ticketId }} 的 ticketToken。可以回到首页重新进入，
            或粘贴创建工单时拿到的 token。
          </p>
        </div>
        <div class="form-row">
          <input v-model="manualToken" class="input" placeholder="粘贴 ticketToken" />
          <button class="btn btn--primary" type="button" @click="saveManualToken">使用该凭证</button>
        </div>
        <RouterLink class="btn btn--ghost" to="/">回到客户入口</RouterLink>
      </div>
    </div>

    <template v-else>
      <div v-if="loading && !view" class="panel">
        <div class="panel-body empty"><strong>正在读取工单…</strong></div>
      </div>

      <template v-else-if="view">
        <div class="ticket-banner">
          <div class="ticket-banner-main">
            <span class="ticket-banner-id">{{ view.ticketId }}</span>
            <StatusPill :state="view.displayState" />
            <span class="ticket-banner-meta">第 {{ view.version }} 版 · 更新于 {{ formatTime(view.updatedAt) }}</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <button class="btn btn--small" type="button" :disabled="loading" @click="load">
              {{ loading ? '刷新中…' : '刷新' }}
            </button>
            <button
              v-if="canCancel"
              class="btn btn--small btn--danger"
              type="button"
              :disabled="cancelling"
              @click="cancel"
            >
              {{ cancelling ? '撤销中…' : '撤销工单' }}
            </button>
          </div>
        </div>

        <div v-if="createdTicket" class="notice" style="margin-top: 12px">
          已根据本次咨询创建关联售后单
          <RouterLink :to="`/tickets/${createdTicket.ticketId}`">
            <strong>{{ createdTicket.ticketId }}</strong>
          </RouterLink>
          ，可以继续补充订单信息或等待坐席处理。
        </div>

        <div class="chat-grid">
          <section class="panel chat-panel">
            <div class="panel-head">
              <h2>对话记录</h2>
              <span class="hint">共 {{ messages.length }} 条 · 仅展示客户与坐席消息</span>
            </div>

            <div ref="messageList" class="message-list">
              <EmptyState
                v-if="!messages.length"
                title="还没有消息"
                description="在下方描述你的问题，助手会先核对。"
              />
              <div
                v-for="message in messages"
                :key="message.id"
                class="message-row"
                :class="{ 'message-row--customer': message.role === 'CUSTOMER' }"
              >
                <span class="avatar">{{ message.role === 'CUSTOMER' ? '我' : '服' }}</span>
                <div class="message-body">
                  <div class="message-meta">
                    {{ message.role === 'CUSTOMER' ? '我' : '售后助手' }} · {{ formatTime(message.createdAt) }}
                  </div>
                  <div class="message-bubble">{{ message.text }}</div>
                </div>
              </div>

              <div v-if="isWaitingHuman" class="message--system">已转交人工坐席，请耐心等待</div>
            </div>

            <div class="composer">
              <div style="flex: 1">
                <textarea
                  v-model="draft"
                  class="textarea"
                  maxlength="500"
                  rows="2"
                  placeholder="补充订单号、说明问题，或回复坐席…（Ctrl + Enter 发送）"
                  @keydown.ctrl.enter.prevent="send"
                  @keydown.meta.enter.prevent="send"
                ></textarea>
                <div class="char-count">{{ draft.length }} / 500</div>
              </div>
              <div class="composer-actions">
                <button class="btn btn--primary" type="button" :disabled="sending || !draft.trim()" @click="send">
                  {{ sending ? '发送中…' : '发送' }}
                </button>
              </div>
            </div>
          </section>

          <aside class="side-stack">
            <section class="panel">
              <div class="panel-head"><h2>处理进度</h2></div>
              <div class="panel-body side-card">
                <div class="side-row"><span>当前状态</span><StatusPill :state="view.displayState" /></div>
                <div class="side-row"><span>工单编号</span><span>{{ view.ticketId }}</span></div>
                <div class="side-row"><span>消息数量</span><span>{{ messages.length }} 条</span></div>
                <div class="side-row"><span>版本</span><span>v{{ view.version }}</span></div>
                <div class="notice notice--warn" style="margin-top: 4px">
                  演示环境，所有退款与状态变更均为模拟，不会产生真实资金动作。
                </div>
              </div>
            </section>

            <section v-if="reply" class="panel">
              <div class="panel-head"><h2>最近一条回复</h2></div>
              <div class="panel-body">
                <p style="font-size: 12.5px; color: var(--ink-soft); white-space: pre-wrap">{{ reply }}</p>
              </div>
            </section>

            <section class="panel">
              <div class="panel-head"><h2>接下来会发生什么</h2></div>
              <div class="panel-body about-list">
                <div class="about-item"><span>1</span><span>助手核对订单、物流与政策，并给出处理建议。</span></div>
                <div class="about-item"><span>2</span><span>需要退款的，会生成草稿，由坐席复核金额与依据。</span></div>
                <div class="about-item"><span>3</span><span>坐席确认后，系统模拟执行并关闭工单。</span></div>
              </div>
            </section>
          </aside>
        </div>
      </template>
    </template>
  </div>
</template>
