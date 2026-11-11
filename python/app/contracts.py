"""Wire contracts for /internal/agent/ask.

Field names intentionally mirror `docs/api/openapi.yaml` (camelCase) so the
payload can be consumed by Java's strict Jackson mapper without aliases.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Category(str, Enum):
    CONSULT = "CONSULT"
    AFTERSALE = "AFTERSALE"


class Intent(str, Enum):
    REFUND_ELIGIBILITY = "REFUND_ELIGIBILITY"
    REFUND_REQUEST = "REFUND_REQUEST"
    LOGISTICS = "LOGISTICS"
    POLICY = "POLICY"
    OTHER = "OTHER"
    HANDOFF = "HANDOFF"


class ReplyType(str, Enum):
    INFORMATIONAL = "INFORMATIONAL"
    DECISIONAL = "DECISIONAL"


class TransferReason(str, Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NO_EVIDENCE = "NO_EVIDENCE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    TOOL_FAILED = "TOOL_FAILED"
    AMBIGUOUS_ORDER = "AMBIGUOUS_ORDER"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    USER_REQUESTED = "USER_REQUESTED"
    INSUFFICIENT_INFO = "INSUFFICIENT_INFO"


class ActionType(str, Enum):
    REFUND = "REFUND"
    NONE = "NONE"


class MessageRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class History(StrictModel):
    role: MessageRole
    text: str = Field(max_length=500)
    createdAt: str | None = None


class Context(StrictModel):
    orderNo: str | None = None
    summary: str | None = Field(default=None, max_length=300)
    history: list[History] = Field(default_factory=list, max_length=12)


class AskRequest(StrictModel):
    traceId: str
    ticketId: str
    requestId: str
    attempt: int = Field(ge=0)
    taskEpoch: int = Field(ge=0)
    userId: str
    category: Category
    message: str = Field(max_length=500)
    context: Context | None = None


class Slots(StrictModel):
    orderNo: str | None = None
    missing: list[str] = Field(default_factory=list)


class SuggestedAction(StrictModel):
    action: ActionType
    amountCents: int | None = Field(default=None, ge=1)
    needHumanConfirm: bool | None = None


class Citation(StrictModel):
    docId: str
    title: str
    clauseId: str
    policyVersion: str


class ModelInfo(StrictModel):
    provider: str
    promptVersion: str


class AskResponse(StrictModel):
    intent: Intent
    slots: Slots = Field(default_factory=Slots)
    confidence: float = Field(ge=0, le=1)
    replyType: ReplyType
    needHumanReview: bool
    transferReason: TransferReason | None = None
    suggestedAction: SuggestedAction | None = None
    replyDraft: str | None = Field(default=None, max_length=200)
    citations: list[Citation] = Field(default_factory=list)
    degraded: bool = False
    model: ModelInfo
