<script setup>
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { recentTickets, session } from '../store'
import StatusPill from '../components/StatusPill.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const ticketId = ref('')
const error = ref('')

const recent = computed(() => recentTickets())
const demoCases = [
  { orderNo: 'O1001', scene: '待发货，订单 5800 分', expect: '可退，但金额超过 5000 分，需要复核说明' },
  { orderNo: 'O1002', scene: '已发货，有物流轨迹', expect: '物流答复；申请退款时按退货退款处理' },
  { orderNo: 'O1003', scene: '已签收 30 天', expect: '草稿可生成，但发送时被政策拦截' },
  { orderNo: 'O1006', scene: '待发货，订单 25000 分', expect: '必须填写复核说明' },
  { orderNo: 'O1010', scene: '已全额退款', expect: '转人工，且不生成金额' },
  { orderNo: 'O9999', scene: '不存在的订单', expect: '第一次追问，第二次转人工' }
]

function openTicket(id = ticketId.value) {
  const value = String(id || '').trim().toUpperCase()
  if (!value) {
    error.value = '请输入工单号，例如 T20261111000001。'
    return
  }
  error.value = ''
  router.push(`/agent/tickets/${value}`)
}</script>

<template>
  <div class="page page--wide">
    <div class="page-head">
      <div>
        <div class="eyebrow">Agent Console</div>
        <h1 class="title">坐席工作台</h1>
        <p class="subtitle">
          按工单号进入三栏工作台：左侧看对话与订单，中间核对依据，右侧编辑草稿并做最终裁决。
        </p>
      </div>
      <span class="env-badge"><span class="dot"></span>演示环境 · 未真实退款</span>
    </div>

    <section class="inbox-toolbar">
      <div class="field">
        <label for="ticketId">工单号</label>
        <input
          id="ticketId"
          v-model="ticketId"
          class="input"
          placeholder="T20261111000001"
          autocomplete="off"
          @keydown.enter.prevent="openTicket()"
        />
      </div>
      <div class="field">
        <label for="agentToken">坐席令牌</label>
        <input
          id="agentToken"
          v-model="session.agentToken"
          class="input"
          placeholder="demo-agent-token"
          autocomplete="off"
        />
      </div>
      <button class="btn btn--primary" type="button" @click="openTicket()">打开工单</button>
    </section>

    <div v-if="error" class="error-box" style="margin-top: 12px">
      <strong>!</strong><span>{{ error }}</span>
    </div>

    <div class="queue-grid">
      <section class="panel">
        <div class="panel-head">
          <h2>最近访问过的工单</h2>
          <span class="hint">来自本浏览器缓存</span>
        </div>
        <div class="panel-body">
          <EmptyState
            v-if="!recent.length"
            title="还没有工单"
            description="先到客户入口提交一次咨询，创建后的工单会出现在这里。"
          >
            <RouterLink class="btn btn--small" to="/">去客户入口</RouterLink>
          </EmptyState>
          <table v-else class="queue-table">
            <thead>
              <tr>
                <th>工单</th>
                <th>类型</th>
                <th>状态</th>
                <th>动作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ticket in recent" :key="ticket.ticketId">
                <td><span class="queue-link">{{ ticket.ticketId }}</span></td>
                <td>{{ ticket.category === 'CONSULT' ? '咨询' : '售后' }}</td>
                <td><StatusPill :state="ticket.displayState" /></td>
                <td>
                  <RouterLink class="btn btn--small" :to="`/agent/tickets/${ticket.ticketId}`">
                    进入工作台
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <aside class="side-stack">
        <section class="panel">
          <div class="panel-head"><h2>进入方式</h2></div>
          <div class="panel-body about-list">
            <div class="about-item"><span>1</span><span>在客户入口用 U001 / U002 建单，记下返回的工单号。</span></div>
            <div class="about-item"><span>2</span><span>把工单号粘贴到上方，使用演示坐席令牌打开。</span></div>
            <div class="about-item"><span>3</span><span>坐席视图会显示完整状态、草稿、政策校验与工具调用。</span></div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>演示脚本</h2>
            <span class="hint">订单夹具</span>
          </div>
          <div class="panel-body">
            <table class="queue-table">
              <thead>
                <tr><th>订单</th><th>场景</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in demoCases" :key="item.orderNo">
                  <td><span class="queue-link">{{ item.orderNo }}</span></td>
                  <td>
                    <strong style="font-size: 12px">{{ item.scene }}</strong>
                    <small style="display: block; color: var(--muted); font-size: 10.5px">{{ item.expect }}</small>
                  </td>
                </tr>
              </tbody>
            </table>
            <p class="hint" style="margin-top: 10px">
              这些订单用于创建工单；工单号由服务端生成，不能直接当作订单号使用。
            </p>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
