"""契约不变量的可执行断言（对应 CONTRACT §3/§5/§6/§10）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.contracts.models import (
    AftersalesCase,
    AftersalesType,
    CaseEvent,
    CaseStatus,
    ErrorCode,
    OrderStatus,
    ReasonCode,
    RefundPolicy,
    SendGate,
    Signals,
    Verdict,
)
from app.domain.transitions import TRANSITIONS, assert_transition, can_transition
from app.policy.refund_policy import evaluate

T0 = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(days=2)


def policy(**kw) -> RefundPolicy:
    return RefundPolicy(version="2026-11-09.1", **kw)


def signals(**kw) -> Signals:
    base = dict(
        order_status=OrderStatus.DELIVERED,
        signed_at=T0,
        created_at=T0 - timedelta(days=1),
        now=NOW,
        amount_cents=3000,
        paid_cents=3000,
        evidence_provided=True,
    )
    base.update(kw)
    return Signals(**base)


# ---- 契约 §3.3：金额只允许整数分 ----
def test_cents_rejects_float():
    with pytest.raises(ValidationError):
        signals(amount_cents=12.30)


def test_cents_rejects_negative():
    with pytest.raises(ValidationError):
        signals(amount_cents=-1)


# ---- 契约 §6.1：策略不变量 ----
def test_policy_invariant_rejects_inverted_floor():
    with pytest.raises(ValidationError):
        RefundPolicy(version="x", auto_limit_cents=5000, human_floor_cents=3000)


def test_policy_rejects_bad_window():
    with pytest.raises(ValidationError):
        RefundPolicy(version="x", window_days=-1)


# ---- 契约 §5.2：退货退款截断 ----
def test_awaiting_buyer_ship_has_no_out_edges():
    assert TRANSITIONS[AftersalesType.return_refund][CaseStatus.AWAITING_BUYER_SHIP] == frozenset()
    for dst in CaseStatus:
        assert not can_transition(AftersalesType.return_refund, CaseStatus.AWAITING_BUYER_SHIP, dst)


def test_refund_only_cannot_reach_awaiting_ship():
    assert not can_transition(AftersalesType.refund_only, CaseStatus.REVIEWING, CaseStatus.AWAITING_BUYER_SHIP)


# ---- 契约 §5.1 / §5.3：非法迁移与不可逆确认 ----
def test_illegal_transition_raises():
    with pytest.raises(Exception) as exc:
        assert_transition(AftersalesType.refund_only, CaseStatus.REFUNDED, CaseStatus.APPROVED, "human:a")
    assert exc.value.code is ErrorCode.STATE_ILLEGAL


def test_irreversible_requires_human_actor():
    with pytest.raises(Exception) as exc:
        assert_transition(AftersalesType.refund_only, CaseStatus.APPROVED, CaseStatus.REFUNDING, "model")
    assert exc.value.code is ErrorCode.CONFIRM_REQUIRED
    assert_transition(AftersalesType.refund_only, CaseStatus.APPROVED, CaseStatus.REFUNDING, "human:demo1")


# ---- 契约 §4.2 N5：幂等域是 (case_id, key) ----
def test_event_dedupe_is_per_case_not_global():
    def case(cid: str) -> AftersalesCase:
        return AftersalesCase(
            case_id=cid, ticket_id="T" + cid, order_ref="O1",
            type=AftersalesType.refund_only,
        )

    a, b = case("C1"), case("C2")
    ev = CaseEvent(event_id="", to_status=CaseStatus.REVIEWING, actor="system", at=NOW)
    a.append_event(ev, "submit")
    a.append_event(ev, "submit")
    b.append_event(ev, "submit")
    assert len(a.events) == 1
    assert len(b.events) == 1  # 同 key 不同 case 不冲突


# ---- 契约 §6.3：金额分档 ----
def test_band_auto():
    d = evaluate(signals(amount_cents=3000), policy(auto_limit_cents=5000, human_floor_cents=5000))
    assert (d.verdict, d.send_gate, d.primary_reason) == (Verdict.approve, SendGate.auto, "R_OK")


def test_band_gray():
    d = evaluate(signals(amount_cents=4000, paid_cents=4000), policy(auto_limit_cents=3000, human_floor_cents=5000))
    assert (d.verdict, d.send_gate, d.primary_reason) == (Verdict.approve, SendGate.human, "R_POLICY_GRAY_BAND")


def test_band_over_limit():
    d = evaluate(signals(amount_cents=12000, paid_cents=12000), policy(auto_limit_cents=5000, human_floor_cents=5000))
    assert (d.verdict, d.send_gate, d.primary_reason) == (Verdict.approve, SendGate.human, "R_AMOUNT_OVER_LIMIT")


# ---- 契约 §6.3：优先级 ----
def test_threat_outranks_amount():
    d = evaluate(
        signals(amount_cents=12000, paid_cents=12000, has_threat=True),
        policy(auto_limit_cents=5000, human_floor_cents=5000),
    )
    assert d.primary_reason is ReasonCode.THREAT_OR_LEGAL
    assert ReasonCode.AMOUNT_OVER_LIMIT in d.reason_codes
    assert d.send_gate is SendGate.human


def test_anomaly_outranks_everything():
    d = evaluate(
        signals(order_status=OrderStatus.UNKNOWN, platform_anomaly=True, has_threat=True),
        policy(),
    )
    assert d.primary_reason is ReasonCode.PLATFORM_ANOMALY
    assert d.verdict is Verdict.undecided


def test_out_of_window_rejects():
    d = evaluate(
        signals(signed_at=NOW - timedelta(days=9)),
        policy(window_days=7),
    )
    assert (d.verdict, d.primary_reason) == (Verdict.reject, "R_OUT_OF_WINDOW")


def test_missing_signed_at_is_anomaly_not_guess():
    d = evaluate(signals(signed_at=None), policy(window_basis="signed_at"))
    assert d.primary_reason is ReasonCode.PLATFORM_ANOMALY
    assert d.send_gate is SendGate.human


def test_partial_cannot_exceed_paid():
    d = evaluate(signals(amount_cents=5000, paid_cents=3000), policy())
    assert (d.verdict, d.primary_reason) == (Verdict.reject, "R_PARTIAL_OVER_RATIO")


# ---- 契约 §10：错误码封闭集 ----
def test_error_codes_are_closed_set():
    assert len(ErrorCode) == 13
