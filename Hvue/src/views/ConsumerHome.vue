<script setup>
// 客户首页：选择订单、描述问题、创建咨询或售后单。
// 页面只使用对外字段（ticketId / displayState / ticketToken），不展示意图、置信度等内部信息。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, createTicket, listOrders, newRequestId } from '../api'
import { recentTickets, rememberTicket, session } from '../store'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()

const orders = ref([])
const ordersLoading = ref(false)
const ordersError = ref('')
const submitting = ref(false)
const formError = ref('')

const form = reactive({
  category: 'CONSULT',
  orderNo: '',
  text: ''
})

const examples = [
  '我买的订单 O1001 想退款，怎么办？',
  '订单 O1002 的物流到哪了？',
  '已经签收 30 天了还能退吗？',
  '我要投诉，转人工'
]

const selectedOrder = computed(() => orders.value.find((item) => item.orderNo === form.orderNo) || null)
const recent = computed(() => recentTickets().slice(0, 5))
const textLength = computed(() => form.text.length)

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

async function loadOrders() {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    orders.value = await listOrders(session.userId)
  } catch (error) {
    ordersError.value = error instanceof ApiError ? error.message : '订单加载失败'
  } finally {
    ordersLoading.value = false
  }
}

function pickOrder(order) {
  form.orderNo = order.orderNo
}

function useExample(text) {
  form.text = text
  const match = text.match(/O\d{4,8}/i)
  if (match) form.orderNo = match[0].toUpperCase()
}

async function submit() {
  formError.value = ''
  const text = form.text.trim()
  if (!text) {
    formError.value = '请先描述遇到的问题。'
    return
  }
  submitting.value = true
  try {
    const created = await createTicket({
      userId: session.userId,
      category: form.category,
      text,
      orderNo: form.orderNo.trim().toUpperCase(),
      requestId: newRequestId()
    })
    rememberTicket({ ...created, userId: session.userId })
    router.push(`/tickets/${created.ticketId}`)
  } catch (error) {
    formError.value = error instanceof ApiError ? error.message : '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

onMounted(loadOrders)
watch(() => session.userId, loadOrders)
</script>

<template>
  <div class="page">
    <section class="hero">
      <div class="hero-copy">
        <div class="eyebrow">After-sale Copilot</div>
        <h1>把售后问题说清楚，剩下的交给助手。</h1>
        <p>
          描述订单问题后，助手会先核对订单与政策，再生成处理建议；涉及退款等资金动作，
          必须由人工坐席确认后才会提交。当前为演示环境，所有执行均为模拟。
        </p>
        <div class="hero-points">
          <span class="hero-point">Java 唯一裁决</span>
          <span class="hero-point">Python 只读建议</span>
          <span class="hero-point">人工确认后才执行</span>
          <span class="hero-point">全链路可审计</span>
        </div>
      </div>
      <aside class="hero-side">
        <h2>一次完整处理</h2>
        <div class="hero-steps">
          <div class="hero-step"><span>1</span><span>选择订单，描述问题</span></div>
          <div class="hero-step"><span>2</span><span>助手核对订单、政策与物流</span></div>
          <div class="hero-step"><span>3</span><span>坐席复核草稿并确认</span></div>
          <div class="hero-step"><span>4</span><span>模拟执行并留下审计记录</span></div>
        </div>
      </aside>
    </section>

    <div class="home-grid">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>发起新咨询</h2>
            <p class="subtitle">咨询用于问政策、查物流；明确要退款时，助手会转成售后单处理。</p>
          </div>
          <span class="pill pill--progress"><span class="pill-dot"></span>{{ session.userId }}</span>
        </div>
        <div class="panel-body">
          <form class="grid" @submit.prevent="submit">
            <div class="field">
              <label>问题类型</label>
              <div class="chip-row" style="margin-top: 0">
                <button
                  type="button"
                  class="chip"
                  :class="{ 'chip--active': form.category === 'CONSULT' }"
                  @click="form.category = 'CONSULT'"
                >
                  咨询 / 政策 / 物流
                </button>
                <button
                  type="button"
                  class="chip"
                  :class="{ 'chip--active': form.category === 'AFTERSALE' }"
                  @click="form.category = 'AFTERSALE'"
                >
                  直接申请售后
                </button>
              </div>
              <span class="hint">
                {{ form.category === 'CONSULT'
                  ? '先答疑，必要时再生成售后单。'
                  : '直接进入售后流程，需要订单号才能生成草稿。' }}
              </span>
            </div>

            <div class="field">
              <label for="orderNo">订单号（可选）</label>
              <div class="form-row">
                <input
                  id="orderNo"
                  v-model="form.orderNo"
                  class="input"
                  placeholder="例如 O1001"
                  autocomplete="off"
                />
                <button type="button" class="btn" :disabled="ordersLoading" @click="loadOrders">
                  {{ ordersLoading ? '刷新中…' : '刷新订单' }}
                </button>
              </div>
              <span v-if="selectedOrder" class="hint">
                {{ selectedOrder.statusLabel }} · 订单金额 {{ money(selectedOrder.amountCents) }}
              </span>
            </div>

            <div class="field">
              <label for="message">问题描述</label>
              <textarea
                id="message"
                v-model="form.text"
                class="textarea"
                maxlength="500"
                rows="4"
                placeholder="请说明订单、商品和遇到的问题，例如：订单 O1001 还没发货，我想退款。"
              ></textarea>
              <div class="char-count">{{ textLength }} / 500</div>
            </div>

            <div class="chip-row">
              <button
                v-for="example in examples"
                :key="example"
                type="button"
                class="chip"
                @click="useExample(example)"
              >
                {{ example }}
              </button>
            </div>

            <div v-if="formError" class="error-box">
              <strong>!</strong><span>{{ formError }}</span>
            </div>

            <div class="draft-toolbar">
              <span class="hint">提交即表示同意由助手先做一次自动核对；不会立即退款。</span>
              <button class="btn btn--primary" type="submit" :disabled="submitting">
                {{ submitting ? '正在提交…' : '提交并开始处理' }}
              </button>
            </div>
          </form>
        </div>
      </section>

      <div class="side-stack">
        <section class="panel">
          <div class="panel-head">
            <h2>我的订单</h2>
            <span class="hint">演示夹具 · {{ session.userId }}</span>
          </div>
          <div class="panel-body">
            <div v-if="ordersError" class="error-box" style="margin-bottom: 10px">
              <strong>!</strong><span>{{ ordersError }}</span>
            </div>
            <div v-if="ordersLoading" class="empty"><strong>正在读取订单…</strong></div>
            <EmptyState
              v-else-if="!orders.length"
              title="没有可用订单"
              description="确认 Java 服务已启动，或切换演示用户后再试。"
            />
            <div v-else class="order-list">
              <button
                v-for="order in orders"
                :key="order.orderNo"
                type="button"
                class="order-card"
                :class="{ 'order-card--active': form.orderNo === order.orderNo }"
                @click="pickOrder(order)"
              >
                <span class="order-thumb">{{ order.orderNo.slice(-2) }}</span>
                <span class="order-main">
                  <strong>{{ order.orderNo }}</strong>
                  <small>{{ order.statusLabel }} · 点击填入订单号</small>
                </span>
                <span class="order-price">{{ money(order.amountCents) }}</span>
              </button>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>我最近的工单</h2>
            <span class="hint">仅保存在本浏览器</span>
          </div>
          <div class="panel-body">
            <EmptyState
              v-if="!recent.length"
              title="还没有工单"
              description="提交一次咨询后，工单会出现在这里。"
            />
            <div v-else class="recent-list">
              <RouterLink
                v-for="ticket in recent"
                :key="ticket.ticketId"
                class="recent-item"
                :to="`/tickets/${ticket.ticketId}`"
              >
                <span>
                  <span class="recent-id">{{ ticket.ticketId }}</span>
                  <small>{{ ticket.category === 'CONSULT' ? '咨询' : '售后' }} · {{ formatTime(ticket.updatedAt) }}</small>
                </span>
                <StatusPill :state="ticket.displayState" />
              </RouterLink>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
