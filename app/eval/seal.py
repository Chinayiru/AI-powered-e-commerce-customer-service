"""AC24：把「可回归基线」封存成 reports/baseline_v0.json。

    python -m app.eval.seal

规则（《边界确认书 v1》§基线）：
- 任一 AC 未通过 / 缺失 → 拒绝生成，退出码 1；
- 封存内容包含 git sha、fixture 清单 hash、policy_version、prompt_version、
  模型五元组、数据集 hash 与逐条 AC 结果；
- 封存后再改任何受控输入，重跑必须仍然全绿，否则该基线作废。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "baseline_v0.json"
AC_TOTAL = 26
SELF_AC = 24  # 封存动作本身，由本脚本自证，不来自 pytest


class SealError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_hash(root: Path) -> tuple[str, list[dict]]:
    entries = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        entries.append({"path": p.relative_to(root).as_posix(), "sha256": _sha(p)})
    blob = "".join(f"{e['path']}:{e['sha256']}\n" for e in entries).encode()
    return hashlib.sha256(blob).hexdigest()[:16], entries


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "no-git"


def run_tests() -> dict[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-v", "--tb=no", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    results: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        m = re.search(r"::test_ac(\d{2})_\w+.*?\b(PASSED|FAILED|ERROR)\b", line)
        if m:
            results[f"AC{m.group(1)}"] = m.group(2).lower()
    return results


def assert_all_green(results: dict[str, str]) -> None:
    bad = [f"AC{i:02d}" for i in range(1, AC_TOTAL + 1)
           if i != SELF_AC and results.get(f"AC{i:02d}") != "passed"]
    if bad:
        raise SealError(f"拒绝封存，未通过或缺失：{', '.join(bad)}")


def build(results: dict[str, str], *, fixture_hash: str, fixtures: list[dict],
          kb_hash: str, query_hash: str, policy_version: str, prompt_version: str,
          llm: dict, dataset: str, provider: str) -> dict:
    assert_all_green(results)
    ac = {f"AC{i:02d}": results.get(f"AC{i:02d}", "missing") for i in range(1, AC_TOTAL + 1)}
    ac["AC24"] = "self"
    return {
        "baseline": "v0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "fixture_manifest_hash": fixture_hash,
        "fixture_count": len(fixtures),
        "kb_hash": kb_hash,
        "query_hash": query_hash,
        "policy_version": policy_version,
        "prompt_version": prompt_version,
        "llm": llm,
        "dataset": dataset,
        "provider": provider,
        "ac_results": ac,
        "note": "任一 AC 转红即阻断；本基线只覆盖 synthetic 数据集与 scripted provider",
    }


def main() -> int:
    results = run_tests()
    try:
        fixture_hash, fixtures = manifest_hash(ROOT / "fixtures")
        from app.cli import default_policy
        from app.llm.prompts import prompt_version
        payload = build(
            results,
            fixture_hash=fixture_hash,
            fixtures=fixtures,
            kb_hash=_sha(ROOT / "data" / "kb" / "qa_40.jsonl"),
            query_hash=_sha(ROOT / "data" / "eval" / "queries_60.jsonl"),
            policy_version=default_policy().version,
            prompt_version=prompt_version(),
            llm={
                "provider": "scripted",
                "model": "scripted-v1",
                "prompt_version": prompt_version(),
                "token_budget": 4000,
                "timeout_ms": 1500,
            },
            dataset="synthetic",
            provider="scripted",
        )
    except SealError as exc:
        print(f"SEAL FAILED: {exc}", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = sum(1 for v in payload["ac_results"].values() if v in ("passed", "self"))
    print(f"sealed {OUT.relative_to(ROOT)}  ac={n}/{AC_TOTAL}  git={payload['git_sha'][:8]}  fixtures={len(fixtures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
