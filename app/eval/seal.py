"""AC24：把「可回归基线」封存成 reports/baseline_v0.json。

    python -m app.eval.seal

规则（《边界确认书 v1》§基线）：
- 任一 AC 未通过 / 缺失 → 拒绝生成，退出码 1；
- 封存内容包含 git sha、fixture 清单 hash、policy_version、prompt_version、
  模型五元组、数据集 hash 与逐条 AC 结果；
- 封存后再改任何受控输入，重跑必须仍然全绿，否则该基线作废。
"""
from __future__ import annotations

import argparse
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


def baseline_path(provider: str, prompt_version: str, out: str | None = None) -> Path:
    """scripted 写默认基线；换模型/换提示词一律另存，绝不覆盖 baseline_v0.json。"""
    if out:
        return (ROOT / out).resolve()
    if provider == "scripted":
        return OUT
    return OUT.with_name(f"baseline_v0_{provider}_{prompt_version}.json")


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
          llm: dict, dataset: str, provider: str, note: str | None = None) -> dict:
    assert_all_green(results)
    ac = {f"AC{i:02d}": results.get(f"AC{i:02d}", "missing") for i in range(1, AC_TOTAL + 1)}
    ac["AC24"] = "self"
    if note is None:
        note = (
            "任一 AC 转红即阻断；本基线只覆盖 synthetic 数据集与 scripted provider"
            if provider == "scripted"
            else f"任一 AC 转红即阻断；AC 结果来自离线用例，provider={provider} 仅用于真实模型抽查"
        )
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
        "note": note,
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.eval.seal", description="封存回归基线（AC24）")
    p.add_argument("--provider", default="scripted", choices=["scripted", "openai_compat"],
                   help="封存哪套模型配置（默认 scripted）")
    p.add_argument("--model", default=None, help="模型名；缺省 scripted-v1 或 .env 里的 AFTERSALE_LLM_MODEL")
    p.add_argument("--out", default=None, help="输出路径（相对仓库根）；缺省按 provider/prompt_version 命名")
    p.add_argument("--token-budget", type=int, default=None,
                   help="缺省 scripted=4000，真实模型=6000（与 CLI 默认一致）")
    p.add_argument("--timeout-ms", type=int, default=None,
                   help="缺省 scripted=1500，真实模型=30000（与 CLI 默认一致）")
    return p


def _resolve_model(provider: str, model: str | None) -> str:
    if model:
        return model
    if provider == "scripted":
        return "scripted-v1"
    from app.llm.settings import resolve

    try:
        return resolve().model
    except ValueError as exc:
        raise SealError(f"provider={provider} 需要模型名：--model 或 .env（{exc}）") from exc


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provider = args.provider
    results = run_tests()
    try:
        model = _resolve_model(provider, args.model)
        fixture_hash, fixtures = manifest_hash(ROOT / "fixtures")
        from app.cli import default_policy
        from app.llm.prompts import prompt_version
        pv = prompt_version()
        path = baseline_path(provider, pv, args.out)
        if provider != "scripted" and path == OUT:
            raise SealError("换模型不得覆盖 reports/baseline_v0.json，请去掉 --out 或另指定文件名")
        payload = build(
            results,
            fixture_hash=fixture_hash,
            fixtures=fixtures,
            kb_hash=_sha(ROOT / "data" / "kb" / "qa_40.jsonl"),
            query_hash=_sha(ROOT / "data" / "eval" / "queries_60.jsonl"),
            policy_version=default_policy().version,
            prompt_version=pv,
            llm={
                "provider": provider,
                "model": model,
                "prompt_version": pv,
                "token_budget": args.token_budget if args.token_budget is not None
                else (4000 if provider == "scripted" else 6000),
                "timeout_ms": args.timeout_ms if args.timeout_ms is not None
                else (1500 if provider == "scripted" else 30000),
            },
            dataset="synthetic",
            provider=provider,
        )
    except SealError as exc:
        print(f"SEAL FAILED: {exc}", file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = sum(1 for v in payload["ac_results"].values() if v in ("passed", "self"))
    try:
        shown = path.relative_to(ROOT).as_posix()
    except ValueError:
        shown = str(path)
    print(f"sealed {shown}  provider={provider}/{model}  ac={n}/{AC_TOTAL}  git={payload['git_sha'][:8]}  fixtures={len(fixtures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
