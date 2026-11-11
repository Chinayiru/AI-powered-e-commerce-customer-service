"""Read-only Agent: intent + slots + tool facts + retrieval + draft.

No policy decision is made here. `policyCheck` is deliberately absent from the
response and is computed by the Java rules engine.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import Settings
from .contracts import (
    ActionType,
    AskRequest,
    AskResponse,
    Citation,
    Intent,
    ModelInfo,
    ReplyType,
    Slots,
    SuggestedAction,
    TransferReason,
)
from .intent import classify, extract_slots
from .knowledge import Chunk, retrieve
from .tools import ToolClient, ToolUnavailable

_STATUS_LABELS = {
    "PAID": "待发货",
    "SHIPPED": "已发货",
    "DELIVERED": "已签收",
    "CLOSED": "已关闭",
}

_LOGISTICS_LABELS = {
    "NOT_SHIPPED": "未发货",
    "IN_TRANSIT": "运输中",
    "DELIVERED": "已签收",
    "EXCEPTION": "物流异常",
}

_BANNED = ("赔付", "赔偿", "保证", "一定", "百分百", "已退款", "已处理", "已改地址")


class AgentService:
    def __init__(self, settings: Settings, tools: ToolClient) -> None:
        self.settings = settings
        self.tools = tools

    def answer(self, request: AskRequest) -> AskResponse:
        result = classify(request.message)
        context_order = request.context.orderNo if request.context else None
        history = request.context.history if request.context else []
        slots = extract_slots(request.message, context_order, [item.text for item in history])

        if slots.ambiguous:
            return self._handoff(
                Intent.HANDOFF,
                0.95,
                TransferReason.AMBIGUOUS_ORDER,
                "检测到多个订单号，请只提供一个订单号，或由人工协助确认。",
                Slots(orderNo=None, missing=[]),
            )

        order_no = slots.order_no
        missing = [] if order_no else ["orderNo"]

        if result.intent == Intent.HANDOFF:
            return self._handoff(
                result.intent,
                result.confidence,
                result.transfer_reason or TransferReason.OUT_OF_SCOPE,
                self._handoff_reply(result.transfer_reason),
                Slots(orderNo=order_no, missing=[]),
            )

        if result.intent == Intent.POLICY:
            chunks = retrieve(request.message, self.settings.policy_version)
            if not chunks:
                return self._handoff(
                    Intent.HANDOFF,
                    0.86,
                    TransferReason.NO_EVIDENCE,
                    "暂未检索到可靠的规则依据，已转人工核实。",
                    Slots(orderNo=order_no, missing=missing),
                )
            return AskResponse(
                intent=Intent.POLICY,
                slots=Slots(orderNo=order_no, missing=missing),
                confidence=result.confidence,
                replyType=ReplyType.INFORMATIONAL,
                needHumanReview=False,
                replyDraft=self._policy_reply(chunks),
                citations=self._citations(chunks[:2]),
                model=self._model(),
            )

        needs_order = result.intent in (
            Intent.REFUND_REQUEST,
            Intent.REFUND_ELIGIBILITY,
            Intent.LOGISTICS,
        )
        if needs_order and not order_no:
            return self._response_without_order(request, result.intent, result.confidence)

        order: dict[str, Any] | None = None
        if needs_order and order_no:
            try:
                order = self.tools.query_order(request.userId, order_no)
            except ToolUnavailable as exc:
                return self._handoff(
                    Intent.HANDOFF,
                    0.0,
                    TransferReason.TOOL_FAILED,
                    "暂时无法查询订单信息，已转人工处理。",
                    Slots(orderNo=order_no, missing=[]),
                    degraded=True,
                )
            if order is None:
                return self._order_not_found(order_no, result.intent)

        shipment: dict[str, Any] | None = None
        if result.intent == Intent.LOGISTICS and order is not None:
            try:
                shipment = self.tools.get_logistics(request.userId, order_no)
            except ToolUnavailable:
                return self._handoff(
                    Intent.HANDOFF,
                    0.0,
                    TransferReason.TOOL_FAILED,
                    "暂时无法查询物流信息，已转人工处理。",
                    Slots(orderNo=order_no, missing=[]),
                    degraded=True,
                )
            if shipment is None:
                return self._order_not_found(order_no, result.intent)

        chunks = retrieve(request.message, self.settings.policy_version)
        if needs_order and not chunks:
            return self._handoff(
                Intent.HANDOFF,
                0.80,
                TransferReason.NO_EVIDENCE,
                "暂未检索到可靠的规则，已转人工核实。",
                Slots(orderNo=order_no, missing=[]),
            )

        if result.intent == Intent.LOGISTICS and order is not None:
            return AskResponse(
                intent=Intent.LOGISTICS,
                slots=Slots(orderNo=order_no, missing=[]),
                confidence=result.confidence,
                replyType=ReplyType.INFORMATIONAL,
                needHumanReview=result.confidence < self.settings.confidence_threshold,
                replyDraft=self._logistics_reply(order, shipment),
                citations=self._citations(chunks[:1]),
                model=self._model(),
            )

        if result.intent == Intent.REFUND_ELIGIBILITY and order is not None:
            return AskResponse(
                intent=Intent.REFUND_ELIGIBILITY,
                slots=Slots(orderNo=order_no, missing=[]),
                confidence=result.confidence,
                replyType=ReplyType.INFORMATIONAL,
                needHumanReview=result.confidence < self.settings.confidence_threshold,
                replyDraft=self._eligibility_reply(order, chunks),
                citations=self._citations(chunks[:2]),
                model=self._model(),
            )

        if result.intent == Intent.REFUND_REQUEST and order is not None:
            return self._refund_request(request, result.confidence, order, chunks)

        # OTHER / fuzzy: valid order still gets a safe draft for a human to edit.
        citations = self._citations(chunks[:1])
        return AskResponse(
            intent=Intent.OTHER,
            slots=Slots(orderNo=order_no, missing=missing),
            confidence=result.confidence,
            replyType=ReplyType.INFORMATIONAL,
            needHumanReview=result.confidence < self.settings.confidence_threshold,
            replyDraft=self._other_reply(order_no),
            citations=citations,
            model=self._model(),
        )

    def _refund_request(
        self,
        request: AskRequest,
        confidence: float,
        order: dict[str, Any],
        chunks: list[Chunk],
    ) -> AskResponse:
        amount = int(order.get("refundableAmountCents") or 0)
        need_review = (
            confidence < self.settings.confidence_threshold
            or amount > self.settings.auto_suggest_limit_cents
            or amount <= 0
        )
        reply = self._refund_reply(order, amount)
        action = (
            SuggestedAction(
                action=ActionType.REFUND,
                amountCents=amount,
                needHumanConfirm=True,
            )
            if amount > 0
            else None
        )
        return AskResponse(
            intent=Intent.REFUND_REQUEST,
            slots=Slots(orderNo=order.get("orderNo"), missing=[]),
            confidence=confidence,
            replyType=ReplyType.DECISIONAL,
            needHumanReview=need_review,
            suggestedAction=action,
            replyDraft=reply,
            citations=self._citations(chunks[:2]),
            model=self._model(),
        )

    def _response_without_order(
        self, request: AskRequest, intent: Intent, confidence: float
    ) -> AskResponse:
        if intent == Intent.REFUND_REQUEST:
            return AskResponse(
                intent=intent,
                slots=Slots(orderNo=None, missing=["orderNo"]),
                confidence=confidence,
                replyType=ReplyType.DECISIONAL,
                needHumanReview=confidence < self.settings.confidence_threshold,
                replyDraft="请提供订单号，我帮您核实订单状态和可退金额。",
                citations=[],
                model=self._model(),
            )
        return AskResponse(
            intent=intent,
            slots=Slots(orderNo=None, missing=["orderNo"]),
            confidence=confidence,
            replyType=ReplyType.INFORMATIONAL,
            needHumanReview=confidence < self.settings.confidence_threshold,
            replyDraft="请提供订单号，我帮您核实订单状态和物流信息。",
            citations=[],
            model=self._model(),
        )

    def _order_not_found(self, order_no: str, intent: Intent) -> AskResponse:
        return AskResponse(
            intent=intent,
            slots=Slots(orderNo=order_no, missing=[]),
            confidence=0.90,
            replyType=ReplyType.INFORMATIONAL,
            needHumanReview=False,
            replyDraft=f"没查到订单 {order_no}，请核对订单号后重新提供。",
            citations=[],
            model=self._model(),
        )

    def _handoff(
        self,
        intent: Intent,
        confidence: float,
        reason: TransferReason,
        reply: str,
        slots: Slots,
        degraded: bool = False,
    ) -> AskResponse:
        return AskResponse(
            intent=intent,
            slots=slots,
            confidence=confidence,
            replyType=ReplyType.INFORMATIONAL,
            needHumanReview=True,
            transferReason=reason,
            replyDraft=self._clip(reply),
            citations=[],
            degraded=degraded,
            model=self._model(),
        )

    def _handoff_reply(self, reason: TransferReason | None) -> str:
        if reason == TransferReason.USER_REQUESTED:
            return "已转接人工客服，请稍候。"
        if reason == TransferReason.AMBIGUOUS_ORDER:
            return "检测到多个订单号，请只提供一个订单号，或由人工协助确认。"
        if reason == TransferReason.TOOL_FAILED:
            return "暂时无法查询信息，已转人工处理。"
        if reason == TransferReason.NO_EVIDENCE:
            return "暂未检索到可靠的规则依据，已转人工核实。"
        return "已记录您的诉求，将转交人工专员处理。"

    def _eligibility_reply(self, order: dict[str, Any], chunks: list[Chunk]) -> str:
        status = _STATUS_LABELS.get(str(order.get("status")), "状态未知")
        amount = int(order.get("refundableAmountCents") or 0)
        total = int(order.get("amountCents") or 0)
        parts = [
            f"查到了：订单 {order.get('orderNo')}，{status}，实付 {_money(total)}，可退 {_money(amount)}。"
        ]
        if status == "待发货":
            parts.append("未发货可申请仅退款；七天无理由自签收次日起算。")
        else:
            parts.append("已发货或已签收可申请退货退款，七天无理由自签收次日起算。")
        delivered = order.get("deliveredAt")
        if delivered:
            parts.append(f"签收日期 {str(delivered)[:10]}。")
        if chunks:
            parts.append(_cite(chunks[0]))
        return self._clip("".join(parts))

    def _refund_reply(self, order: dict[str, Any], amount: int) -> str:
        status = _STATUS_LABELS.get(str(order.get("status")), "状态未知")
        total = int(order.get("amountCents") or 0)
        head = (
            f"订单 {order.get('orderNo')}，{status}，实付 {_money(total)}，"
            f"可退 {_money(amount)}。"
        )
        if amount <= 0:
            return self._clip(head + "当前暂无可退金额，需人工进一步核实。")
        tail = "已记录您的退款诉求，需坐席确认后生效（演示环境，未真实退款）。"
        delivered = order.get("deliveredAt")
        if delivered:
            days = _days_since(str(delivered))
            if days is not None and days > self.settings.return_window_days:
                tail = "已签收超过七天，是否适用无理由退货需人工核实；确认前不产生退款。"
        return self._clip(head + tail)

    def _logistics_reply(self, order: dict[str, Any], shipment: dict[str, Any] | None) -> str:
        order_no = order.get("orderNo")
        if not shipment:
            return self._clip(f"订单 {order_no} 还没有物流信息，请稍后重试。")
        status = _LOGISTICS_LABELS.get(str(shipment.get("status")), "状态未知")
        packages = shipment.get("shipments") or []
        if not packages:
            return self._clip(f"订单 {order_no} 还没有物流单号，当前待发货。")
        parts = [f"订单 {order_no} 物流{status}："]
        descriptions = []
        latest = ""
        for pkg in packages[:3]:
            tracking = pkg.get("trackingNo") or "暂无运单号"
            pkg_status = _LOGISTICS_LABELS.get(str(pkg.get("status")), str(pkg.get("status")))
            descriptions.append(f"{tracking}（{pkg_status}）")
            events = pkg.get("events") or []
            if events and not latest:
                latest = str(events[-1].get("text") or "")
        parts.append("、".join(descriptions) + "。")
        if latest:
            parts.append(f"最新：{latest}。")
        if len(packages) > 1:
            parts.append("该订单有多个包裹，请以各运单状态为准。")
        return self._clip("".join(parts))

    def _policy_reply(self, chunks: list[Chunk]) -> str:
        selected = chunks[:2]
        body = "".join(chunk.text for chunk in selected)
        return self._clip(body + "".join(_cite(chunk) for chunk in selected))

    def _other_reply(self, order_no: str | None) -> str:
        if order_no:
            return self._clip(
                f"已收到您关于订单 {order_no} 的问题。请补充具体诉求，由坐席进一步核实。"
            )
        return self._clip("已收到您的问题。请补充订单号和具体诉求，由坐席进一步核实。")

    def _citations(self, chunks: list[Chunk]) -> list[Citation]:
        return [
            Citation(
                docId=chunk.doc_id,
                title=chunk.title,
                clauseId=chunk.clause_id,
                policyVersion=self.settings.policy_version,
            )
            for chunk in chunks
        ]

    def _model(self) -> ModelInfo:
        return ModelInfo(provider=self.settings.provider, promptVersion=self.settings.prompt_version)

    def _clip(self, text: str) -> str:
        cleaned = text
        for word in _BANNED:
            cleaned = cleaned.replace(word, "相关")
        cleaned = " ".join(cleaned.split())
        if len(cleaned) <= 200:
            return cleaned
        return cleaned[:199] + "…"


def _money(cents: int) -> str:
    return f"¥{cents / 100:.2f}"


def _cite(chunk: Chunk) -> str:
    return f"[{chunk.doc_id}#{chunk.clause_id}]"


def _days_since(iso: str) -> int | None:
    try:
        delivered = date.fromisoformat(iso[:10])
        return (date.today() - delivered).days
    except ValueError:
        return None
