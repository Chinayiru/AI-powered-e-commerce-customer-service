"""工单域服务：只认状态机，不认平台。

所有迁移都走 `transition()` 一处，事件 key 幂等 —— 平台重推同一事件不会长出第二条。
"""
from __future__ import annotations

from datetime import datetime

from app.adapters.base import PlatformAdapter
from app.contracts.models import (
    AftersalesCase,
    AftersalesType,
    CaseEvent,
    CaseStatus,
    DomainError,
    ErrorCode,
)
from app.domain.transitions import assert_transition


class CaseService:
    def __init__(self, adapter: PlatformAdapter) -> None:
        self.adapter = adapter

    # -- 创建 ---------------------------------------------------------------
    def open(
        self,
        *,
        case_id: str,
        ticket_id: str,
        order_ref: str,
        case_type: AftersalesType,
        requested_cents: int,
        paid_cents: int,
        now: datetime,
        reason_code: str = "",
    ) -> AftersalesCase:
        if requested_cents > paid_cents:
            raise DomainError(
                ErrorCode.STATE_ILLEGAL,
                f"申请金额 {requested_cents} 分超过实付 {paid_cents} 分",
                hint="部分退款金额必须 ≤ 实付金额；超出即拒绝，不做截断",
            )
        return AftersalesCase(
            case_id=case_id,
            ticket_id=ticket_id,
            order_ref=order_ref,
            type=case_type,
            reason_code=reason_code,
            requested_cents=requested_cents,
            amount_cents=requested_cents,
        )

    # -- 唯一迁移入口 -------------------------------------------------------
    def transition(
        self,
        case: AftersalesCase,
        dst: CaseStatus,
        *,
        actor: str,
        now: datetime,
        key: str,
        note: str = "",
    ) -> None:
        src = case.status
        assert_transition(case.type, src, dst, actor)
        event = CaseEvent(
            event_id=f"{case.case_id}:{key}",
            from_status=src,
            to_status=dst,
            actor=actor,
            at=now,
            note=note,
        )
        case.append_event(event, key)
        case.status = dst

    def submit(self, case: AftersalesCase, *, now: datetime, actor: str = "system:bot") -> None:
        self.transition(case, CaseStatus.REVIEWING, actor=actor, now=now, key="submit")

    def approve(self, case: AftersalesCase, *, approver: str, now: datetime, key: str = "approve") -> None:
        dst = CaseStatus.AWAITING_BUYER_SHIP if case.type is AftersalesType.return_refund else CaseStatus.APPROVED
        self.transition(case, dst, actor=f"human:{approver}", now=now, key=key)

    def reject(self, case: AftersalesCase, *, now: datetime, reason: str = "", actor: str = "system:policy") -> None:
        self.transition(case, CaseStatus.REJECTED, actor=actor, now=now, key="reject", note=reason)

    def close(self, case: AftersalesCase, *, now: datetime, actor: str = "system:bot") -> None:
        self.transition(case, CaseStatus.CLOSED, actor=actor, now=now, key="close")

    # -- 执行退款：批准与打款分离 ------------------------------------------
    def execute(self, case: AftersalesCase, *, approver: str, now: datetime) -> str:
        self.transition(case, CaseStatus.REFUNDING, actor=f"human:{approver}", now=now, key="refund_requested")
        try:
            refund_id = self.adapter.execute_refund(case.case_id, case.amount_cents, f"human:{approver}")
        except DomainError:
            # 打款失败不吞：保留 REFUNDING，等待人工介入（不伪造成功）
            raise
        case.platform_refund_id = refund_id
        # 平台结果也是不可逆事实，记在授权人账下，不新增"系统"特权路径
        self.transition(case, CaseStatus.REFUNDED, actor=f"human:{approver}", now=now, key="refund_succeeded", note=refund_id)
        self.close(case, now=now)
        return refund_id
