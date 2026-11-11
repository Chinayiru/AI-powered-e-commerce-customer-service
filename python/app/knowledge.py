"""Tiny policy corpus + deterministic lexical retrieval.

The production plan is a real vector index; for the offline demo we keep one
rule per chunk, explicit clause ids, and deterministic retrieval so every
draft citation can be audited. The corpus is intentionally separate from the
M-Q evaluation set (see AGENT_RAG_SPEC §9.1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    clause_id: str
    title: str
    text: str
    triggers: tuple[str, ...]


CHUNKS: tuple[Chunk, ...] = (
    Chunk(
        doc_id="refund-policy",
        clause_id="3.1",
        title="七天无理由与退款适用范围",
        text=(
            "自签收次日起七天内，商品完好可申请无理由退货；已发货或已签收可申请退货退款。"
            "仅退款只适用于未发货订单。"
        ),
        triggers=(
            "退",
            "退款",
            "退货",
            "退了",
            "退了吧",
            "退掉",
            "退钱",
            "能退",
            "七天",
            "无理由",
            "签收",
            "发货",
        ),
    ),
    Chunk(
        doc_id="refund-policy",
        clause_id="3.2",
        title="退款条件与例外",
        text=(
            "定制商品、鲜活易腐商品、拆封的音像制品等不适用无理由退货；"
            "退款金额以订单可退金额为准，不由客服自行计算。"
        ),
        triggers=("拆封", "例外", "定制", "鲜活", "不支持", "已拆", "金额"),
    ),
    Chunk(
        doc_id="return-shipping",
        clause_id="2.1",
        title="退货运费承担",
        text="因商品质量问题退货的，运费由商家承担；无理由退货的，运费由消费者承担，另有约定除外。",
        triggers=("运费", "谁出", "谁承担", "承担", "包邮", "质量问题"),
    ),
    Chunk(
        doc_id="logistics-sla",
        clause_id="1.1",
        title="发货与物流时效",
        text=(
            "现货订单通常在 48 小时内发货；运输时效以承运商实际配送为准，"
            "平台不承诺具体送达时间。"
        ),
        triggers=("物流", "快递", "发货", "签收", "包裹", "运单", "配送", "派送", "到哪", "没到"),
    ),
    Chunk(
        doc_id="after-sale-process",
        clause_id="4.1",
        title="售后申请流程",
        text=(
            "提交售后申请后由坐席确认；确认前不会产生真实退款。"
            "申请时需提供订单号与问题描述。"
        ),
        triggers=("流程", "材料", "怎么退", "步骤", "申请", "需要什么"),
    ),
    Chunk(
        doc_id="refund-policy",
        clause_id="3.3",
        title="退款到账时效",
        text=(
            "审核通过后按原支付渠道退回；具体到账时间以支付机构为准，"
            "平台不承诺固定到账时间。"
        ),
        triggers=("到账", "多久", "几天", "时效", "退款时间"),
    ),
)


def retrieve(query: str, policy_version: str, limit: int = 5, threshold: float = 0.35) -> list[Chunk]:
    text = query or ""
    scored: list[tuple[float, int, Chunk]] = []
    for index, chunk in enumerate(CHUNKS):
        # Longer triggers are more specific: "运费"+"谁出" must beat the
        # generic "退"/"退货" in the refund-policy chunk for a shipping-fee
        # question.
        weight = sum(len(trigger) for trigger in chunk.triggers if trigger in text)
        score = min(1.0, weight / 4.0)
        if score >= threshold:
            scored.append((score, index, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]
