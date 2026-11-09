"""契约层：对外形状 + 领域枚举 + 策略对象。

本文件是《边界确认书 v1》第 3 / 6 / 8 / 9 / 10 章的可执行版本。
改这里 = 改契约，必须同步 docs/CONTRACT.md 并走 ADR。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, Field, model_validator


# --------------------------------------------------------------------------
# 0. 错误码（封闭集，见 CONTRACT §10）
# --------------------------------------------------------------------------
class ErrorCode(str, Enum):
    INPUT_INVALID = "E_INPUT_INVALID"
    ORDER_NOT_FOUND = "E_ORDER_NOT_FOUND"
    PLATFORM_ANOMALY = "E_PLATFORM_ANOMALY"
    STATE_ILLEGAL = "E_STATE_ILLEGAL"
    CONFIRM_REQUIRED = "E_CONFIRM_REQUIRED"
    POLICY_BLOCKED = "E_POLICY_BLOCKED"
    BUDGET_EXHAUSTED = "E_BUDGET_EXHAUSTED"
    TIMEOUT = "E_TIMEOUT"
    INVALID_OUTPUT = "E_INVALID_OUTPUT"
    RETRIEVAL_EMPTY = "E_RETRIEVAL_EMPTY"
    DB_WRITE = "E_DB_WRITE"
    IDEMPOTENT_REPLAY = "E_IDEMPOTENT_REPLAY"
    SCRIPT_MISS = "E_SCRIPT_MISS"


class DomainError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, hint: str = ""):
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.message = message
        self.hint = hint


# --------------------------------------------------------------------------
# 1. 枚举
# --------------------------------------------------------------------------
class Intent(str, Enum):
    refund = "refund"
    address_change = "address_change"
    shipping_urge = "shipping_urge"
    other = "other"


class AftersalesType(str, Enum):
    refund_only = "refund_only"
    return_refund = "return_refund"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"          # 平台值无法映射，必须配 platform_anomaly


class CaseStatus(str, Enum):
    INITIATED = "INITIATED"
    REVIEWING = "REVIEWING"
    APPROVED = "APPROVED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    AWAITING_BUYER_SHIP = "AWAITING_BUYER_SHIP"


class Verdict(str, Enum):
    approve = "approve"
    partial = "partial"
    reject = "reject"
    undecided = "undecided"


class SendGate(str, Enum):
    auto = "auto"
    human = "human"


class StopReason(str, Enum):
    finalized = "finalized"
    budget_exhausted = "budget_exhausted"
    timeout = "timeout"
    invalid_output = "invalid_output"
    rejected = "rejected"
    degraded = "degraded"


class ReasonCode(str, Enum):
    OK = "R_OK"
    PLATFORM_ANOMALY = "R_PLATFORM_ANOMALY"
    ORDER_NOT_ELIGIBLE = "R_ORDER_NOT_ELIGIBLE"
    THREAT_OR_LEGAL = "R_THREAT_OR_LEGAL"
    CATEGORY_EXCLUDED = "R_CATEGORY_EXCLUDED"
    OUT_OF_WINDOW = "R_OUT_OF_WINDOW"
    AMOUNT_OVER_LIMIT = "R_AMOUNT_OVER_LIMIT"
    POLICY_GRAY_BAND = "R_POLICY_GRAY_BAND"
    MISSING_EVIDENCE = "R_MISSING_EVIDENCE"
    PARTIAL_OVER_RATIO = "R_PARTIAL_OVER_RATIO"
    HUMAN_REQUESTED = "R_HUMAN_REQUESTED"
    MODEL_LOW_CONFIDENCE = "R_MODEL_LOW_CONFIDENCE"
    NOT_A_REFUND = "R_NOT_A_REFUND"
    MODEL_NEEDS_HUMAN = "R_MODEL_NEEDS_HUMAN"


# --------------------------------------------------------------------------
# 2. 标量类型
# --------------------------------------------------------------------------
def _reject_float(v: Any) -> Any:
    if isinstance(v, float):
        raise ValueError("金额必须以整数分传入，禁止 float（见 CONTRACT §3.3）")
    return v


Cents = Annotated[int, Field(ge=0), BeforeValidator(_reject_float)]


# --------------------------------------------------------------------------
# 3. 订单（中立模型）
# --------------------------------------------------------------------------
class OrderItem(BaseModel):
    sku: str
    title: str
    qty: int = Field(gt=0)
    unit_cents: Cents
    category: str = "general"


class ShipmentItem(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class Shipment(BaseModel):
    package_id: str
    carrier: str
    tracking_no: str
    shipped_at: AwareDatetime | None = None
    delivered_at: AwareDatetime | None = None
    items: list[ShipmentItem] = Field(default_factory=list)


class Order(BaseModel):
    order_ref: str
    status: OrderStatus
    paid_cents: Cents
    currency: str = "CNY"
    created_at: AwareDatetime
    signed_at: AwareDatetime | None = None
    items: list[OrderItem] = Field(default_factory=list)
    shipments: list[Shipment] = Field(default_factory=list)
    # 平台原始载荷：不透明，仅 adapters/ 可读（AC04 静态扫描）
    raw_ref: str | None = None
    platform_anomaly: bool = False

    @property
    def last_delivered_at(self) -> datetime | None:
        """多包裹：签收口径取最晚一个已签收包裹（AC02）。"""
        ts = [s.delivered_at for s in self.shipments if s.delivered_at is not None]
        return max(ts) if ts else None


# --------------------------------------------------------------------------
# 4. 售后单与事件
# --------------------------------------------------------------------------
class CaseEvent(BaseModel):
    event_id: str
    from_status: CaseStatus | None = None
    to_status: CaseStatus
    actor: str
    at: AwareDatetime
    note: str = ""


class AftersalesCase(BaseModel):
    case_id: str
    ticket_id: str
    order_ref: str
    type: AftersalesType
    reason_code: str = ""
    requested_cents: Cents = 0
    amount_cents: Cents = 0
    status: CaseStatus = CaseStatus.INITIATED
    events: list[CaseEvent] = Field(default_factory=list)
    platform_refund_id: str | None = None

    def append_event(self, event: CaseEvent, idem_key: str) -> None:
        """幂等域 = (case_id, idem_key)，不是全局唯一（AC05 / v1 事故教训）。"""
        if any(e.event_id == f"{self.case_id}:{idem_key}" for e in self.events):
            return
        if event.event_id != f"{self.case_id}:{idem_key}":
            event = event.model_copy(update={"event_id": f"{self.case_id}:{idem_key}"})
        self.events.append(event)

    @property
    def last_status(self) -> CaseStatus:
        return self.events[-1].to_status if self.events else self.status


# --------------------------------------------------------------------------
# 5. 策略对象（CONTRACT §6）
# --------------------------------------------------------------------------
class CategoryRule(BaseModel):
    auto_limit_cents: Cents
    human_floor_cents: Cents
    excluded: bool = False

    @model_validator(mode="after")
    def _order(self) -> "CategoryRule":
        if self.human_floor_cents < self.auto_limit_cents:
            raise ValueError("human_floor_cents 必须 ≥ auto_limit_cents")
        return self


class RefundPolicy(BaseModel):
    version: str
    auto_limit_cents: Cents = 5000
    human_floor_cents: Cents = 5000
    window_days: int = Field(default=7, ge=0)
    window_basis: Literal["signed_at", "created_at"] = "signed_at"
    per_category: dict[str, CategoryRule] = Field(default_factory=dict)
    max_partial_ratio: float = Field(default=1.0, gt=0, le=1)

    @model_validator(mode="after")
    def _invariants(self) -> "RefundPolicy":
        if self.human_floor_cents < self.auto_limit_cents:
            raise ValueError("human_floor_cents 必须 ≥ auto_limit_cents（AC12 灰带前提）")
        return self

    def for_category(self, category: str) -> CategoryRule:
        return self.per_category.get(
            category,
            CategoryRule(
                auto_limit_cents=self.auto_limit_cents,
                human_floor_cents=self.human_floor_cents,
            ),
        )


class Signals(BaseModel):
    """策略层输入：只放事实，不放结论。"""

    order_status: OrderStatus
    signed_at: AwareDatetime | None = None
    created_at: AwareDatetime
    now: AwareDatetime
    amount_cents: Cents
    paid_cents: Cents
    category: str = "general"
    evidence_provided: bool = False
    has_threat: bool = False
    user_requested_human: bool = False
    model_confidence: float = 1.0
    platform_anomaly: bool = False


class PolicyDecision(BaseModel):
    verdict: Verdict
    send_gate: SendGate
    approved_amount_cents: Cents | None = None
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    primary_reason: ReasonCode = ReasonCode.OK
    policy_version: str


# --------------------------------------------------------------------------
# 6. 模型配置（五元组）
# --------------------------------------------------------------------------
class LLMConfig(BaseModel):
    provider: Literal["scripted", "openai_compat"] = "scripted"
    model: str = "scripted-v1"
    prompt_version: str = ""
    token_budget: int = Field(default=6000, ge=1)
    timeout_ms: int = Field(default=30000, ge=1)

    @staticmethod
    def prompt_hash(template: str) -> str:
        return hashlib.sha256(template.encode("utf-8")).hexdigest()[:8]


# --------------------------------------------------------------------------
# 7. 检索
# --------------------------------------------------------------------------
class QaDoc(BaseModel):
    qa_id: str
    question: str
    answer: str = Field(max_length=200)
    category: str
    tags: list[str] = Field(default_factory=list)
    source: str
    status: Literal["draft", "approved"] = "draft"
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None


class Hit(BaseModel):
    qa_id: str
    score: float
    matched_terms: list[str] | None = None
    source: str = ""


# --------------------------------------------------------------------------
# 8. 出口契约
# --------------------------------------------------------------------------
class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float | None = None   # 缺 usage 记 null，不记 0
    estimated: bool = False


class ToolCallTrace(BaseModel):
    step: int
    name: str
    ok: bool
    latency_ms: int = 0
    error_code: str | None = None
    args_digest: str = ""


class Citation(BaseModel):
    qa_id: str | None = None
    quote: str
    source: Literal["kb", "tool"]


class DraftView(BaseModel):
    text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class CaseView(BaseModel):
    case_id: str
    type: AftersalesType
    status: CaseStatus
    amount_cents: Cents = 0
    platform_refund_id: str | None = None


class TicketIn(BaseModel):
    ticket_id: str = Field(min_length=6, max_length=40)
    user_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=2000)
    order_ref: str | None = None
    channel: str = "app"
    created_at: AwareDatetime


class TicketOut(BaseModel):
    run_id: str
    ticket_id: str
    intent: Intent
    aftersales_type: AftersalesType | None = None
    case: CaseView | None = None
    draft: DraftView = Field(default_factory=DraftView)
    verdict: Verdict = Verdict.undecided
    send_gate: SendGate = SendGate.human
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    stop_reason: StopReason = StopReason.finalized
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    policy_version: str = ""
    prompt_version: str = ""
    model: str = ""
