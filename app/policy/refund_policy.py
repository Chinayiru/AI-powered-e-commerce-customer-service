"""策略层：纯函数，确定性，可表驱动。

verdict 看业务事实，send_gate 看风险，两者正交（CONTRACT §6.2）。
模型永远只是输入信号之一，不能决定 send_gate（ADR-007）。

判定顺序按 CONTRACT §6.3 的 P0–P10：
- P0 平台异常意味着"事实不可用"，此时**不允许**给出 approve/reject 这类业务结论，
  verdict 固定 undecided；其余规则只允许追加 reason_code，不能翻转 verdict。
- 早期实现里 P1 会把 anomaly 的 undecided 覆盖成 reject，这是一类典型缺陷：
  拿不可信的事实下确定的结论。测试 test_anomaly_outranks_everything 锁死这一点。
"""
from __future__ import annotations

from datetime import timedelta

from app.contracts.models import (
    OrderStatus,
    PolicyDecision,
    ReasonCode,
    RefundPolicy,
    SendGate,
    Signals,
    Verdict,
)

ELIGIBLE_STATUSES = frozenset({OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED})

# 只想影响 send_gate、不影响 verdict 的原因码
GATE_ONLY = frozenset(
    {
        ReasonCode.AMOUNT_OVER_LIMIT,
        ReasonCode.POLICY_GRAY_BAND,
        ReasonCode.MISSING_EVIDENCE,
        ReasonCode.HUMAN_REQUESTED,
        ReasonCode.MODEL_LOW_CONFIDENCE,
        ReasonCode.MODEL_NEEDS_HUMAN,
    }
)

# primary_reason 的优先级：越小越优先，用来回答"这条工单到底卡在哪"
PRIORITY = [
    ReasonCode.NOT_A_REFUND,
    ReasonCode.PLATFORM_ANOMALY,
    ReasonCode.ORDER_NOT_ELIGIBLE,
    ReasonCode.THREAT_OR_LEGAL,
    ReasonCode.CATEGORY_EXCLUDED,
    ReasonCode.OUT_OF_WINDOW,
    ReasonCode.AMOUNT_OVER_LIMIT,
    ReasonCode.POLICY_GRAY_BAND,
    ReasonCode.MISSING_EVIDENCE,
    ReasonCode.PARTIAL_OVER_RATIO,
    ReasonCode.HUMAN_REQUESTED,
    ReasonCode.MODEL_LOW_CONFIDENCE,
]


def evaluate(signals: Signals, policy: RefundPolicy) -> PolicyDecision:
    rule = policy.for_category(signals.category)
    hits: list[ReasonCode] = []

    def hit(code: ReasonCode) -> None:
        if code not in hits:
            hits.append(code)

    anomaly = detect_anomaly(signals, policy)
    if anomaly:
        hit(ReasonCode.PLATFORM_ANOMALY)

    if signals.has_threat:
        hit(ReasonCode.THREAT_OR_LEGAL)

    # ---- 金额分档：只影响 send_gate ----
    if signals.amount_cents > rule.human_floor_cents:
        hit(ReasonCode.AMOUNT_OVER_LIMIT)
    elif signals.amount_cents > rule.auto_limit_cents:
        hit(ReasonCode.POLICY_GRAY_BAND)

    if not signals.evidence_provided:
        hit(ReasonCode.MISSING_EVIDENCE)
    if signals.user_requested_human:
        hit(ReasonCode.HUMAN_REQUESTED)
    if signals.model_confidence < 0.6:
        hit(ReasonCode.MODEL_LOW_CONFIDENCE)

    # ---- 业务结论：异常时一律不下结论 ----
    if anomaly:
        verdict, approved = Verdict.undecided, None
    else:
        verdict, approved = _business_verdict(signals, policy, rule, hit)

    primary = next((c for c in PRIORITY if c in hits), ReasonCode.OK)
    send_gate = SendGate.auto if not hits else SendGate.human

    return PolicyDecision(
        verdict=verdict,
        send_gate=send_gate,
        approved_amount_cents=approved,
        reason_codes=hits or [ReasonCode.OK],
        primary_reason=primary,
        policy_version=policy.version,
    )


def detect_anomaly(signals: Signals, policy: RefundPolicy) -> bool:
    """事实是否可信。不可信就不许下业务结论（AC03）。

    注意：未发货订单本来就没有签收时间，那是正常事实而不是异常。
    只有"声称已发货/已签收，却拿不到签收时间"才算不可信。
    """
    if signals.platform_anomaly or signals.order_status is OrderStatus.UNKNOWN:
        return True
    needs_delivery = signals.order_status in {OrderStatus.SHIPPED, OrderStatus.DELIVERED}
    if policy.window_basis == "signed_at" and needs_delivery and signals.signed_at is None:
        return True
    return False


def _business_verdict(
    signals: Signals,
    policy: RefundPolicy,
    rule,
    hit,
) -> tuple[Verdict, int | None]:
    if signals.order_status not in ELIGIBLE_STATUSES:
        hit(ReasonCode.ORDER_NOT_ELIGIBLE)
        return Verdict.reject, None

    if rule.excluded:
        hit(ReasonCode.CATEGORY_EXCLUDED)
        return Verdict.reject, None

    anchor = signals.signed_at if policy.window_basis == "signed_at" else signals.created_at
    if anchor is not None and signals.now - anchor > timedelta(days=policy.window_days):
        hit(ReasonCode.OUT_OF_WINDOW)
        return Verdict.reject, None

    if signals.amount_cents > signals.paid_cents:
        hit(ReasonCode.PARTIAL_OVER_RATIO)
        return Verdict.reject, None

    if signals.has_threat:
        return Verdict.undecided, None

    if signals.paid_cents > 0 and signals.amount_cents < signals.paid_cents:
        ratio = signals.amount_cents / signals.paid_cents
        if ratio > policy.max_partial_ratio:
            hit(ReasonCode.PARTIAL_OVER_RATIO)
            return Verdict.undecided, None
        return Verdict.partial, signals.amount_cents

    return Verdict.approve, signals.amount_cents
