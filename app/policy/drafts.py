"""草稿口径：模型可以写得随意，出口必须守规矩。

两条硬规矩（对应 AC08 / AC18 的出口侧）：
1. 结论是 reject 时，草稿里不允许出现"退款将在/已退款"这类承诺。
2. 结论是 undecided（事实不可信）时，草稿必须落到人手里，而不是给用户一个假装确定的答复。
"""
from __future__ import annotations

import re

from app.contracts.models import PolicyDecision, ReasonCode, SendGate, Verdict

PROMISE_RE = re.compile(r"(退款将在|退款已|已退款|已原路退回|将原路退回|将于\S{0,6}到账)")
DISSUADE_RE = re.compile(r"(不用转人工|没必要转人工|不需要转人工|我可以帮你处理|我可以直接帮你)")
SENTENCE_RE = re.compile(r"[^。！？]+[。！？]?")

REASON_TEXT: dict[ReasonCode, str] = {
    ReasonCode.PLATFORM_ANOMALY: "订单状态暂无法确认",
    ReasonCode.ORDER_NOT_ELIGIBLE: "订单当前状态不支持该售后",
    ReasonCode.THREAT_OR_LEGAL: "该诉求需人工核实",
    ReasonCode.CATEGORY_EXCLUDED: "该商品类目不在自动理范围",
    ReasonCode.OUT_OF_WINDOW: "已超出售后申请期限",
    ReasonCode.AMOUNT_OVER_LIMIT: "申请金额超出自动处理范围",
    ReasonCode.POLICY_GRAY_BAND: "需人工确认",
    ReasonCode.MISSING_EVIDENCE: "缺少必要凭证",
}

REJECT_TEMPLATE = "您好，订单 {ref} 当前不符合退款条件（{why}）。如您有补充凭证，可回复本消息进一步处理。"
UNDECIDED_SUFFIX = "已转人工核实，请稍候。"


def shape_draft(
    text: str,
    decision: PolicyDecision,
    *,
    order_ref: str,
    user_requested_human: bool = False,
) -> tuple[str, list[str]]:
    flags: list[str] = []
    text = (text or "").strip()

    if user_requested_human:
        # AC15：用户明确要人工时，模型不得劝阻；劝阻句整句删掉
        text = "".join(s for s in SENTENCE_RE.findall(text) if not DISSUADE_RE.search(s)).strip()
        if "人工" not in text:
            text = (text or "您好，已收到您的反馈。") + "已为您转人工，请稍候。"
        flags.append("HUMAN_REQUESTED")

    if decision.verdict is Verdict.reject and PROMISE_RE.search(text):
        flags.append("PROMISE_IN_REJECT")
        why = REASON_TEXT.get(decision.primary_reason, "当前条件不满足")
        text = REJECT_TEMPLATE.format(ref=order_ref, why=why)

    if decision.verdict is Verdict.undecided:
        if "人工" not in text:
            text = (text.rstrip("。") + "。" if text else "") + UNDECIDED_SUFFIX
        flags.append("HUMAN_HANDOFF")

    if decision.send_gate is SendGate.human and decision.verdict is not Verdict.reject:
        flags.append("REQUIRES_CONFIRM")

    return text, flags
