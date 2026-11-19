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
    AftersalesType,
    OrderStatus,
    PolicyDecision,
    ReasonCode,
    RefundPolicy,
    SendGate,
    Signals,
    Verdict,
)

ELIGIBLE_STATUSES = frozenset({OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED})

# 只收紧闸门、**保留**原 verdict 的原因码（CONTRACT §6.3 的 P6/P7/P12）
VERDICT_NEUTRAL = frozenset(
    {
        ReasonCode.AMOUNT_OVER_LIMIT,
        ReasonCode.POLICY_GRAY_BAND,
        ReasonCode.MODEL_NEEDS_HUMAN,
    }
)

# 契约写死 verdict=undecided 的原因码（P8/P10/P11）：事实不清或人不让发，
# 就不许给出 approve/partial——拒绝文案也是对外承诺，何况还有打款动作。
UNDECIDED_ONLY = frozenset(
    {
        ReasonCode.MISSING_EVIDENCE,
        ReasonCode.HUMAN_REQUESTED,
        ReasonCode.MODEL_LOW_CONFIDENCE,
    }
)

# primary_reason 的优先级：越小越优先，用来回答"这条工单到底卡在哪"。
# 顺序必须与 CONTRACT §6.3 的 P0–P12 一一对应，否则 primary 会挑到表外的东西。
PRIORITY = [
    ReasonCode.NOT_A_REFUND,
    ReasonCode.PLATFORM_ANOMALY,
    ReasonCode.ORDER_NOT_ELIGIBLE,
    ReasonCode.THREAT_OR_LEGAL,
    ReasonCode.CATEGORY_EXCLUDED,
    ReasonCode.OUT_OF_WINDOW,
    ReasonCode.AMOUNT_OVER_PAID,
    ReasonCode.AMOUNT_OVER_LIMIT,
    ReasonCode.POLICY_GRAY_BAND,
    ReasonCode.MISSING_EVIDENCE,
    ReasonCode.PARTIAL_OVER_RATIO,
    ReasonCode.HUMAN_REQUESTED,
    ReasonCode.MODEL_LOW_CONFIDENCE,
    ReasonCode.MODEL_NEEDS_HUMAN,
]


def primary_of(codes: list[ReasonCode] | tuple[ReasonCode, ...]) -> ReasonCode:
    """按契约优先级挑 primary；表里没有的码不许当 primary（否则排序不可解释）。"""
    return next((c for c in PRIORITY if c in codes), ReasonCode.OK)


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

    # P8 缺凭证：只对"仅退款"生效。退货退款此时买家还没寄回，凭证在寄回验收环节看（AC10），
    # 否则所有退货退款都会永远停在 undecided，退货流程根本走不到 AWAITING_BUYER_SHIP。
    if not signals.evidence_provided and signals.aftersales_type is not AftersalesType.return_refund:
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
        # P8/P10/P11：缺凭证 / 用户要人工 / 模型低置信 → 契约要求 undecided。
        # 只在业务结论是"可退"（approve/partial）时降级：reject 由更早的 P2/P4/P5 决定，优先级更高。
        if verdict in (Verdict.approve, Verdict.partial) and any(c in UNDECIDED_ONLY for c in hits):
            verdict, approved = Verdict.undecided, None

    primary = primary_of(hits)
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
        hit(ReasonCode.AMOUNT_OVER_PAID)
        return Verdict.reject, None

    if signals.has_threat:
        return Verdict.undecided, None

    if signals.paid_cents > 0 and signals.amount_cents < signals.paid_cents:
        ratio = signals.amount_cents / signals.paid_cents
        if ratio > policy.max_partial_ratio:
            # P9：请求比例超上限只批到上限（partial），仍需人工确认；不是整单拒绝
            hit(ReasonCode.PARTIAL_OVER_RATIO)
            return Verdict.partial, int(signals.paid_cents * policy.max_partial_ratio)
        return Verdict.partial, signals.amount_cents

    return Verdict.approve, signals.amount_cents
