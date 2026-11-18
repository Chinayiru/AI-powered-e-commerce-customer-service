import type { Platform } from './types'

export const PLATFORM_LABEL: Record<Platform, string> = {
  taobao: '淘宝',
  douyin: '抖店',
}

export const INTENT_LABEL: Record<string, string> = {
  refund: '退款',
  address_change: '改地址',
  shipping_urge: '催发货',
  other: '其他',
}

export const AFTERSALES_LABEL: Record<string, string> = {
  refund_only: '仅退款',
  return_refund: '退货退款',
}

export const VERDICT_LABEL: Record<string, string> = {
  approve: '建议同意',
  partial: '部分同意',
  reject: '建议拒绝',
  undecided: '未决 / 转人工',
}

export const GATE_LABEL: Record<string, string> = {
  auto: '自动发送',
  human: '人工发送',
}

export const STOP_LABEL: Record<string, string> = {
  finalized: '已定稿',
  budget_exhausted: '预算耗尽',
  timeout: '超时',
  invalid_output: '输出非法',
  rejected: '已拒绝',
  degraded: '降级',
}

export const ORDER_STATUS_LABEL: Record<string, string> = {
  CREATED: '待付款',
  PAID: '待发货',
  SHIPPED: '运输中',
  DELIVERED: '已签收',
  CLOSED: '已关闭',
  CANCELLED: '已取消',
  UNKNOWN: '未知（平台值无法映射）',
}

export const CASE_STATUS_LABEL: Record<string, string> = {
  INITIATED: '已发起',
  REVIEWING: '审核中',
  APPROVED: '审核通过',
  REFUNDING: '退款中',
  REFUNDED: '已退款',
  CLOSED: '已关单',
  REJECTED: '已拒绝',
  CANCELLED: '已取消',
  AWAITING_BUYER_SHIP: '待买家寄回',
}

export const REASON_LABEL: Record<string, string> = {
  R_OK: '规则通过',
  R_PLATFORM_ANOMALY: '平台数据异常',
  R_ORDER_NOT_ELIGIBLE: '订单不满足条件',
  R_THREAT_OR_LEGAL: '威胁 / 法务风险',
  R_CATEGORY_EXCLUDED: '类目排除',
  R_OUT_OF_WINDOW: '超出售后窗口',
  R_AMOUNT_OVER_LIMIT: '金额超自动上限',
  R_POLICY_GRAY_BAND: '金额灰带',
  R_MISSING_EVIDENCE: '缺少凭证',
  R_PARTIAL_OVER_RATIO: '部分退款超额',
  R_HUMAN_REQUESTED: '用户要求人工',
  R_MODEL_LOW_CONFIDENCE: '模型低置信',
  R_NOT_A_REFUND: '非退款意图',
  R_MODEL_NEEDS_HUMAN: '模型要求人工',
}

export const AC_TITLE: Record<string, string> = {
  AC01: '分 / 元归一',
  AC02: '多包裹签收口径',
  AC03: '缺状态不补默认值',
  AC04: '平台字段不越界',
  AC05: '事件幂等域',
  AC06: '仅退款闭环',
  AC07: '已签收大额转人工',
  AC08: '超窗拒绝口径',
  AC09: '部分退款不超实付',
  AC10: '退货退款截断',
  AC11: '非法迁移不改状态',
  AC12: '灰带可批不自动',
  AC13: '类目排除',
  AC14: '威胁优先转人工',
  AC15: '转人工话术',
  AC16: '按旧版本回放',
  AC17: '关键词召回基线',
  AC18: '引用可追溯',
  AC19: '向量增益不足关闭',
  AC20: '同输入完全一致',
  AC21: '预算耗尽不留半稿',
  AC22: '超时降级',
  AC23: '坏输出重试一次',
  AC24: '基线封存',
  AC25: '敏感信息脱敏',
  AC26: '错误码封闭集',
}

export const AC_STATUS_LABEL: Record<string, string> = {
  passed: '通过',
  failed: '失败',
  self: '自证',
  skipped: '跳过',
}
