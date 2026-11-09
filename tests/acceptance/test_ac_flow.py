"""功能类 AC：06–10、13、14、20–23。

每条只盯一个失败原因：状态序列看 case.status/events，策略看 policy.verdict，
降级看 stop_reason，不看"草稿里有没有某几个字"这种模糊断言（AC08 的禁词除外）。
"""
from __future__ import annotations

import json

from app.contracts.models import CaseStatus, LLMConfig, StopReason, Verdict
from app.domain.transitions import TRANSITIONS
from app.llm.prompts import prompt_version
from app.llm.scripted import ScriptedProvider
from conftest import run_fixture

# ---------------------------------------------------------------- AC06
def test_ac06_unship_within_limit_closes_the_loop():
    result, adapter = run_fixture("tb_1001", confirm="human:demo1")
    out = result.out
    assert out.stop_reason is StopReason.finalized
    assert out.case is not None
    assert out.case.status is CaseStatus.CLOSED
    seq = [e.to_status for e in result.case.events]
    assert seq == [
        CaseStatus.REVIEWING,
        CaseStatus.APPROVED,
        CaseStatus.REFUNDING,
        CaseStatus.REFUNDED,
        CaseStatus.CLOSED,
    ]
    assert adapter.refund_calls == [("CTTB1001", 5000, "human:demo1")]


# ---------------------------------------------------------------- AC07
def test_ac07_over_limit_stops_before_approval():
    result, _ = run_fixture("dy_2001")
    out = result.out
    assert out.verdict is Verdict.approve
    assert out.send_gate.value == "human"
    assert out.case.status is CaseStatus.REVIEWING
    assert "R_AMOUNT_OVER_LIMIT" in [c.value for c in out.reason_codes]


# ---------------------------------------------------------------- AC08
def test_ac08_out_of_window_reject_has_no_promise_words():
    result, _ = run_fixture("tb_1003")
    out = result.out
    assert out.verdict is Verdict.reject
    assert result.trace["policy"]["primary_reason"] == "R_OUT_OF_WINDOW"
    for banned in ("退款将在", "已退款", "已原路退回"):
        assert banned not in out.draft.text
    assert "不支持退款" in out.draft.text or "不符合退款条件" in out.draft.text


# ---------------------------------------------------------------- AC09
def test_ac09_partial_never_exceeds_paid():
    result, _ = run_fixture("tb_1004")
    out = result.out
    assert out.verdict is Verdict.partial
    approved = result.trace["policy"]["approved_amount_cents"]
    assert approved == 2000
    assert approved <= 8900


# ---------------------------------------------------------------- AC10
def test_ac10_return_refund_stops_at_awaiting_buyer_ship():
    result, _ = run_fixture("dy_2004", confirm="human:demo1")
    assert result.out.case.status is CaseStatus.AWAITING_BUYER_SHIP
    assert TRANSITIONS[result.case.type][CaseStatus.AWAITING_BUYER_SHIP] == frozenset()


# ---------------------------------------------------------------- AC13
def test_ac13_digital_category_is_excluded():
    result, _ = run_fixture("tb_1006")
    out = result.out
    assert out.verdict is Verdict.reject
    assert result.trace["policy"]["primary_reason"] == "R_CATEGORY_EXCLUDED"


# ---------------------------------------------------------------- AC14
def test_ac14_threat_goes_human_and_keeps_amount_reason():
    result, _ = run_fixture("tb_1005")
    out = result.out
    assert out.send_gate.value == "human"
    assert "R_THREAT_OR_LEGAL" in [c.value for c in out.reason_codes]
    assert "R_AMOUNT_OVER_LIMIT" in [c.value for c in out.reason_codes]
    assert result.trace["policy"]["primary_reason"] == "R_THREAT_OR_LEGAL"


# ---------------------------------------------------------------- AC20
def test_ac20_scripted_runs_are_byte_identical():
    a, _ = run_fixture("tb_1002")
    b, _ = run_fixture("tb_1002")
    x = a.out.model_dump(mode="json")
    y = b.out.model_dump(mode="json")
    for key in ("run_id", "latency_ms", "tool_calls"):
        x.pop(key, None)
        y.pop(key, None)
    assert json.dumps(x, ensure_ascii=False, sort_keys=True) == json.dumps(y, ensure_ascii=False, sort_keys=True)
    assert x["prompt_version"] == prompt_version()
    assert x["draft"]["text"] == y["draft"]["text"]


# ---------------------------------------------------------------- AC21
def test_ac21_budget_exhausted_emits_no_half_draft():
    result, _ = run_fixture("tb_1001", llm=LLMConfig(model="scripted-v1", token_budget=100))
    out = result.out
    assert out.stop_reason is StopReason.budget_exhausted
    assert out.draft.text == ""


# ---------------------------------------------------------------- AC22
def test_ac22_timeout_marks_usage_estimated_and_no_draft():
    result, _ = run_fixture(
        "tb_1001",
        provider=ScriptedProvider(delay_ms=200),
        llm=LLMConfig(model="scripted-v1", timeout_ms=50),
    )
    out = result.out
    assert out.stop_reason is StopReason.timeout
    assert out.usage.estimated is True
    assert out.draft.text == ""


# ---------------------------------------------------------------- AC23
def test_ac23_one_bad_json_recovers_with_a_retry():
    result, _ = run_fixture("tb_1003", provider=ScriptedProvider(bad_first={"TB1003": 1}))
    assert result.out.stop_reason is StopReason.finalized

    result2, _ = run_fixture("tb_1003", provider=ScriptedProvider(bad_first={"TB1003": 2}))
    assert result2.out.stop_reason is StopReason.invalid_output
    assert "degraded" in result2.out.draft.risk_flags
