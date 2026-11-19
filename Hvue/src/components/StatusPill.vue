<script setup>
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, default: '' }
})

// 坐席看到原始状态；客户只看到 displayState。两种都做可读映射。
const AGENT_LABELS = {
  OPEN: '已建单',
  PENDING_ACCEPT: '待接入',
  AI_RUNNING: 'AI 处理中',
  WAITING_INPUT: '待补充',
  DRAFT_READY: '草稿待确认',
  CONFIRMED: '已确认',
  EXECUTING: '执行中',
  REPLIED: '已回复',
  TRANSFERRED: '待人工',
  CLOSED: '已完成',
  CANCELLED: '已取消'
}

const TONES = {
  处理中: 'progress',
  待补充信息: 'wait',
  待人工处理: 'human',
  已回复: 'reply',
  已完成: 'done',
  已取消: 'cancel',
  已建单: 'progress',
  待接入: 'progress',
  'AI 处理中': 'progress',
  待补充: 'wait',
  草稿待确认: 'draft',
  已确认: 'progress',
  执行中: 'progress',
  待人工: 'human',
  已取消: 'cancel'
}

const label = computed(() => AGENT_LABELS[props.state] || props.state || '未知状态')
const tone = computed(() => TONES[label.value] || 'progress')
</script>

<template>
  <span class="pill" :class="`pill--${tone}`">
    <span class="pill-dot"></span>{{ label }}
  </span>
</template>
