"""Deterministic intent/slot rules for the scripted demo agent.

This is intentionally transparent: no hidden model, no invented facts. The
same rules back the regression tests, so a rule change is visible in Git.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import Intent, TransferReason

RULES_VERSION = "intent-v1.1.0"


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
    r"(帮我|给我|我要|我想|麻烦|直接|那就|就|请|申请|要求|安排|办理)"
    r"(?:帮我|给我|提交|办理|申请|处理|取消并|直接|全额|部分|一下|把|这单|订单|商品|进行){0,3}"
    r"(退|退款|退钱|退货退款|退掉|退了)"
    r"|退了吧|退款吧|退掉|退了|不想要了|退钱|我要退|想退"
    r"|退不了.{0,8}转人工"
)

_POLICY = re.compile(
    r"运费|谁出|谁承担|规则|政策|时效|流程|材料|需要什么|怎么退|如何退"
    r"|退款多久|几天到账|多久到账|到账|从哪天|无理由|退货地址|退款到哪"
    r"|原路|原支付|银行卡|余额|退回.{0,4}账户|退到.{0,4}账户|退款.{0,5}渠道"
    r"|退货.{0,6}寄到|退货.{0,6}地址"
)

_LOGISTICS = re.compile(
    r"物流|快递|发货|没收到|催一下|催|签收|包裹|运单|配送|派送"
    r"|到哪|到哪了|一直没到|怎么还没到|多久能到|什么时候到"
    r"|什么时候.{0,3}发|何时.{0,3}发|发出来|出库|送到"
)

_ELIGIBILITY = re.compile(
    r"(?:能不能|可不可以|是否|能否|可否|还能|能|可以|可)"
    r"(?:再|还|继续|给我|为我|申请|办理|直接|全额|部分|可以|能|以){0,3}(?:退款|退货|退钱|退)"
    r"|(?:退款|退货|退了|退钱|退).{0,8}(?:会不会|要不要|资格|限制|需要.{0,4}吗)"
    r"|(?:退款|退货|退钱|退)[吗不](?:[？?]|$|[，。])"
    r"|(?:如果|假如).{0,4}(?:退款|退货|退).{0,8}(?:扣|费用|影响)"
    r"|拆封|拆了|用了|没拆|不合适"
)

_CONDITIONAL = re.compile(r"能退的话|退得了的话|可以退的话|能退就|退不了.{0,8}转人工")

# Remove denied/reported/completed refund phrases before matching actions.
# Keep the rest of the sentence: "不用退钱，帮我查物流" is still logistics.
_NEGATED_REFUND = re.compile(
    r"(?:不想|不需要|不打算|不准备|不要|不用|无需|别|不是|并非|不能|不给|不让|无法)"
    r"[^，。！？,!?;；]{0,10}?(?:退款申请|退货退款|退款|退钱|退货|退掉|退了|退)"
    r"|(?:取消|撤销)(?:这次|本次|我的|这笔)?(?:退款申请|退款|退货)"
)
_COMPLETED_REFUND = re.compile(
    r"(?:已经|已|之前|刚才)(?:成功|完成|给我|帮我|全额|部分)?(?:退了钱|退款成功|退款|退钱|退了)"
)
_PROCESS_QUESTION = re.compile(r"怎么办|怎么退|如何退")
_EXPLICIT_INSTRUCTION = re.compile(r"帮我|给我|请.{0,4}(?:退|办理|提交)|麻烦|申请|要求|直接|退了吧|退款吧")

# A bare desire followed by a question stays informational. Explicit
# instructions such as "帮我提交退款，可以吗" remain refund requests.
_REFUND_QUESTION = re.compile(r"能否|可以吗|能吗|行吗|吗[?？]?\s*$")

_ORDER = re.compile(r"(?i)(?<![A-Z0-9])O\d{4,8}(?![A-Z0-9])")


def classify(message: str) -> IntentResult:
    text = (message or "").strip()

    if any(word in text for word in _SAFETY):
        return IntentResult(
            Intent.HANDOFF,
            0.98,
            transfer_reason=TransferReason.OUT_OF_SCOPE,
            out_of_scope=True,
        )

    conditional = bool(_CONDITIONAL.search(text))
    # "退不了就转人工" describes a conditional refund request. A direct
    # human request otherwise takes precedence over a refund keyword.
    if any(word in text for word in _HUMAN) and not conditional:
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

    if conditional:
        return IntentResult(Intent.REFUND_REQUEST, 0.92, conditional=True)

    active_text = _COMPLETED_REFUND.sub("", _NEGATED_REFUND.sub("", text))
    refund_request = bool(_REFUND_ACTION.search(active_text))
    explicit_instruction = bool(_EXPLICIT_INSTRUCTION.search(active_text))

    # Questions about an order's eligibility beat incidental shipment/fee
    # words. "可以吗" following an actual instruction is only politeness.
    if (_ELIGIBILITY.search(active_text)
            or refund_request and _PROCESS_QUESTION.search(active_text)
            or refund_request and _REFUND_QUESTION.search(active_text) and not explicit_instruction):
        return IntentResult(Intent.REFUND_ELIGIBILITY, 0.88)

    if refund_request:
        return IntentResult(Intent.REFUND_REQUEST, 0.92)

    if _POLICY.search(active_text):
        return IntentResult(Intent.POLICY, 0.88)

    if _LOGISTICS.search(active_text):
        return IntentResult(Intent.LOGISTICS, 0.90)

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
