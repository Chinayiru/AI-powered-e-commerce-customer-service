"""意图开发集与评测的门禁测试。

三件事必须钉住：
1. 数据自洽（标签合法、refund 必须有子类型、case_id 不重复）；
2. 数据独立（与检索评测集 queries_60、与 fixtures 工单文本、开发集与留出集之间不重样）；
3. 指标不倒退（开发集门禁、留出集下限、规则必须明显强于单关键词基线）。

第 3 条里的数字来自 THRESHOLDS/HOLDOUT_FLOOR 常量，报告与测试共用，不会"测试绿、报告红"。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.cli import build_ticket, resolve_fixture
from app.contracts.models import AftersalesType, Intent
from app.eval.intent import (
    DEV_PATH,
    HOLDOUT2_PATH,
    HOLDOUT_PATH,
    HOLDOUT_FLOOR,
    THRESHOLDS,
    build_report,
    evaluate,
    gate,
    load_dev,
    naive_predict,
)
from app.intent.rules import classify

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dev_cases():
    return load_dev(DEV_PATH)


@pytest.fixture(scope="module")
def holdout_cases():
    return load_dev(HOLDOUT_PATH), load_dev(HOLDOUT2_PATH)


def test_dev_set_is_balanced_and_covers_all_classes(dev_cases) -> None:
    assert len(dev_cases) >= 80
    counts = Counter(c.intent for c in dev_cases)
    assert set(counts) == set(Intent)
    assert all(counts[i] >= 14 for i in Intent), counts
    types = Counter(c.aftersales_type for c in dev_cases if c.intent is Intent.refund)
    assert types[AftersalesType.refund_only] >= 15
    assert types[AftersalesType.return_refund] >= 10
    assert sum(1 for c in dev_cases if c.hard) >= 15


def test_holdouts_are_valid_and_never_mix_ids(dev_cases, holdout_cases) -> None:
    h1, h2 = holdout_cases
    dev_ids = {c.case_id for c in dev_cases}
    for cases in (h1, h2):
        assert {c.case_id for c in cases}.isdisjoint(dev_ids)
        assert len({c.case_id for c in cases}) == len(cases)


def test_no_text_leaks_between_dev_and_holdouts(dev_cases, holdout_cases) -> None:
    dev_texts = {c.text for c in dev_cases}
    for cases in holdout_cases:
        assert dev_texts.isdisjoint({c.text for c in cases})


def test_intent_sets_do_not_reuse_retrieval_queries(dev_cases, holdout_cases) -> None:
    queries = {
        json.loads(line)["query"]
        for line in (ROOT / "data" / "eval" / "queries_60.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for cases in (dev_cases, *holdout_cases):
        assert {c.text for c in cases}.isdisjoint(queries)


def test_intent_sets_do_not_reuse_fixture_tickets(dev_cases, holdout_cases) -> None:
    fixture_texts = set()
    for path in sorted((ROOT / "fixtures").rglob("*.json")):
        platform, fixture, resolved = resolve_fixture(path.stem)
        assert platform and resolved
        fixture_texts.add(build_ticket(fixture, resolved).text)
    for cases in (dev_cases, *holdout_cases):
        assert {c.text for c in cases}.isdisjoint(fixture_texts)


def test_dev_gate_passes(dev_cases) -> None:
    metrics = evaluate(classify, dev_cases)
    assert gate(metrics) == {}, gate(metrics)
    assert metrics.accuracy >= THRESHOLDS["accuracy"]
    assert metrics.macro_f1 >= THRESHOLDS["macro_f1"]


def test_holdouts_meet_pre_registered_floor(holdout_cases) -> None:
    for cases in holdout_cases:
        metrics = evaluate(classify, cases)
        assert metrics.accuracy >= HOLDOUT_FLOOR["accuracy"], metrics.errors
        assert metrics.macro_f1 >= HOLDOUT_FLOOR["macro_f1"], metrics.errors


def test_rules_beat_naive_baseline(dev_cases) -> None:
    rules = evaluate(classify, dev_cases)
    naive = evaluate(naive_predict, dev_cases)
    assert rules.accuracy - naive.accuracy >= 0.15
    assert rules.macro_f1 - naive.macro_f1 >= 0.15
    assert rules.type_accuracy >= naive.type_accuracy


def test_report_is_self_consistent(dev_cases, holdout_cases) -> None:
    rules = evaluate(classify, dev_cases)
    naive = evaluate(naive_predict, dev_cases)
    h1, h2 = holdout_cases
    report = build_report(
        rules,
        naive,
        [
            (HOLDOUT_PATH, evaluate(classify, h1), evaluate(naive_predict, h1)),
            (HOLDOUT2_PATH, evaluate(classify, h2), evaluate(naive_predict, h2)),
        ],
    )
    assert report["report"] == "intent_dev_v0"
    assert len(report["dev_sha256"]) == 16
    assert report["gate"] == "passed"
    assert report["rule"]["accuracy"] == round(rules.accuracy, 4)
    assert len(report["holdouts"]) == 2
    assert all(isinstance(h["case_count"], int) and h["case_count"] > 0 for h in report["holdouts"])
