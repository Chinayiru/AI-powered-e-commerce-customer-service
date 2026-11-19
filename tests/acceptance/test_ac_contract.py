"""契约类 AC：01–05、11、12、15、18、26。

断言纪律：只读 fixture，时间用 conftest.NOW 注入，金额比整数分。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.adapters.normalize import to_cents
from app.contracts.models import (
    AftersalesType,
    CaseStatus,
    DomainError,
    ErrorCode,
    OrderStatus,
    RefundPolicy,
    SendGate,
    Signals,
    Verdict,
)
from app.core.pipeline import _check_citations
from app.domain.cases import CaseService
from app.policy.drafts import shape_draft
from app.policy.refund_policy import evaluate
from app.contracts.models import Citation
from conftest import NOW, run_fixture

APP = Path(__file__).resolve().parents[2] / "app"


def policy(**kw) -> RefundPolicy:
    base = dict(version="2026-11-09.1", auto_limit_cents=5000, human_floor_cents=5000, window_days=7)
    base.update(kw)
    return RefundPolicy(**base)


def signals(**kw) -> Signals:
    base = dict(
        order_status=OrderStatus.DELIVERED,
        signed_at=datetime(2026, 11, 5, 7, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc),
        now=NOW,
        amount_cents=3000,
        paid_cents=3000,
        evidence_provided=True,
    )
    base.update(kw)
    return Signals(**base)


# ---------------------------------------------------------------- AC01
def test_ac01_cent_and_yuan_both_normalize_to_integer_cents():
    assert to_cents("1230", "cent") == 1230
    assert to_cents("12.30", "yuan") == 1230
    _, adapter = run_fixture("dy_2001")
    order = adapter.fetch_order("DY2001")
    assert isinstance(order.paid_cents, int)
    assert order.paid_cents == 12000  # "120.00" 元 → 12000 分，float 不进领域层


# ---------------------------------------------------------------- AC02
def test_ac02_two_packages_takes_latest_delivered_at():
    _, adapter = run_fixture("tb_1002")
    order = adapter.fetch_order("TB1002")
    assert len(order.shipments) == 2
    # 只有 A 签收（2026-11-03 12:00 +08 = 04:00Z）；B 未签收不得参与
    assert order.last_delivered_at == datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- AC03
def test_ac03_missing_state_is_anomaly_not_a_guess():
    result, _ = run_fixture("dy_2002")
    assert result.out.send_gate is SendGate.human
    assert "R_PLATFORM_ANOMALY" in [c.value for c in result.out.reason_codes]
    assert result.out.verdict is Verdict.undecided


# ---------------------------------------------------------------- AC04
PLATFORM_FIELDS = re.compile(
    r"\b(refund_fee|refund_amount|out_sid|consign_time|delivery_time|pay_amount|product_items|track_no|ship_time|receive_time)\b"
)


def test_ac04_platform_field_names_do_not_leak_outside_adapters():
    hits: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if "adapters" in path.parts:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PLATFORM_FIELDS.search(line):
                hits.append(f"{path.relative_to(APP.parent)}:{i}:{line.strip()}")
    assert hits == [], "平台字段泄漏到领域层：\n" + "\n".join(hits)


# ---------------------------------------------------------------- AC05
def test_ac05_duplicate_platform_event_is_deduped_per_case():
    _, adapter = run_fixture("dy_2003")
    cases = adapter.fetch_cases("DY2003")
    assert len(cases) == 1
    assert len(cases[0].events) == 1  # 平台推了两次 apply，只留一条


# ---------------------------------------------------------------- AC11
def test_ac11_approve_after_refunded_is_state_illegal_and_silent():
    result, adapter = run_fixture("tb_1001", confirm="human:demo1")
    case = result.case
    assert case is not None and case.status is CaseStatus.CLOSED
    before = len(case.events)
    with pytest.raises(DomainError) as exc:
        CaseService(adapter).approve(case, approver="demo1", now=NOW)
    assert exc.value.code is ErrorCode.STATE_ILLEGAL
    assert case.status is CaseStatus.CLOSED
    assert len(case.events) == before


# ---------------------------------------------------------------- AC12
def test_ac12_gray_band_is_human_but_approvable():
    decision = evaluate(
        signals(amount_cents=4000, paid_cents=4000),
        policy(auto_limit_cents=3000, human_floor_cents=5000),
    )
    assert decision.verdict is Verdict.approve
    assert decision.send_gate is SendGate.human
    assert decision.primary_reason.value == "R_POLICY_GRAY_BAND"


# ---------------------------------------------------------------- AC15
def test_ac15_human_request_removes_dissuading_copy():
    decision = evaluate(signals(user_requested_human=True), policy())
    assert decision.send_gate is SendGate.human
    assert "R_HUMAN_REQUESTED" in [c.value for c in decision.reason_codes]

    text, flags = shape_draft(
        "我可以帮你处理，不用转人工。请提供订单号。", decision, order_ref="TB9999", user_requested_human=True
    )
    assert "不用转人工" not in text
    assert "我可以帮你处理" not in text
    assert "人工" in text
    assert "HUMAN_REQUESTED" in flags


# ---------------------------------------------------------------- AC18
def test_ac18_unresolved_citation_is_dropped_and_flagged():
    kb = {"QA-1": "七天无理由退货需商品完好。"}
    cites = [
        Citation(qa_id="QA-1", quote="七天无理由退货需商品完好。", source="kb"),
        Citation(qa_id="QA-404", quote="不存在的政策。", source="kb"),
        Citation(qa_id="QA-1", quote="篡改过的引文。", source="kb"),
    ]
    flags: list[str] = []
    kept = _check_citations(cites, kb, flags)
    assert [c.qa_id for c in kept] == ["QA-1"]
    assert "CITATION_UNRESOLVED" in flags
    assert "CITATION_QUOTE_MISMATCH" in flags


# ---------------------------------------------------------------- AC26
def test_ac26_error_codes_are_closed_set():
    assert {c.value for c in ErrorCode} == {
        "E_ORDER_NOT_FOUND",
        "E_PLATFORM_ANOMALY",
        "E_STATE_ILLEGAL",
        "E_CONFIRM_REQUIRED",
        "E_POLICY_BLOCKED",
        "E_BUDGET_EXHAUSTED",
        "E_TIMEOUT",
        "E_INVALID_OUTPUT",
        "E_RETRIEVAL_EMPTY",
        "E_DB_WRITE",
        "E_IDEMPOTENT_REPLAY",
        "E_SCRIPT_MISS",
        "E_INPUT_INVALID",
    }


# -------------------------------------------------- AC09 的域侧半边
def test_ac09_over_paid_is_state_illegal_not_clamped():
    _, adapter = run_fixture("tb_1004")
    with pytest.raises(DomainError) as exc:
        CaseService(adapter).open(
            case_id="C1",
            ticket_id="T1",
            order_ref="TB1004",
            case_type=AftersalesType.refund_only,
            requested_cents=9000,
            paid_cents=8900,
            now=NOW,
        )
    assert exc.value.code is ErrorCode.STATE_ILLEGAL
