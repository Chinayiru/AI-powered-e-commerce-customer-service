"""QC01–QC13 离线指标评测：在 holdout 集上跑只读 Agent，产出可复算的指标。

用法（在 python/ 目录下）：

    python eval/run_eval.py                  # 跑默认 holdout_v1.jsonl
    python eval/run_eval.py --repeat 2       # 同集重跑，报 QC12 差值

不使用网络与数据库：工具层用内置演示订单夹具（与 Java OrderToolService 同口径），
QC12 只验证同日、同进程、同实例重复性；跨日与跨进程未验证，日期依赖仍存在。

指标口径见 docs/BOUNDARY.md §15.2 与 docs/TEST_PLAN.md。凡需要人工判断的项
（QC05 草稿可用率、QC06 引用正确性的语义部分）不伪造数字，一律标 未评 并说明原因。
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import AgentService  # noqa: E402
from app.config import Settings  # noqa: E402
from app.contracts import AskRequest, Category, Context, Intent  # noqa: E402
from app.knowledge import CHUNKS  # noqa: E402
from app.intent import RULES_VERSION  # noqa: E402

INTENTS = ("REFUND_REQUEST", "REFUND_ELIGIBILITY", "LOGISTICS", "POLICY", "OTHER")
BANNED = ("赔付", "赔偿", "保证", "一定", "百分百", "已退款", "已处理", "已改地址")

# 与 Java OrderToolService 的演示数据同口径，保证评测与真实调用看到同一批订单。
DEMO_ORDERS: dict[str, dict[str, Any]] = {
    "O1001": dict(orderNo="O1001", status="PAID", amountCents=5800, refundableAmountCents=5800,
                  paidAt="2026-11-01T10:00:00+08:00", deliveredAt=None),
    "O1002": dict(orderNo="O1002", status="SHIPPED", amountCents=12900, refundableAmountCents=12900,
                  paidAt="2026-11-05T10:00:00+08:00", deliveredAt=None),
    "O1003": dict(orderNo="O1003", status="DELIVERED", amountCents=8800, refundableAmountCents=8800,
                  paidAt="2026-09-20T10:00:00+08:00", deliveredAt="2026-10-01T10:00:00+08:00"),
    "O1004": dict(orderNo="O1004", status="PAID", amountCents=9900, refundableAmountCents=9900,
                  paidAt="2026-11-02T10:00:00+08:00", deliveredAt=None),
    "O1005": dict(orderNo="O1005", status="PAID", amountCents=3000, refundableAmountCents=3000,
                  paidAt="2026-11-02T10:00:00+08:00", deliveredAt=None),
    "O1006": dict(orderNo="O1006", status="PAID", amountCents=25000, refundableAmountCents=25000,
                  paidAt="2026-11-03T10:00:00+08:00", deliveredAt=None),
    "O1007": dict(orderNo="O1007", status="DELIVERED", amountCents=6600, refundableAmountCents=6600,
                  paidAt="2026-11-01T10:00:00+08:00", deliveredAt="2026-11-10T10:00:00+08:00"),
    "O1008": dict(orderNo="O1008", status="SHIPPED", amountCents=4000, refundableAmountCents=4000,
                  paidAt="2026-11-06T10:00:00+08:00", deliveredAt=None),
    "O1009": dict(orderNo="O1009", status="PAID", amountCents=0, refundableAmountCents=0,
                  paidAt="2026-11-07T10:00:00+08:00", deliveredAt=None),
    "O1010": dict(orderNo="O1010", status="DELIVERED", amountCents=5000, refundableAmountCents=0,
                  paidAt="2026-10-01T10:00:00+08:00", deliveredAt="2026-10-05T10:00:00+08:00"),
    "O1012": dict(orderNo="O1012", status="CLOSED", amountCents=4500, refundableAmountCents=0,
                  paidAt="2026-09-01T10:00:00+08:00", deliveredAt=None),
}
for _order in DEMO_ORDERS.values():
    _order.setdefault("userId", "U001")
    _order.setdefault("refundedAmountCents", _order["amountCents"] - _order["refundableAmountCents"])

DEMO_SHIPMENTS = {
    "O1002": {
        "orderNo": "O1002",
        "status": "IN_TRANSIT",
        "shipments": [{
            "carrierCode": "MOCK",
            "trackingNo": "MOCK002",
            "status": "IN_TRANSIT",
            "events": [{"at": "2026-11-09T09:00:00+08:00", "code": "ARRIVED",
                        "text": "到达分拨中心"}],
        }],
    },
    "O1008": {
        "orderNo": "O1008",
        "status": "IN_TRANSIT",
        "shipments": [{
            "carrierCode": "MOCK",
            "trackingNo": "MOCK008",
            "status": "IN_TRANSIT",
            "events": [{"at": "2026-11-12T09:00:00+08:00", "code": "OUT_FOR_DELIVERY",
                        "text": "派送中"}],
        }],
    },
}


class DemoFakeTools:
    """只读工具替身：与 pytest 的 FakeTools 行为一致，订单集覆盖 holdout 用到的全部单号。"""

    def query_order(self, user_id: str, order_no: str) -> dict[str, Any] | None:
        if order_no == "O5000":
            from app.tools import ToolUnavailable

            raise ToolUnavailable("TOOL_UNAVAILABLE", "boom")
        return DEMO_ORDERS.get(order_no)

    def get_logistics(self, user_id: str, order_no: str) -> dict[str, Any] | None:
        if order_no == "O5001":
            from app.tools import ToolUnavailable

            raise ToolUnavailable("TOOL_TIMEOUT", "timeout")
        return DEMO_SHIPMENTS.get(order_no)


def make_settings() -> Settings:
    return Settings(
        java_base_url="http://localhost:8080",
        hmac_secret="eval-secret-0123456789abcdef0123456789",
        tool_timeout_seconds=1.0,
        tool_retries=1,
        confidence_threshold=0.60,
        auto_suggest_limit_cents=5000,
        return_window_days=7,
        policy_version="2026-11",
        prompt_version="p1.0.0",
        provider="scripted",
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def to_request(case: dict[str, Any]) -> AskRequest:
    context = None
    if case.get("context_order_no"):
        context = Context(orderNo=case["context_order_no"])
    return AskRequest(
        traceId=f"eval-{case['id']}",
        ticketId=f"T-{case['id']}",
        requestId=f"eval-{case['id']}",
        attempt=0,
        taskEpoch=0,
        userId="U001",
        category=Category.AFTERSALE,
        message=case["message"],
        context=context,
    )


def run_once(service: AgentService, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        started = time.perf_counter()
        response = service.answer(to_request(case))
        elapsed_ms = (time.perf_counter() - started) * 1000
        results.append({
            "id": case["id"],
            "message": case["message"],
            "gold_intent": case["gold_intent"],
            "gold_transfer_reason": case.get("gold_transfer_reason"),
            "gold_order_no": case.get("gold_order_no"),
            "context_order_no": case.get("context_order_no"),
            "gold_clauses": case.get("gold_clauses") or [],
            "expect_no_order": case.get("expect_no_order", False),
            "intent": response.intent.value,
            "transfer_reason": response.transferReason.value if response.transferReason else None,
            "order_no": response.slots.orderNo,
            "confidence": response.confidence,
            "reply_type": response.replyType.value,
            "need_human_review": response.needHumanReview,
            "degraded": response.degraded,
            "reply_draft": response.replyDraft,
            "citations": [f"{c.docId}#{c.clauseId}" for c in response.citations],
            "policy_version": response.citations[0].policyVersion if response.citations else None,
            "provider": response.model.provider,
            "prompt_version": response.model.promptVersion,
            "amount_cents": response.suggestedAction.amountCents if response.suggestedAction else None,
            "latency_ms": round(elapsed_ms, 3),
        })
    return results


def qc01_dataset(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["gold_intent"]] = counts.get(case["gold_intent"], 0) + 1
    states = [case.get("order_state") for case in cases]
    intent_ok = all(counts.get(name, 0) >= 8 for name in INTENTS)
    return {
        "total": len(cases),
        "intent_counts": counts,
        "five_classes_each_at_least_8": intent_ok,
        "order_states": {state: states.count(state) for state in sorted(set(states))},
        "three_order_states_covered": all(s in states for s in ("PAID", "SHIPPED", "DELIVERED")),
        "no_order_cases": sum(1 for c in cases if not c.get("gold_order_no")),
        "expect_no_order_cases": sum(1 for c in cases if c.get("expect_no_order")),
        "not_found_cases": sum(1 for c in cases if c.get("gold_order_no") == "O9999"),
        "ambiguous_cases": sum(1 for c in cases if c["gold_intent"] == "HANDOFF"
                               and c.get("gold_transfer_reason") == "AMBIGUOUS_ORDER"),
        "unique_ids": len({c["id"] for c in cases}) == len(cases),
        "message_length_ok": all(0 < len(c["message"]) <= 500 for c in cases),
        "pass": intent_ok
        and all(s in states for s in ("PAID", "SHIPPED", "DELIVERED"))
        and len({c["id"] for c in cases}) == len(cases),
    }


def qc02_intent(results: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = {gold: {pred: 0 for pred in INTENTS} for gold in INTENTS}
    correct = total = 0
    for item in results:
        if item["gold_intent"] == "HANDOFF":
            continue
        total += 1
        matrix[item["gold_intent"]][item["intent"]] = matrix[item["gold_intent"]].get(item["intent"], 0) + 1
        if item["intent"] == item["gold_intent"]:
            correct += 1
    per_class = {}
    for name in INTENTS:
        row = matrix[name]
        support = sum(row.values())
        hit = row.get(name, 0)
        per_class[name] = {"support": support, "correct": hit,
                           "recall": round(hit / support, 4) if support else None}
    handoff = [r for r in results if r["gold_intent"] == "HANDOFF"]
    handoff_ok = sum(1 for r in handoff if r["intent"] == "HANDOFF")
    return {
        "accuracy_5class": round(correct / total, 4) if total else None,
        "total_5class": total,
        "correct_5class": correct,
        "confusion_matrix": matrix,
        "per_class": per_class,
        "go_nogo": 0.85,
        "gate_pass": (correct / total) >= 0.85 if total else False,
        "handoff_recall": round(handoff_ok / len(handoff), 4) if handoff else None,
        "handoff_support": len(handoff),
        "wrong_cases": [{"id": r["id"], "gold": r["gold_intent"], "pred": r["intent"],
                         "message": r["message"], "reply": r["reply_draft"]}
                        for r in results
                        if r["gold_intent"] != "HANDOFF" and r["intent"] != r["gold_intent"]],
    }


def qc03_slots(results: list[dict[str, Any]]) -> dict[str, Any]:
    """orderNo 槽位精确率/召回。

    期望单号 = gold_order_no 或（无金标单号但上文已给单号时的）context_order_no；
    应追问单号的用例（expect_no_order）期望为 None。
    """
    tp = fp = fn = exact = 0
    wrong = []
    for item in results:
        if item.get("expect_no_order"):
            expected = None
        else:
            expected = item["gold_order_no"] or item.get("context_order_no")
        pred = item["order_no"]
        if expected and pred == expected:
            tp += 1
        elif expected and pred != expected:
            fn += 1
            wrong.append({"id": item["id"], "expected": expected, "pred": pred})
        elif not expected and pred:
            fp += 1
            wrong.append({"id": item["id"], "expected": None, "pred": pred})
        if expected == pred:
            exact += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "exact_match": round(exact / len(results), 4) if results else None,
        "target_recall": 0.90,
        "gate_pass": (recall or 0) >= 0.90,
        "tp": tp, "fp": fp, "fn": fn,
        "wrong_cases": wrong,
    }


def qc04_recall_at_3(results: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in results if r["gold_clauses"]]
    hits = 0
    full = 0
    per_case = []
    for item in scored:
        top3 = item["citations"][:3]
        found = [clause for clause in item["gold_clauses"] if clause in top3]
        hits += len(found)
        if len(found) == len(item["gold_clauses"]):
            full += 1
        else:
            per_case.append({"id": item["id"], "gold": item["gold_clauses"], "top3": top3})
    gold_total = sum(len(r["gold_clauses"]) for r in scored)
    return {
        "cases_with_gold_clauses": len(scored),
        "recall_at_3": round(hits / gold_total, 4) if gold_total else None,
        "all_gold_hit_rate": round(full / len(scored), 4) if scored else None,
        "misses": per_case,
    }


def qc05_draft(results: list[dict[str, Any]]) -> dict[str, Any]:
    with_draft = [r for r in results if r["reply_draft"]]
    return {
        "status": "未评",
        "reason": "草稿可用率要求双人独立评分并计算 Cohen's κ（BOUNDARY §15.2 QC05），"
                  "脚本无法代替人工判断。此处只报可自动统计的分母。",
        "cases_with_reply_draft": len(with_draft),
        "total": len(results),
        "draft_coverage": round(len(with_draft) / len(results), 4) if results else None,
        "go_nogo": 0.80,
    }


def qc06_citation(results: list[dict[str, Any]]) -> dict[str, Any]:
    known = {f"{chunk.doc_id}#{chunk.clause_id}" for chunk in CHUNKS}
    total_cites = 0
    unknown = []
    cited_cases = 0
    overlap_cases = 0
    need_citation = [r for r in results if r["intent"] != "HANDOFF"]
    for item in results:
        cites = item["citations"]
        if cites:
            cited_cases += 1
        total_cites += len(cites)
        for cite in cites:
            if cite not in known:
                unknown.append({"id": item["id"], "cite": cite})
        if item["gold_clauses"] and cites:
            if set(item["gold_clauses"]) & set(cites):
                overlap_cases += 1
    with_gold = [r for r in results if r["gold_clauses"] and r["intent"] != "HANDOFF"]
    return {
        "resolvable_rate": round(1 - len(unknown) / total_cites, 4) if total_cites else None,
        "total_citations": total_cites,
        "unknown_citations": unknown,
        "citation_coverage_non_handoff": round(cited_cases / len(need_citation), 4) if need_citation else None,
        "gold_overlap_rate": round(overlap_cases / len(with_gold), 4) if with_gold else None,
        "gold_overlap_denominator": len(with_gold),
        "note": "可解析率与金标交集率是必要条件；语义层面的引用正确性仍需人工抽检。",
        "go_nogo": 0.85,
    }


def qc07_hallucination(results: list[dict[str, Any]]) -> dict[str, Any]:
    flagged = []
    for item in results:
        text = item["reply_draft"] or ""
        problems = []
        for token in BANNED:
            if token in text:
                problems.append(f"banned:{token}")
        for amount in _money_amounts(text):
            gold = item["gold_order_no"] or ""
            order = DEMO_ORDERS.get(gold)
            if order is None:
                continue
            if amount > order["refundableAmountCents"]:
                problems.append(f"amount_exceeds_refundable:{amount}")
        for order_no in _order_numbers(text):
            # 客户自己提供的单号被原样回述（"没查到订单 O9999"）不算编造。
            if order_no not in DEMO_ORDERS and order_no not in item["message"]:
                problems.append(f"unknown_order:{order_no}")
        if problems:
            flagged.append({"id": item["id"], "problems": problems})
    return {
        "flagged_cases": len(flagged),
        "total": len(results),
        "hallucination_rate": round(len(flagged) / len(results), 4) if results else None,
        "threshold": 0.05,
        "gate_pass": (len(flagged) / len(results)) <= 0.05 if results else False,
        "details": flagged,
    }


def qc08_confidence(results: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = [("lt_0.60", 0.0, 0.60), ("0.60_0.85", 0.60, 0.85), ("ge_0.85", 0.85, 1.01)]
    out = {}
    for name, low, high in buckets:
        rows = [r for r in results if low <= r["confidence"] < high]
        if not rows:
            out[name] = {"count": 0, "accuracy": None, "handoff_ratio": None}
            continue
        correct = sum(1 for r in rows if r["intent"] == r["gold_intent"])
        out[name] = {
            "count": len(rows),
            "accuracy": round(correct / len(rows), 4),
            "handoff_ratio": round(sum(1 for r in rows if r["intent"] == "HANDOFF") / len(rows), 4),
        }
    return {"buckets": out}


def qc09_cost() -> dict[str, Any]:
    return {
        "mode": "rule-based（scripted provider）",
        "tokens_per_request": 0,
        "cost_per_request": 0.0,
        "note": "当前实现不调用 LLM，成本为 0；接入模型后需按 token 用量重测本项。",
    }


def qc10_latency(results: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(r["latency_ms"] for r in results)
    return {
        "p50_ms": round(_percentile(values, 50), 2),
        "p95_ms": round(_percentile(values, 95), 2),
        "max_ms": round(values[-1], 2) if values else None,
        "n": len(values),
        "note": "进程内直调 AgentService，工具为内存夹具；不含 HTTP/序列化开销，不可作为系统延迟对外报。",
    }


def qc11_version(dataset: Path) -> dict[str, Any]:
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    return {
        "dataset": str(dataset.name),
        "dataset_sha256": digest,
        "policy_version": "2026-11",
        "prompt_version": "p1.0.0",
        "rules_version": RULES_VERSION,
        "provider": "scripted",
        "python_version": sys.version.split()[0],
        "harness": "eval/run_eval.py",
        "evaluation_date": date.today().isoformat(),
        "reference_date": None,
        "date_scope": "运行时使用 date.today()，未固定 reference_date；指标仅在 evaluation_date 当日有效。",
    }


def qc12_rerun(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> dict[str, Any]:
    if len(first) != len(second):
        return {"comparable": False, "reason": "两次运行用例数不一致"}
    diff = []
    for a, b in zip(first, second):
        fields = ("intent", "transfer_reason", "order_no", "confidence", "reply_draft", "citations")
        changed = [f for f in fields if a[f] != b[f]]
        if changed:
            diff.append({"id": a["id"], "fields": changed})
    first_acc = _accuracy_5class(first)
    second_acc = _accuracy_5class(second)
    return {
        "comparable": True,
        "changed_cases": len(diff),
        "details": diff,
        "metric": "QC02 同口径（5 类，HANDOFF 不计分母）",
        "accuracy_first": round(first_acc, 4),
        "accuracy_second": round(second_acc, 4),
        "delta_points": round((second_acc - first_acc) * 100, 2),
        "same_instance_consistent": not diff,
        "scope": "同日、同进程、同实例；跨日与跨进程未验证",
    }


def qc13_handoff(results: list[dict[str, Any]]) -> dict[str, Any]:
    predicted = [r for r in results if r["intent"] == "HANDOFF"]
    gold = [r for r in results if r["gold_intent"] == "HANDOFF"]
    reason_ok = [r for r in predicted
                 if r["gold_intent"] == "HANDOFF" and r["transfer_reason"] == r["gold_transfer_reason"]]
    reason_mismatch = [{"id": r["id"], "gold": r["gold_transfer_reason"], "pred": r["transfer_reason"]}
                       for r in predicted
                       if r["gold_intent"] == "HANDOFF" and r["transfer_reason"] != r["gold_transfer_reason"]]
    false_positive = [{"id": r["id"], "reason": r["transfer_reason"], "gold": r["gold_intent"]}
                      for r in predicted if r["gold_intent"] != "HANDOFF"]
    return {
        "predicted_handoff": len(predicted),
        "gold_handoff": len(gold),
        "reason_accuracy": round(len(reason_ok) / len(predicted), 4) if predicted else None,
        "precision": round(len(reason_ok) / len(predicted), 4) if predicted else None,
        "recall": round(len(reason_ok) / len(gold), 4) if gold else None,
        "false_positive_cases": false_positive,
        "reason_mismatch": reason_mismatch,
        "note": "报告项，非合入门槛（BOUNDARY §15.2）。",
    }


def extra_checks(results: list[dict[str, Any]]) -> dict[str, Any]:
    """契约行为项：无单号追问、查无此单降级、工具故障降级。"""
    ask_order_cases = [r for r in results if r["expect_no_order"]]
    follow_up_text = [r for r in ask_order_cases
                      if (r["reply_draft"] or "").find("订单号") >= 0]
    not_found = [r for r in results if r["gold_order_no"] == "O9999"]
    not_found_handled = [r for r in not_found
                         if "没查到" in (r["reply_draft"] or "") or "核对" in (r["reply_draft"] or "")]
    return {
        "expect_no_order_cases": len(ask_order_cases),
        "asked_order_no_cases": len(follow_up_text),
        "not_found_cases": len(not_found),
        "not_found_handled_cases": len(not_found_handled),
        "not_found_need_review": sum(1 for r in not_found if r["need_human_review"]),
        "degraded_cases": sum(1 for r in results if r["degraded"]),
    }


def _money_amounts(text: str) -> list[int]:
    import re

    amounts = []
    for match in re.finditer(r"¥\s*(\d+(?:\.\d{1,2})?)", text):
        amounts.append(int(round(float(match.group(1)) * 100)))
    return amounts


def _order_numbers(text: str) -> list[str]:
    import re

    return re.findall(r"(?i)(?<![A-Z0-9])O\d{4,8}(?![A-Z0-9])", text)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * pct / 100.0
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _accuracy(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r["intent"] == r["gold_intent"]) / len(results)


def _accuracy_5class(results: list[dict[str, Any]]) -> float:
    rows = [r for r in results if r["gold_intent"] != "HANDOFF"]
    if not rows:
        return 0.0
    return sum(1 for r in rows if r["intent"] == r["gold_intent"]) / len(rows)


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# 售后 AI 指标评测报告（QC01–QC13）", ""]
    lines.append(f"- 数据集：`{report['qc11_version']['dataset']}` "
                 f"（sha256 `{report['qc11_version']['dataset_sha256'][:16]}…`，共 {report['qc01_dataset']['total']} 例）")
    lines.append(f"- provider：`{report['qc11_version']['provider']}`，"
                 f"prompt `{report['qc11_version']['prompt_version']}`，"
                 f"policy `{report['qc11_version']['policy_version']}`")
    lines.append("")
    lines.append(f"- 评测日期：`{report['qc11_version']['evaluation_date']}`；reference_date 未固定；指标仅在该日有效，跨日须重评。")
    lines.append("")
    lines.append("| 指标 | 结果 | 门槛 | 结论 |")
    lines.append("| --- | --- | --- | --- |")

    qc2 = report["qc02_intent"]
    lines.append(f"| QC02 意图准确率（5 类，HANDOFF 不计分母） | {_pct(qc2['accuracy_5class'])} "
                 f"（{qc2['correct_5class']}/{qc2['total_5class']}） | ≥85% | {_verdict(qc2['gate_pass'])} |")
    qc3 = report["qc03_slots"]
    lines.append(f"| QC03 槽位 orderNo 召回 | {_pct(qc3['recall'])}（精确率 {_pct(qc3['precision'])}） "
                 f"| ≥90% | {_verdict(qc3['gate_pass'])} |")
    qc4 = report["qc04_recall_at_3"]
    lines.append(f"| QC04 检索 Recall@3 | {_pct(qc4['recall_at_3'])} | 观测项 | — |")
    qc5 = report["qc05_draft"]
    lines.append(f"| QC05 草稿可用率 | 未评（需双人评分） | ≥80% | 待人工 |")
    qc6 = report["qc06_citation"]
    lines.append(f"| QC06 引用可解析率 | {_pct(qc6['resolvable_rate'])}（金标交集率 {_pct(qc6['gold_overlap_rate'])}） "
                 f"| ≥85% | {_verdict((qc6['resolvable_rate'] or 0) >= 0.85)} |")
    qc7 = report["qc07_hallucination"]
    lines.append(f"| QC07 幻觉率 | {_pct(qc7['hallucination_rate'])}（{qc7['flagged_cases']} 例） "
                 f"| ≤5% | {_verdict(qc7['gate_pass'])} |")
    qc9 = report["qc09_cost"]
    lines.append(f"| QC09 成本 | {qc9['cost_per_request']} 元/次（{qc9['mode']}） | 观测项 | — |")
    qc10 = report["qc10_latency"]
    lines.append(f"| QC10 延迟 P50/P95 | {qc10['p50_ms']} / {qc10['p95_ms']} ms（进程内直调，不含 HTTP/序列化，不可作为系统延迟对外报） | 观测项 | — |")
    lines.append(f"| QC11 版本记录 | 评测日期 {report['qc11_version']['evaluation_date']}，reference_date 未固定；prompt p1.0.0 / policy 2026-11 | 当日有效 | 跨日须重评 |")
    lines.append(f"| QC12 同集重跑 | {report['qc12_rerun'].get('changed_cases', '未比较')} 条变化；同日、同进程、同实例；跨日与跨进程未验证 | 同实例重复性检查 | 仅限本次条件 |")
    lines.append(f"| QC13 转人工原因精确率 | {_pct(report['qc13_handoff']['reason_accuracy'])} "
                 f"（召回 {_pct(report['qc13_handoff']['recall'])}） | 报告项 | — |")
    lines.append("")

    gates = [
        ("QC02 意图准确率", qc2["gate_pass"], "rule-based 分类器对同义表达覆盖不足"),
        ("QC03 槽位召回", qc3["gate_pass"], "orderNo 抽取与上下文补全"),
        ("QC07 幻觉率", qc7["gate_pass"], "禁用词与金额越界"),
        ("QC06 引用可解析", (qc6["resolvable_rate"] or 0) >= 0.85, "引用是否指向存在的条款"),
    ]
    lines.append("## 结论")
    lines.append("")
    for name, passed, focus in gates:
        lines.append(f"- {name}：{_verdict(passed)}（关注点：{focus}）")
    buckets = report["qc08_confidence"]["buckets"]
    low = buckets.get("lt_0.60", {}).get("accuracy")
    high = buckets.get("ge_0.85", {}).get("accuracy")
    if low is not None and high is not None:
        lines.append(f"- QC08 置信度分层：低置信区间准确率 {_pct(low)}、高置信区间 {_pct(high)}，"
                     f"{'单调（置信度有区分度）' if low <= high else '不单调（置信度缺乏区分度）'}")
    lines.append("- 本报告只做测量。修复项应在独立的 dev 集上验证，"
                 "直接按 holdout 误判调规则会让 holdout 失去留出集意义。")
    lines.append("")

    lines.append("## QC02 混淆矩阵（行=金标，列=预测）")
    lines.append("")
    header = "| 金标 \\ 预测 | " + " | ".join(INTENTS) + " | HANDOFF |"
    lines.append(header)
    lines.append("| --- |" + " --- |" * (len(INTENTS) + 1))
    for gold in INTENTS:
        row = qc2["confusion_matrix"][gold]
        cells = " | ".join(str(row.get(pred, 0)) for pred in INTENTS)
        extra = row.get("HANDOFF", 0)
        lines.append(f"| {gold} | {cells} | {extra} |")
    lines.append("")

    if qc2["wrong_cases"]:
        lines.append("### QC02 误判用例")
        lines.append("")
        for case in qc2["wrong_cases"]:
            lines.append(f"- `{case['id']}` 金标 {case['gold']} → 预测 {case['pred']}：{case['message']}")
        lines.append("")

    if qc3["wrong_cases"]:
        lines.append("### QC03 槽位错例")
        lines.append("")
        for case in qc3["wrong_cases"]:
            lines.append(f"- `{case['id']}` 期望 {case['expected']} → 预测 {case['pred']}")
        lines.append("")

    if qc4["misses"]:
        lines.append("### QC04 检索未覆盖用例")
        lines.append("")
        for case in qc4["misses"]:
            lines.append(f"- `{case['id']}` 金标 {case['gold']} / top3 {case['top3'] or '无引用'}")
        lines.append("")

    lines.append("## QC08 置信度分层")
    lines.append("")
    lines.append("| 区间 | 样本数 | 准确率 | 转人工占比 |")
    lines.append("| --- | --- | --- | --- |")
    for name, bucket in report["qc08_confidence"]["buckets"].items():
        lines.append(f"| {name} | {bucket['count']} | {_pct(bucket['accuracy'])} | "
                     f"{_pct(bucket['handoff_ratio'])} |")
    lines.append("")

    extra = report["extra_checks"]
    lines.append("## 契约行为补充检查")
    lines.append("")
    lines.append(f"- 无单号且应追问的用例：{extra['expect_no_order_cases']}，"
                 f"回复中出现“订单号”追问：{extra['asked_order_no_cases']}")
    lines.append(f"- 查无此单（O9999）：{extra['not_found_cases']}，"
                 f"回复明确“没查到/核对”：{extra['not_found_handled_cases']}，"
                 f"其中需人工复核：{extra['not_found_need_review']}")
    lines.append(f"- 降级标记（degraded）：{extra['degraded_cases']}")
    lines.append("")

    qc12 = report["qc12_rerun"]
    lines.append("## QC12 同集重跑")
    lines.append("")
    lines.append("同日、同进程、同实例重复性检查；跨日与跨进程未验证。")
    lines.append("")
    lines.append(f"- 用例逐条比对变化：{qc12['changed_cases']} 条；准确率 {_pct(qc12['accuracy_first'])} → "
                 f"{_pct(qc12['accuracy_second'])}（差值 {qc12['delta_points']} 个百分点）")
    lines.append("")
    lines.append("## 未评项说明")
    lines.append("")
    lines.append(f"- QC05：{qc5['reason']}")
    lines.append(f"- QC06 语义部分：{qc6['note']}")
    lines.append(f"- QC09：{qc9['note']}")
    lines.append(f"- QC11 版本记录：见 `eval/eval_result.json` 的 `qc11_version`。")
    lines.append("")
    return "\n".join(lines)


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _verdict(passed: bool) -> str:
    return "达标" if passed else "未达标"


def main() -> int:
    parser = argparse.ArgumentParser(description="QC 指标离线评测")
    parser.add_argument("--dataset", default=str(ROOT / "eval" / "holdout_v1.jsonl"))
    parser.add_argument("--repeat", type=int, default=2, help="同集重跑次数（QC12 用）")
    parser.add_argument("--json", default=str(ROOT / "eval" / "eval_result.json"))
    parser.add_argument("--markdown", default=str(ROOT / "eval" / "report.md"))
    args = parser.parse_args()

    dataset = Path(args.dataset)
    cases = load_cases(dataset)
    if not cases:
        print("数据集为空", file=sys.stderr)
        return 1

    service = AgentService(make_settings(), DemoFakeTools())  # type: ignore[arg-type]
    runs = [run_once(service, cases) for _ in range(max(1, args.repeat))]
    first = runs[0]

    report = {
        "qc01_dataset": qc01_dataset(cases),
        "qc02_intent": qc02_intent(first),
        "qc03_slots": qc03_slots(first),
        "qc04_recall_at_3": qc04_recall_at_3(first),
        "qc05_draft": qc05_draft(first),
        "qc06_citation": qc06_citation(first),
        "qc07_hallucination": qc07_hallucination(first),
        "qc08_confidence": qc08_confidence(first),
        "qc09_cost": qc09_cost(),
        "qc10_latency": qc10_latency(first),
        "qc11_version": qc11_version(dataset),
        "qc12_rerun": qc12_rerun(first, runs[-1]) if len(runs) > 1 else {"comparable": False},
        "qc13_handoff": qc13_handoff(first),
        "extra_checks": extra_checks(first),
        "cases": first,
    }

    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.markdown).write_text(render_markdown(report), encoding="utf-8")

    print(render_markdown(report))
    print(f"\nJSON -> {args.json}")
    print(f"Markdown -> {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
