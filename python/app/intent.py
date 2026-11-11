"""Deterministic intent/slot rules for the scripted demo agent.

This is intentionally transparent: no hidden model, no invented facts. The
same rules back the regression tests, so a rule change is visible in Git.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import Intent, TransferReason


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    confidence: float
    transfer_reason: TransferReason | None = None
    conditional: bool = False
    out_of_scope: bool = False


_SAFETY = (
    "投诉",
    "举报",
    "12315",
    "消协",
    "律师",
    "起诉",
    "法院",
    "监管",
    "曝光",
    "人身安全",
    "威胁",
    "打死",
    "弄死",
    "跳楼",
    "自杀",
)

_HUMAN = (
    "转人工",
    "人工客服",
    "找人工",
    "人工处理",
    "真人",
    "找个人",
    "找人",
    "客服电话",
)

_OUT_OF_SCOPE = (
    "换货",
    "价保",
    "价格保护",
    "改地址",
    "修改地址",
    "开发票",
    "发票",
    "赔",
    "赔偿",
)

_REFUND_ACTION = re.compile(
    r"(帮我|给我|我要|我想|麻烦|直接|那就|就|请|申请|要求|安排|办理).{0,6}"
    r"(退|退款|退钱|退货退款|退掉|退了)"
    r"|退了吧|退款吧|退掉|退了|不想要了|退钱|我要退|想退"
    r"|退不了.{0,8}转人工"
)

_POLICY = re.compile(
    r"运费|谁出|谁承担|规则|政策|时效|流程|材料|需要什么|怎么退|如何退"
    r"|退款多久|几天到账|多久到账|到账|从哪天|无理由|退货地址|退款到哪"
)

_LOGISTICS = re.compile(
    r"物流|快递|发货|没收到|催一下|催|签收|包裹|运单|配送|派送"
    r"|到哪|到哪了|一直没到|怎么还没到|多久能到|什么时候到"
)

_ELIGIBILITY = re.compile(
    r"能退|可以退|可退|还能退|退吗|能不能退|退货|退换|拆封|拆了|用了"
    r"|超过.{0,3}天|没拆|不合适"
)

_CONDITIONAL = re.compile(r"能退的话|退得了的话|可以退的话|能退就|退不了.{0,8}转人工")

# "我想退款，怎么办？" is a question about eligibility, not an instruction to
# execute a refund. Keep it informational; an explicit "帮我退了吧" stays a
# REFUND_REQUEST.
_REFUND_QUESTION = re.compile(
    r"怎么办|怎么退|如何退|能否|可以吗|能吗|行吗|吗[?？]?\s*$"
)

_ORDER = re.compile(r"(?i)(?<![A-Z0-9])O\d{4,8}(?![A-Z0-9])")


def classify(message: str) -> IntentResult:
    text = (message or "").strip()
    lower = text.lower()

    if any(word in text for word in _SAFETY):
        return IntentResult(
            Intent.HANDOFF,
            0.98,
            transfer_reason=TransferReason.OUT_OF_SCOPE,
            out_of_scope=True,
        )

    refund_request = bool(_REFUND_ACTION.search(text))
    conditional = bool(_CONDITIONAL.search(text))

    if refund_request and _REFUND_QUESTION.search(text):
        return IntentResult(Intent.REFUND_ELIGIBILITY, 0.88, conditional=conditional)

    if refund_request:
        return IntentResult(Intent.REFUND_REQUEST, 0.92, conditional=conditional)

    if any(word in text for word in _HUMAN):
        return IntentResult(
            Intent.HANDOFF,
            0.97,
            transfer_reason=TransferReason.USER_REQUESTED,
        )

    if any(word in text for word in _OUT_OF_SCOPE):
        return IntentResult(
            Intent.HANDOFF,
            0.90,
            transfer_reason=TransferReason.OUT_OF_SCOPE,
            out_of_scope=True,
        )

    if _POLICY.search(text):
        return IntentResult(Intent.POLICY, 0.88)

    if _LOGISTICS.search(text):
        return IntentResult(Intent.LOGISTICS, 0.90)

    if _ELIGIBILITY.search(text):
        return IntentResult(Intent.REFUND_ELIGIBILITY, 0.90)

    if "订单" in text or "单号" in text:
        return IntentResult(Intent.OTHER, 0.55)

    # Fuzzy/unrelated: keep a draft path for a valid order, but flag review.
    return IntentResult(Intent.OTHER, 0.42)


@dataclass
class SlotResult:
    order_no: str | None = None
    missing: list[str] = field(default_factory=list)
    ambiguous: bool = False


def extract_slots(message: str, context_order_no: str | None, history_texts: list[str]) -> SlotResult:
    current = _unique(_ORDER.findall(message or ""))
    if len(current) > 1:
        return SlotResult(ambiguous=True)

    if current:
        return SlotResult(order_no=current[0].upper())

    if context_order_no:
        return SlotResult(order_no=context_order_no.upper())

    from_history = _unique(
        match.upper() for text in history_texts for match in _ORDER.findall(text or "")
    )
    if len(from_history) > 1:
        return SlotResult(ambiguous=True)
    if from_history:
        return SlotResult(order_no=from_history[0])
    return SlotResult(missing=["orderNo"])


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.upper()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
