"""垂直切片：一张工单从文本到 TicketOut 的单向流水线。

顺序固定，任一步失败都**落 StopReason，不抛到调用方**（除领域错误需要显式暴露的用例）。
预算与超时在调用模型**之前/之后**各查一次：事前不花冤枉钱，事后不留半截草稿。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.adapters.base import PlatformAdapter
from app.contracts.models import (
    AftersalesCase,
    CaseView,
    Citation,
    DomainError,
    DraftView,
    ErrorCode,
    Intent,
    LLMConfig,
    Order,
    PolicyDecision,
    ReasonCode,
    RefundPolicy,
    SendGate,
    Signals,
    StopReason,
    TicketIn,
    TicketOut,
    ToolCallTrace,
    Usage,
    Verdict,
)
from app.domain.cases import CaseService
from app.llm.base import Proposal, Provider
from app.llm.prompts import build_prompt, prompt_version
from app.llm.scripted import parse_proposal
from app.policy.drafts import shape_draft
from app.policy.refund_policy import evaluate

THREAT_RE = re.compile(r"12315|曝光|法院|起诉|律师函|投诉到")
HUMAN_RE = re.compile(r"转人工|人工客服|找人工|真人")


@dataclass
class RunResult:
    out: TicketOut
    case: AftersalesCase | None = None
    trace: dict[str, Any] = field(default_factory=dict)


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]


class _Traces:
    def __init__(self) -> None:
        self.items: list[ToolCallTrace] = []

    def add(self, name: str, ok: bool, t0: float, *, args: Any = None, error: str | None = None) -> None:
        self.items.append(
            ToolCallTrace(
                step=len(self.items) + 1,
                name=name,
                ok=ok,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error_code=error,
                args_digest=_digest(args) if args is not None else "",
            )
        )


def _category(order: Order) -> str:
    cats = {i.category for i in order.items}
    return cats.pop() if len(cats) == 1 else "general"


def run(
    ticket: TicketIn,
    *,
    adapter: PlatformAdapter,
    provider: Provider,
    policy: RefundPolicy,
    llm: LLMConfig,
    now: datetime,
    confirm: str | None = None,
    kb_quotes: dict[str, str] | None = None,
) -> RunResult:
    t_start = time.perf_counter()
    traces = _Traces()
    order_ref = ticket.order_ref or ""
    approver = confirm.split(":", 1)[1] if confirm and confirm.startswith("human:") else None
    # run_id 必须在任何分支里都一致：把模型配置也算进去，否则"超时跑"和"正常跑"会同号
    rid = _run_id(ticket, order_ref, prompt_version(), policy.version, confirm, llm)

    # 1) 取单
    t0 = time.perf_counter()
    try:
        order = adapter.fetch_order(order_ref)
        traces.add("fetch_order", True, t0, args={"ref": order_ref})
    except DomainError as exc:
        traces.add("fetch_order", False, t0, args={"ref": order_ref}, error=exc.code.value)
        return _fail(ticket, traces, t_start, order_ref, ErrorCode.ORDER_NOT_FOUND, rid)

    # 2) 组 prompt + 事前预算
    pv = prompt_version()
    prompt = build_prompt(ticket.text, order)
    est_input = max(1, len(prompt) // 4)
    usage = Usage(input_tokens=est_input, output_tokens=0, estimated=True)
    if est_input > llm.token_budget:
        return _stop(
            ticket, traces, t_start, order_ref, StopReason.budget_exhausted, usage,
            policy=policy, rid=rid, prompt_version=pv, model=llm.model,
        )

    # 3) 调模型（一次 + 最多一次重试）
    t0 = time.perf_counter()
    resp = provider.propose(prompt, order_ref)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    usage.output_tokens = resp.output_tokens
    usage.input_tokens = max(usage.input_tokens, resp.input_tokens)
    if elapsed_ms > llm.timeout_ms:
        traces.add("llm.propose", False, t0, args={"provider": provider.name}, error=ErrorCode.TIMEOUT.value)
        return _stop(
            ticket, traces, t_start, order_ref, StopReason.timeout, usage,
            policy=policy, rid=rid, prompt_version=pv, model=llm.model, latency_override=elapsed_ms,
        )
    traces.add("llm.propose", True, t0, args={"provider": provider.name, "model": llm.model})

    proposal: Proposal | None = None
    for attempt in range(2):
        try:
            proposal = parse_proposal(resp.raw)
            break
        except Exception:  # noqa: BLE001 - 任何解析失败都走同一条降级路径
            if attempt == 1:
                break
            t0 = time.perf_counter()
            resp = provider.propose(prompt, order_ref)
            usage.output_tokens += resp.output_tokens
            traces.add("llm.propose.retry", True, t0, args={"attempt": 2})
    if proposal is None:
        out = _stop(
            ticket, traces, t_start, order_ref, StopReason.invalid_output, usage,
            policy=policy, rid=rid, prompt_version=pv, model=llm.model,
        )
        out.out.draft.risk_flags = ["degraded"]
        return out

    # 4) 事实 → 信号 → 策略
    slots = proposal.slots or {}
    amount = int(slots.get("amount_cents", 0) or 0)
    signals = Signals(
        order_status=order.status,
        signed_at=order.last_delivered_at,
        created_at=order.created_at,
        now=now,
        amount_cents=amount,
        paid_cents=order.paid_cents,
        category=_category(order),
        evidence_provided=bool(slots.get("evidence_provided", False)),
        has_threat=bool(slots.get("has_threat", False)) or bool(THREAT_RE.search(ticket.text)),
        user_requested_human=bool(slots.get("user_requested_human", False)) or bool(HUMAN_RE.search(ticket.text)),
        model_confidence=proposal.confidence,
        platform_anomaly=order.platform_anomaly,
    )
    t0 = time.perf_counter()
    decision = evaluate(signals, policy)
    traces.add("policy.evaluate", True, t0, args={"policy": policy.version})

    # 4b) 只读意图不适用退款策略：不下退款结论，一律人工（CONTRACT §6.5）
    if proposal.intent is not Intent.refund:
        decision = PolicyDecision(
            verdict=Verdict.undecided,
            send_gate=SendGate.human,
            approved_amount_cents=None,
            reason_codes=[ReasonCode.NOT_A_REFUND],
            primary_reason=ReasonCode.NOT_A_REFUND,
            policy_version=policy.version,
        )
    # 模型自己说"拿不准"时，不许自动发（needs_human 是信号，不是授权）
    elif proposal.needs_human and decision.send_gate is SendGate.auto:
        codes = [c for c in decision.reason_codes if c is not ReasonCode.OK]
        decision = decision.model_copy(
            update={
                "send_gate": SendGate.human,
                "reason_codes": [*codes, ReasonCode.MODEL_NEEDS_HUMAN],
                "primary_reason": ReasonCode.MODEL_NEEDS_HUMAN,
            }
        )

    # 5) 报价口径
    text, flags = shape_draft(proposal.draft, decision, order_ref=order_ref, user_requested_human=signals.user_requested_human)
    citations = _check_citations(proposal.citations, kb_quotes or {}, flags)

    # 6) 落域：建单 → 走状态机
    case: AftersalesCase | None = None
    if proposal.intent is Intent.refund and proposal.aftersales_type is not None:
        svc = CaseService(adapter)
        case = svc.open(
            case_id=f"C{ticket.ticket_id}",
            ticket_id=ticket.ticket_id,
            order_ref=order_ref,
            case_type=proposal.aftersales_type,
            requested_cents=amount,
            paid_cents=order.paid_cents,
            now=now,
            reason_code=decision.primary_reason.value,
        )
        svc.submit(case, now=now)
        if decision.verdict is Verdict.approve and approver:
            approved = decision.approved_amount_cents
            if approved is not None:
                case.amount_cents = approved
            svc.approve(case, approver=approver, now=now)
            if case.status is not None and case.type.value == "refund_only":
                svc.execute(case, approver=approver, now=now)

    out = TicketOut(
        run_id=rid,
        ticket_id=ticket.ticket_id,
        intent=proposal.intent,
        aftersales_type=proposal.aftersales_type,
        case=CaseView(
            case_id=case.case_id, type=case.type, status=case.status,
            amount_cents=case.amount_cents, platform_refund_id=case.platform_refund_id,
        ) if case else None,
        draft=DraftView(text=text, citations=citations, risk_flags=flags),
        verdict=decision.verdict,
        send_gate=decision.send_gate,
        reason_codes=decision.reason_codes,
        stop_reason=StopReason.finalized,
        tool_calls=traces.items,
        usage=usage,
        latency_ms=int((time.perf_counter() - t_start) * 1000),
        policy_version=policy.version,
        prompt_version=pv,
        model=llm.model,
    )
    return RunResult(out=out, case=case, trace={"signals": signals.model_dump(mode="json"), "policy": decision.model_dump(mode="json")})


def _check_citations(cites: list[Citation], kb: dict[str, str], flags: list[str]) -> list[Citation]:
    """引用必须能在知识库里逐字找；找不到的不是"少一条"，是造假（AC18）。"""
    kept: list[Citation] = []
    for c in cites:
        if c.source == "kb" and c.qa_id not in kb:
            flags.append("CITATION_UNRESOLVED")
            continue
        if c.source == "kb" and c.quote not in kb.get(c.qa_id or "", ""):
            flags.append("CITATION_QUOTE_MISMATCH")
            continue
        kept.append(c)
    return kept


def _run_id(ticket: TicketIn, order_ref: str, pv: str, policy_version: str, confirm: str | None, llm: LLMConfig) -> str:
    raw = "|".join([
        ticket.ticket_id, order_ref, pv, policy_version, confirm or "-",
        llm.provider, llm.model, str(llm.token_budget), str(llm.timeout_ms),
    ])
    return "run_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def _stop(ticket, traces, t_start, order_ref, reason: StopReason, usage: Usage, *, policy, rid: str, prompt_version: str, model: str, latency_override: int | None = None) -> RunResult:
    out = TicketOut(
        run_id=rid,
        ticket_id=ticket.ticket_id,
        intent=Intent.other,
        stop_reason=reason,
        send_gate=SendGate.human,
        tool_calls=traces.items,
        usage=usage,
        latency_ms=latency_override if latency_override is not None else int((time.perf_counter() - t_start) * 1000),
        policy_version=policy.version,
        prompt_version=prompt_version,
        model=model,
    )
    return RunResult(out=out, case=None, trace={})


def _fail(ticket, traces, t_start, order_ref, code: ErrorCode, rid: str) -> RunResult:
    out = TicketOut(
        run_id=rid,
        ticket_id=ticket.ticket_id,
        intent=Intent.other,
        stop_reason=StopReason.degraded,
        send_gate=SendGate.human,
        tool_calls=traces.items,
        draft=DraftView(text="", risk_flags=[code.value]),
        usage=Usage(estimated=True),
        latency_ms=int((time.perf_counter() - t_start) * 1000),
    )
    return RunResult(out=out, case=None, trace={"error": code.value})
