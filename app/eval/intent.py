"""意图开发集评测：独立于检索评测集（data/eval/queries_60.jsonl）的一套标注。

为什么要独立：检索集回答"知识找得准不准"，开发集回答"工单读得对不对"。两套混用
会互相污染——用检索集的查询调意图规则，检索分数就会虚高；反之亦然。

产物（`python -m app.eval.intent`）：
    reports/intent_dev_v0.json   规则 v1 与朴素基线 v0 的对比、混淆矩阵、错误清单

门禁（THRESHOLDS）与 tests/test_intent_dev.py 共用同一组常量，避免"测试绿、报告红"
或反过来。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.contracts.models import AftersalesType, Intent
from app.intent.rules import RuleResult, classify

ROOT = Path(__file__).resolve().parents[2]
DEV_PATH = ROOT / "data" / "eval" / "intent_dev.jsonl"
HOLDOUT_PATH = ROOT / "data" / "eval" / "intent_holdout.jsonl"
HOLDOUT2_PATH = ROOT / "data" / "eval" / "intent_holdout2.jsonl"
REPORT_PATH = ROOT / "reports" / "intent_dev_v0.json"

THRESHOLDS: dict[str, float] = {
    "accuracy": 0.85,
    "macro_f1": 0.78,
    "refund_recall": 0.88,
    "refund_only_recall": 0.80,
    "return_refund_recall": 0.75,
}

# 留出集下限在看结果之前就定好，避免"跑完再改门槛"。
HOLDOUT_FLOOR: dict[str, float] = {"accuracy": 0.80, "macro_f1": 0.75}


@dataclass(frozen=True)
class Case:
    case_id: str
    text: str
    intent: Intent
    aftersales_type: AftersalesType | None
    hard: bool
    note: str


@dataclass(frozen=True)
class Metrics:
    accuracy: float
    macro_f1: float
    per_class: dict[str, dict[str, float]]
    confusion: dict[str, dict[str, int]]
    type_accuracy: float
    type_per_class: dict[str, dict[str, float]]
    errors: tuple[dict[str, object], ...]
    total: int

    def as_dict(self) -> dict[str, object]:
        return {
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {
                k: {m: round(v, 4) for m, v in vals.items()} for k, vals in self.per_class.items()
            },
            "confusion": self.confusion,
            "type_accuracy": round(self.type_accuracy, 4),
            "type_per_class": {
                k: {m: round(v, 4) for m, v in vals.items()} for k, vals in self.type_per_class.items()
            },
            "errors": list(self.errors),
            "total": self.total,
        }


def load_dev(path: Path = DEV_PATH) -> list[Case]:
    """读开发集并做"标注自洽"校验：字段缺失、标签越界、refund 缺子类型都要报出来。"""
    cases: list[Case] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:  # 数据坏了要指名道姓，不要静默跳过
            raise ValueError(f"{path}:{lineno} 不是合法 JSON：{exc}") from exc
        for field in ("case_id", "text", "intent", "aftersales_type", "hard", "note"):
            if field not in raw:
                raise ValueError(f"{path}:{lineno} 缺字段 {field}")
        if raw["case_id"] in seen:
            raise ValueError(f"{path}:{lineno} case_id 重复：{raw['case_id']}")
        seen.add(raw["case_id"])
        if not str(raw["text"]).strip():
            raise ValueError(f"{path}:{lineno} text 为空")
        intent = Intent(raw["intent"])
        aftersales = None if raw["aftersales_type"] is None else AftersalesType(raw["aftersales_type"])
        if intent is Intent.refund and aftersales is None:
            raise ValueError(f"{path}:{lineno} 退款样本必须有 aftersales_type")
        if intent is not Intent.refund and aftersales is not None:
            raise ValueError(f"{path}:{lineno} 非退款样本的 aftersales_type 必须为 null")
        cases.append(
            Case(raw["case_id"], str(raw["text"]), intent, aftersales, bool(raw["hard"]), str(raw["note"]))
        )
    if not cases:
        raise ValueError(f"{path} 为空")
    return cases


# ---------------------------------------------------------------------------
# 基线 v0：单关键词优先级（改造前的"规则"），留作对照，证明改进不是自说自话
# ---------------------------------------------------------------------------
NAIVE_ORDER: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (Intent.address_change, ("地址", "收货人", "收件人")),
    (Intent.shipping_urge, ("物流", "发货", "快递", "单号")),
    (Intent.refund, ("退款", "退货", "退钱")),
)


def naive_predict(text: str) -> RuleResult:
    """朴素基线：命中哪个关键词就算哪个，不看否定、不看问句、不看子类型。"""
    for intent, words in NAIVE_ORDER:
        if any(w in text for w in words):
            aftersales = (
                AftersalesType.return_refund if intent is Intent.refund and "退货" in text
                else AftersalesType.refund_only if intent is Intent.refund
                else None
            )
            return RuleResult(intent, aftersales, 0.6, tuple(w for w in words if w in text), False)
    return RuleResult(Intent.other, None, 0.3, (), True)


def _rate(hit: int, total: int) -> float:
    return (hit / total) if total else 0.0


def evaluate(predict, cases: list[Case]) -> Metrics:
    intents = [i.value for i in Intent]
    confusion: dict[str, dict[str, int]] = {g: {p: 0 for p in intents} for g in intents}
    type_confusion: dict[str, dict[str, int]] = {
        t.value: {p: 0 for p in (AftersalesType.refund_only.value, AftersalesType.return_refund.value)}
        for t in AftersalesType
    }
    type_total = 0
    type_hit = 0
    errors: list[dict[str, object]] = []
    for case in cases:
        pred = predict(case.text)
        confusion[case.intent.value][pred.intent.value] += 1
        if pred.intent is not case.intent:
            errors.append(
                {
                    "case_id": case.case_id,
                    "text": case.text,
                    "gold": case.intent.value,
                    "pred": pred.intent.value,
                    "confidence": pred.confidence,
                    "cues": list(pred.cues),
                }
            )
        if case.intent is Intent.refund and pred.intent is Intent.refund:
            type_total += 1
            got = pred.aftersales_type
            type_confusion[case.aftersales_type.value][got.value if got else "none"] += 1
            if got is case.aftersales_type:
                type_hit += 1
            else:
                errors.append(
                    {
                        "case_id": case.case_id,
                        "text": case.text,
                        "gold": f"{case.intent.value}/{case.aftersales_type.value}",
                        "pred": f"{pred.intent.value}/{got.value if got else 'none'}",
                        "confidence": pred.confidence,
                        "cues": list(pred.cues),
                    }
                )

    per_class: dict[str, dict[str, float]] = {}
    f1s: list[float] = []
    for g in intents:
        tp = confusion[g][g]
        support = sum(confusion[g].values())
        predicted = sum(confusion[x][g] for x in intents)
        precision = _rate(tp, predicted)
        recall = _rate(tp, support)
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        per_class[g] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
        f1s.append(f1)

    type_per_class: dict[str, dict[str, float]] = {}
    for t in AftersalesType:
        row = type_confusion[t.value]
        tp = row[t.value]
        predicted = sum(row.values())
        gold_support = sum(1 for c in cases if c.intent is Intent.refund and c.aftersales_type is t)
        precision = _rate(tp, predicted)
        recall = _rate(tp, gold_support)
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        type_per_class[t.value] = {"precision": precision, "recall": recall, "f1": f1, "support": gold_support}

    correct = sum(confusion[g][g] for g in intents)
    return Metrics(
        accuracy=_rate(correct, len(cases)),
        macro_f1=sum(f1s) / len(f1s),
        per_class=per_class,
        confusion=confusion,
        type_accuracy=_rate(type_hit, type_total),
        type_per_class=type_per_class,
        errors=tuple(errors[:25]),
        total=len(cases),
    )


def gate(metrics: Metrics) -> dict[str, float]:
    """返回"未达标项"；空字典表示全过。"""
    failed: dict[str, float] = {}
    if metrics.accuracy < THRESHOLDS["accuracy"]:
        failed["accuracy"] = metrics.accuracy
    if metrics.macro_f1 < THRESHOLDS["macro_f1"]:
        failed["macro_f1"] = metrics.macro_f1
    if metrics.per_class[Intent.refund.value]["recall"] < THRESHOLDS["refund_recall"]:
        failed["refund_recall"] = metrics.per_class[Intent.refund.value]["recall"]
    if metrics.type_per_class[AftersalesType.refund_only.value]["recall"] < THRESHOLDS["refund_only_recall"]:
        failed["refund_only_recall"] = metrics.type_per_class[AftersalesType.refund_only.value]["recall"]
    if metrics.type_per_class[AftersalesType.return_refund.value]["recall"] < THRESHOLDS["return_refund_recall"]:
        failed["return_refund_recall"] = metrics.type_per_class[AftersalesType.return_refund.value]["recall"]
    return failed


def dev_sha256(path: Path = DEV_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()[:8]
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _holdout_block(path: Path, m: Metrics, naive_m: Metrics | None) -> dict[str, object]:
    failed = {k: v for k, v in HOLDOUT_FLOOR.items() if getattr(m, k) < v}
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": dev_sha256(path),
        "case_count": m.total,
        "floor": dict(HOLDOUT_FLOOR),
        "gate": "passed" if not failed else "failed",
        "failed": failed,
        "rule": m.as_dict(),
        "baseline_naive": naive_m.as_dict() if naive_m else None,
        "note": "留出集只用于最终测量，不参与调参；跑完这一遍就冻结",
    }


def build_report(
    rule_m: Metrics,
    naive_m: Metrics,
    holdouts: list[tuple[Path, Metrics, Metrics | None]] | None = None,
    *,
    dev_path: Path = DEV_PATH,
) -> dict[str, object]:
    failed = gate(rule_m)
    report: dict[str, object] = {
        "report": "intent_dev_v0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "dev_path": str(dev_path.relative_to(ROOT)),
        "dev_sha256": dev_sha256(dev_path),
        "case_count": rule_m.total,
        "thresholds": dict(THRESHOLDS),
        "gate": "passed" if not failed else "failed",
        "failed": failed,
        "rule": rule_m.as_dict(),
        "baseline_naive": naive_m.as_dict(),
        "improvement": {
            "accuracy": round(rule_m.accuracy - naive_m.accuracy, 4),
            "macro_f1": round(rule_m.macro_f1 - naive_m.macro_f1, 4),
            "type_accuracy": round(rule_m.type_accuracy - naive_m.type_accuracy, 4),
        },
        "note": "开发集独立于 data/eval/queries_60.jsonl；只用于调意图规则，不参与检索指标",
        "holdouts": [_holdout_block(p, m, n) for p, m, n in (holdouts or [])],
    }
    return report


def _print_table(m: Metrics, title: str) -> None:
    print(f"\n== {title} ==  accuracy={m.accuracy:.3f}  macroF1={m.macro_f1:.3f}  type_acc={m.type_accuracy:.3f}")
    for name, vals in m.per_class.items():
        print(f"  {name:<15} P={vals['precision']:.3f} R={vals['recall']:.3f} F1={vals['f1']:.3f} n={int(vals['support'])}")
    for name, vals in m.type_per_class.items():
        print(f"  type:{name:<12} P={vals['precision']:.3f} R={vals['recall']:.3f} F1={vals['f1']:.3f} n={int(vals['support'])}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m app.eval.intent", description="意图开发集评测")
    parser.add_argument("--dev", default=str(DEV_PATH), help="开发集路径")
    parser.add_argument(
        "--holdout",
        nargs="*",
        default=[str(HOLDOUT_PATH), str(HOLDOUT2_PATH)],
        help="留出集路径（可传多个）；传空则跳过",
    )
    parser.add_argument("--report", default=str(REPORT_PATH), help="报告输出路径；传空串则不写")
    parser.add_argument("--quiet", action="store_true", help="只输出错误清单")
    args = parser.parse_args(argv)

    dev_path = Path(args.dev)
    cases = load_dev(dev_path)
    rule_m = evaluate(classify, cases)
    naive_m = evaluate(naive_predict, cases)

    holdouts: list[tuple[Path, Metrics, Metrics]] = []
    for raw in args.holdout:
        hp = Path(raw)
        hold_cases = load_dev(hp)
        holdouts.append((hp, evaluate(classify, hold_cases), evaluate(naive_predict, hold_cases)))

    if not args.quiet:
        _print_table(naive_m, "baseline v0（单关键词）")
        _print_table(rule_m, "rules v1 · 开发集（调参用的）")
        for hp, m, _nm in holdouts:
            _print_table(m, f"rules v1 · 留出集 {hp.name}（未参与调参）")
        if rule_m.errors:
            print("\n-- 错误清单（规则 v1，开发集）--")
            for e in rule_m.errors:
                print(f"  {e['case_id']} gold={e['gold']} pred={e['pred']} conf={e['confidence']} | {e['text']}")
        for hp, m, _nm in holdouts:
            if not m.errors:
                continue
            print(f"\n-- 错误清单（规则 v1，留出集 {hp.name}）--")
            for e in m.errors:
                print(f"  {e['case_id']} gold={e['gold']} pred={e['pred']} conf={e['confidence']} | {e['text']}")

    failed = gate(rule_m)
    if failed:
        print("\n门禁未通过：" + ", ".join(f"{k}={v:.3f}" for k, v in failed.items()), file=sys.stderr)
    else:
        print(f"\n门禁通过：accuracy≥{THRESHOLDS['accuracy']}，macroF1≥{THRESHOLDS['macro_f1']}")

    for hp, m, _nm in holdouts:
        hold_failed = {k: v for k, v in HOLDOUT_FLOOR.items() if getattr(m, k) < v}
        if hold_failed:
            print(
                f"\n留出集 {hp.name} 低于预设下限：" + ", ".join(f"{k}={v:.3f}" for k, v in hold_failed.items()),
                file=sys.stderr,
            )
            failed.update({f"{hp.stem}.{k}": v for k, v in hold_failed.items()})
        else:
            print(
                f"留出集 {hp.name} 达标：accuracy={m.accuracy:.3f}≥{HOLDOUT_FLOOR['accuracy']}，"
                f"macroF1={m.macro_f1:.3f}≥{HOLDOUT_FLOOR['macro_f1']}"
            )

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                build_report(rule_m, naive_m, holdouts, dev_path=dev_path),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
