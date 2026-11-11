package com.chinayiru.aftersale.domain;

/**
 * 转人工原因封闭集（9 个）。原因保持粗粒度：超时/5xx 都归 TOOL_FAILED，
 * 由 AGENT_UNAVAILABLE 与组件日志区分。
 */
public enum TransferReason {
    LOW_CONFIDENCE,
    NO_EVIDENCE,
    POLICY_BLOCKED,
    TOOL_FAILED,
    AMBIGUOUS_ORDER,
    ORDER_NOT_FOUND,
    OUT_OF_SCOPE,
    USER_REQUESTED,
    INSUFFICIENT_INFO
}
