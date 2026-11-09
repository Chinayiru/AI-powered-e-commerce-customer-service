"""AC24：封存动作只在全绿时成立，且清单字段齐全。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval import seal

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "reports" / "baseline_v0.json"
REQUIRED = {
    "baseline", "created_at", "git_sha", "fixture_manifest_hash", "policy_version",
    "prompt_version", "llm", "dataset", "ac_results",
}


def _all_green() -> dict[str, str]:
    return {f"AC{i:02d}": "passed" for i in range(1, seal.AC_TOTAL + 1)}


def test_ac24_refuses_to_seal_with_a_red_ac():
    results = _all_green()
    results["AC09"] = "failed"
    with pytest.raises(seal.SealError):
        seal.build(results, fixture_hash="x", fixtures=[], kb_hash="x", query_hash="x",
                   policy_version="p", prompt_version="q", llm={}, dataset="synthetic", provider="scripted")


def test_ac24_refuses_when_an_ac_is_missing():
    results = _all_green()
    del results["AC17"]
    with pytest.raises(seal.SealError):
        seal.build(results, fixture_hash="x", fixtures=[], kb_hash="x", query_hash="x",
                   policy_version="p", prompt_version="q", llm={}, dataset="synthetic", provider="scripted")


def test_ac24_baseline_payload_is_complete():
    payload = seal.build(_all_green(), fixture_hash="abc", fixtures=[{"path": "a", "sha256": "b"}],
                         kb_hash="k", query_hash="q", policy_version="2026-11-09.1",
                         prompt_version="deadbeef",
                         llm={"provider": "scripted", "model": "scripted-v1"},
                         dataset="synthetic", provider="scripted")
    assert REQUIRED <= set(payload)
    assert payload["ac_results"]["AC24"] == "self"
    assert all(v == "passed" for k, v in payload["ac_results"].items() if k != "AC24")


def test_ac24_sealed_file_matches_contract_when_present():
    if not BASELINE.exists():
        pytest.skip("尚未执行 python -m app.eval.seal")
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert REQUIRED <= set(data)
    assert data["dataset"] == "synthetic"
    assert data["provider"] == "scripted"
