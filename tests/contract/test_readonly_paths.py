"""只读意图（address_change / shipping_urgue / other）的边界断言。

文档未为它们单开 AC 编号：它们共用 AC15（人工话术）与 AC20（确定性），
这里把"不能落退款单、不能自动发、不能调打款"固化成契约测试。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.adapters.base import FixtureAdapter
from app.cli import FIXTURES, default_policy
from app.contracts.models import Intent, LLMConfig, ReasonCode, SendGate, TicketIn, Verdict
from app.core.pipeline import run
from app.llm.base import LLMResponse
from app.llm.prompts import prompt_version

NOW = datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc)


@dataclass
class FixedProvider:
    payload: dict

    name = "scripted"
    model = "scripted-v1"

    def propose(self, prompt: str, key: str) -> LLMResponse:
        raw = json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(raw=raw, input_tokens=len(prompt) // 4, output_tokens=len(raw) // 4)


def _payload(**over) -> dict:
    base = {
        "intent": "address_change",
        "aftersales_type": None,
        "slots": {"order_ref": "TB1001"},
        "draft": "您好，收货地址修改需要核实身份，已为您转人工处理。",
        "citations": [],
        "confidence": 0.9,
        "needs_human": False,
    }
    base.update(over)
    return base


def _run(payload: dict, *, confirm: str | None = "human:demo1"):
    adapter = FixtureAdapter(FIXTURES, "taobao")
    ticket = TicketIn(
        ticket_id="TK100001",
        user_id="u_1",
        text="麻烦帮我改一下收货地址到公司",
        order_ref="TB1001",
        created_at=NOW,
    )
    res = run(
        ticket,
        adapter=adapter,
        provider=FixedProvider(payload),
        policy=default_policy(),
        llm=LLMConfig(prompt_version=prompt_version()),
        now=NOW,
        confirm=confirm,
    )
    return res, adapter


@pytest.mark.parametrize(
    "intent",
    [Intent.address_change, Intent.shipping_urge, Intent.other],
)
def test_readonly_intent_never_touches_refund(intent):
    res, adapter = _run(_payload(intent=intent.value))
    assert res.case is None
    assert adapter.refund_calls == []
    assert res.out.verdict is Verdict.undecided
    assert res.out.send_gate is SendGate.human
    assert ReasonCode.NOT_A_REFUND in res.out.reason_codes
    assert res.out.reason_codes[0] is ReasonCode.NOT_A_REFUND
    assert res.out.draft.text


def test_model_may_not_self_authorize_auto_send():
    payload = _payload(
        intent="refund",
        aftersales_type="refund_only",
        slots={"order_ref": "TB1001", "amount_cents": 5000, "evidence_provided": True},
        confidence=0.95,
        needs_human=True,
    )
    res, adapter = _run(payload, confirm=None)
    # 事实干净、金额在自动档，但模型自己要求人工 → 不许自动发、更不许凭"人工确认"顺带打款
    assert res.out.send_gate is SendGate.human
    assert ReasonCode.MODEL_NEEDS_HUMAN in res.out.reason_codes
    assert res.out.reason_codes[0] is ReasonCode.MODEL_NEEDS_HUMAN
    assert adapter.refund_calls == []
    assert res.case is not None and res.case.status.value == "REVIEWING"
