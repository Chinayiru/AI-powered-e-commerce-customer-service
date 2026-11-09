"""状态机：唯一允许的迁移集合。

退货退款的 AWAITING_BUYER_SHIP 是显式终止态——出边集合为空，
任何"顺手补一个质检"的改动都会让 AC10 变红。
"""
from __future__ import annotations

from app.contracts.models import AftersalesType, CaseStatus, DomainError, ErrorCode

S = CaseStatus

_REFUND_ONLY: dict[CaseStatus, frozenset[CaseStatus]] = {
    S.INITIATED: frozenset({S.REVIEWING, S.CANCELLED}),
    S.REVIEWING: frozenset({S.APPROVED, S.REJECTED}),
    S.APPROVED: frozenset({S.REFUNDING}),
    S.REFUNDING: frozenset({S.REFUNDED}),
    S.REFUNDED: frozenset({S.CLOSED}),
    S.REJECTED: frozenset({S.CLOSED}),
    S.CLOSED: frozenset(),
    S.CANCELLED: frozenset(),
    S.AWAITING_BUYER_SHIP: frozenset(),   # 仅退款不应到达
}

_RETURN_REFUND: dict[CaseStatus, frozenset[CaseStatus]] = {
    S.INITIATED: frozenset({S.REVIEWING, S.CANCELLED}),
    S.REVIEWING: frozenset({S.AWAITING_BUYER_SHIP, S.REJECTED}),
    S.AWAITING_BUYER_SHIP: frozenset(),   # 截断：回寄/质检/入库不在本期（NG-2）
    S.REJECTED: frozenset({S.CLOSED}),
    S.CLOSED: frozenset(),
    S.CANCELLED: frozenset(),
}

TRANSITIONS: dict[AftersalesType, dict[CaseStatus, frozenset[CaseStatus]]] = {
    AftersalesType.refund_only: _REFUND_ONLY,
    AftersalesType.return_refund: _RETURN_REFUND,
}

# 不可逆迁移：只能由 human:<id> 触发
IRREVERSIBLE: frozenset[tuple[CaseStatus, CaseStatus]] = frozenset(
    {
        (S.REVIEWING, S.APPROVED),
        (S.REVIEWING, S.REJECTED),
        (S.REVIEWING, S.AWAITING_BUYER_SHIP),
        (S.APPROVED, S.REFUNDING),
        (S.REFUNDING, S.REFUNDED),
        (S.AWAITING_BUYER_SHIP, S.CLOSED),
    }
)

TERMINAL: frozenset[CaseStatus] = frozenset({S.CLOSED, S.CANCELLED, S.AWAITING_BUYER_SHIP})


def can_transition(case_type: AftersalesType, src: CaseStatus, dst: CaseStatus) -> bool:
    return dst in TRANSITIONS[case_type].get(src, frozenset())


def assert_transition(case_type: AftersalesType, src: CaseStatus, dst: CaseStatus, actor: str) -> None:
    if not can_transition(case_type, src, dst):
        raise DomainError(
            ErrorCode.STATE_ILLEGAL,
            f"{case_type.value} 不允许 {src.value} → {dst.value}",
            hint=f"合法出边={sorted(s.value for s in TRANSITIONS[case_type].get(src, ()))}",
        )
    if (src, dst) in IRREVERSIBLE and not actor.startswith("human:"):
        raise DomainError(
            ErrorCode.CONFIRM_REQUIRED,
            f"{src.value} → {dst.value} 为不可逆迁移，需要 human:<id>",
            hint=f"actor={actor}",
        )
