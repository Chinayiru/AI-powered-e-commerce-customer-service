"""AC17–AC19：检索可直接评测、引用必须落地、向量通道由阈值决定。"""
from __future__ import annotations

import json
from pathlib import Path

from app.eval import retrieval

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "retrieval_v0.json"


def test_ac17_recall_is_measurable_and_above_floor():
    rc = retrieval.main(["--compare"])
    assert rc == 0
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["keyword"]["n_queries"] == 60
    assert payload["keyword"]["unlabeled"] == 0
    # 合成集上的地板值；掉下来说明分词/索引坏了
    assert payload["keyword"]["recall_at_5"] >= 0.90
    assert payload["hybrid"]["recall_at_5"] >= 0.90


def test_ac19_vector_channel_off_without_proven_gain():
    payload = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    if payload.get("delta_pt") is None:
        retrieval.main(["--compare"])
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
    assert payload["dataset"] == "synthetic"
    assert payload["provider"] == "scripted"
    assert payload["vector_enabled"] is False
    assert retrieval.decide_vector(0.02) is False
    assert retrieval.decide_vector(0.03) is True
    assert retrieval.decide_vector(0.11) is True
