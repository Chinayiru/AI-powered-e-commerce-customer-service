"""提示词模板 + 版本号。

prompt_version 由模板正文哈希得出：改了提示词却忘改版本号，在结构上不可能发生（CONTRACT §8.1）。
"""
from __future__ import annotations

import hashlib

from app.contracts.models import Order

TEMPLATE = """你是电商售后客服助手。只输出一个 JSON 对象，不要解释。

工单：{ticket_text}
订单：{order_summary}
可引用知识：{kb_hits}

输出字段：intent(refund|address_change|shipping_urge|other), aftersales_type(refund_only|return_refund|null),
slots(order_ref, reason, evidence_provided, amount_cents, has_threat, user_requested_human),
draft(中文，≤120字，不承诺未确认的动作), citations[], confidence(0-1), needs_human(bool)。

规则：
1. 金额一律整数分。
2. 不确定就降低 confidence，不要编造订单事实。
3. 草稿里出现政策原文时，必须来自可引用知识。
"""


def prompt_version() -> str:
    return hashlib.sha256(TEMPLATE.encode("utf-8")).hexdigest()[:8]


def build_prompt(ticket_text: str, order: Order, kb_hits: list[str] | None = None) -> str:
    summary = (
        f"order_ref={order.order_ref} status={order.status.value} "
        f"paid_cents={order.paid_cents} items={len(order.items)} shipments={len(order.shipments)}"
    )
    return TEMPLATE.format(
        ticket_text=ticket_text,
        order_summary=summary,
        kb_hits="; ".join(kb_hits or []) or "（无）",
    )
