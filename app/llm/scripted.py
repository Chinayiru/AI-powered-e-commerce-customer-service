"""一期模型：台词化的 ScriptedProvider。

它证明的是**编排**，不是智能。每次调用都按 key（= order_ref）取一条预置剧本，
token 数按字符数粗估并标 estimated=True —— 真实 provider 才有 usage。
"""
from __future__ import annotations

import json
import time

from app.contracts.models import DomainError, ErrorCode
from app.llm.base import LLMResponse, Proposal
from app.llm.openai_compat import ProviderError

DRAFTS = {
    "TB1001": (
        "您好，已收到您对订单 TB1001 的仅退款申请（50.00 元）。订单尚未发货，"
        "我们将在 1 个工作日内原路退回，请留意账户到账通知。"
    ),
    "TB1002": (
        "您好，已收到您的售后申请。订单 TB1002 的两件商品分两个包裹发出，"
        "其中一件尚未显示签收，我们需要先与物流核实，请稍。"
    ),
    "TB1003": (
        "您好，订单 TB1003 签收已超过 7 天，按平台售后规则暂不支持退款。"
        "如商品存在质量问题，可补充凭证后为您转人工复核。"
    ),
    "TB1004": (
        "您好，已收到您反馈的少件问题。订单 TB1004 实付 89.00 元，您申请退 20.00 元，"
        "我们正在核实包裹内件，核实后会尽快答复。"
    ),
    "TB1005": "您好，已收到您的反馈。您的诉求已完整记录，会有专员尽快与您联系处理。",
    "TB1006": (
        "您好，虚拟商品订单 TB1006 不支持七天无理由退款。"
        "如存在未激活或质量问题，请补充凭证，我们为您转人工复核。"
    ),
    "DY2001": (
        "您好，已收到您对订单 DY2001 的退款申请（120.00 元）。"
        "该金额超出自动处理范围，已转人工复核，请耐心等待。"
    ),
    "DY2002": "您好，已收到您的反馈。订单状态暂无法确认，已转人工核实。",
    "DY2003": "您好，您的售后单 AS2003 正在审核中，请耐心等待。",
    "DY2004": (
        "您好，已收到您的退货退款申请（260.00 元）。审核通过后请在 7 天内寄回商品，"
        "寄回后我们会尽快处理。"
    ),
}

SCRIPTED: dict[str, dict] = {
    "TB1001": {"intent": "refund", "type": "refund_only", "amount": 5000, "evidence": True, "confidence": 0.93},
    "TB1002": {"intent": "refund", "type": "refund_only", "amount": 8900, "evidence": False, "confidence": 0.71},
    "TB1003": {"intent": "refund", "type": "refund_only", "amount": 6800, "evidence": False, "confidence": 0.82},
    "TB1004": {"intent": "refund", "type": "refund_only", "amount": 2000, "evidence": True, "confidence": 0.88},
    "TB1005": {"intent": "refund", "type": "refund_only", "amount": 6800, "evidence": False, "confidence": 0.61, "threat": True},
    "TB1006": {"intent": "refund", "type": "refund_only", "amount": 19900, "evidence": False, "confidence": 0.77},
    "DY2001": {"intent": "refund", "type": "refund_only", "amount": 12000, "evidence": True, "confidence": 0.9},
    "DY2002": {"intent": "refund", "type": "refund_only", "amount": 9900, "evidence": False, "confidence": 0.35},
    "DY2003": {"intent": "refund", "type": "refund_only", "amount": 3000, "evidence": True, "confidence": 0.8},
    "DY2004": {"intent": "refund", "type": "return_refund", "amount": 26000, "evidence": False, "confidence": 0.85},
}


class ScriptedProvider:
    name = "scripted"

    def __init__(self, *, model: str | None = None, delay_ms: int = 0, bad_first: dict[str, int] | None = None) -> None:
        self.model = model or "scripted-v1"
        self.delay_ms = delay_ms
        self._bad = dict(bad_first or {})
        self.calls = 0

    def propose(self, prompt: str, key: str, *, timeout_ms: int | None = None) -> LLMResponse:
        self.calls += 1
        delay = self.delay_ms
        if timeout_ms is not None and delay > timeout_ms:
            # 契约 AC22 的"真超时"：先卡到预算上限，再显式失败，而不是睡完再事后判超时
            time.sleep(timeout_ms / 1000)
            raise ProviderError(f"scripted 模拟超时：delay_ms={delay} > timeout_ms={timeout_ms}", timeout=True)
        if delay:
            time.sleep(delay / 1000)
        if self._bad.get(key, 0) > 0:
            self._bad[key] -= 1
            raw = '{"intent": "refund", "draft": '  # 故意截断，制造 E_INVALID_OUTPUT
        else:
            raw = json.dumps(self._script(key), ensure_ascii=False)
        return LLMResponse(
            raw=raw,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(raw) // 4),
            estimated=True,
        )

    def _script(self, key: str) -> dict:
        s = SCRIPTED.get(key)
        if s is None:
            # CONTRACT §8.3：未命中必须显式报 E_SCRIPT_MISS，不许静默降级成 intent=other，
            # 否则 fixture/order_ref 拼错会被当成"模型看不懂"而悄悄放过。
            raise DomainError(ErrorCode.SCRIPT_MISS, f"scripted 无剧本: {key!r}")
        slots = {
            "order_ref": key,
            "reason": "用户申请退款",
            "evidence_provided": s["evidence"],
            "amount_cents": s["amount"],
            "has_threat": bool(s.get("threat", False)),
            "user_requested_human": bool(s.get("human", False)),
        }
        return {
            "intent": s["intent"],
            "aftersales_type": s["type"],
            "slots": slots,
            "draft": DRAFTS[key],
            "citations": [],
            "confidence": s["confidence"],
            "needs_human": s["confidence"] < 0.6,
        }


def parse_proposal(raw: str) -> Proposal:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("proposal must be a JSON object")
    return Proposal.model_validate(data)
