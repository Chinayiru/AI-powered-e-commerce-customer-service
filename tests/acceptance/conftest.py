from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.adapters.base import FixtureAdapter
from app.cli import FIXTURES, build_ticket, default_policy, resolve_fixture
from app.contracts.models import LLMConfig
from app.core.pipeline import RunResult, run
from app.llm.prompts import prompt_version
from app.llm.scripted import ScriptedProvider

NOW = datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc)

EVIDENCE = Path(__file__).resolve().parents[2] / "reports" / "evidence-index.md"

# nodeid -> {"ac": "AC06", "run_ids": [...], "outcome": "passed", "command": ...}
_RECORDS: dict[str, dict] = {}
_CURRENT: dict[str, str] = {}


def _ac_of(nodeid: str) -> str | None:
    m = re.search(r"test_ac(\d{2})_", nodeid)
    return f"AC{m.group(1)}" if m else None


def note_run(run_id: str) -> None:
    """run_fixture 每跑一单就把 run_id 记到当前用例名下（AC 证据索引用）。"""
    rec = _RECORDS.setdefault(_CURRENT.get("nodeid", ""), {"run_ids": []})
    if run_id and run_id not in rec["run_ids"]:
        rec["run_ids"].append(run_id)


def run_fixture(
    name: str,
    *,
    confirm: str | None = None,
    provider=None,
    llm: LLMConfig | None = None,
    policy=None,
) -> tuple[RunResult, FixtureAdapter]:
    platform, fixture, path = resolve_fixture(name)
    adapter = FixtureAdapter(FIXTURES, platform)
    result = run(
        build_ticket(fixture, path),
        adapter=adapter,
        provider=provider or ScriptedProvider(),
        policy=policy or default_policy(),
        llm=llm or LLMConfig(model="scripted-v1", prompt_version=prompt_version()),
        now=NOW,
        confirm=confirm,
    )
    note_run(result.out.run_id)
    return result, adapter


@pytest.fixture()
def r():
    return run_fixture


def pytest_runtest_setup(item):
    _CURRENT["nodeid"] = item.nodeid


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    rec = _RECORDS.setdefault(item.nodeid, {"run_ids": []})
    rec["outcome"] = report.outcome
    rec["command"] = f"pytest -k test_ac{(_ac_of(item.nodeid) or 'AC??')[2:]}"


def pytest_sessionfinish(session, exitstatus):
    """AC01–AC26 逐条登记：编号 | run_id | 命令 | 时间 | 结果。"""
    rows: dict[str, list[tuple[str, str, str]]] = {}
    for nodeid, rec in _RECORDS.items():
        ac = _ac_of(nodeid)
        if not ac:
            continue
        run_id = ",".join(rec.get("run_ids") or []) or "—（契约级，不产生 run）"
        file_part = nodeid.split("::")[0]
        cmd = f"python -m pytest {file_part} -k {ac.lower()}"
        rows.setdefault(ac, []).append((run_id, cmd, rec.get("outcome", "not-run")))

    lines = [
        "# 证据索引（自动生成，勿手改）",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        "",
        "| AC | run_id | 命令 | 结果 |",
        "| --- | --- | --- | --- |",
    ]
    for ac in sorted(rows):
        for run_id, cmd, outcome in rows[ac]:
            lines.append(f"| {ac} | `{run_id}` | `{cmd}` | {outcome} |")
    lines.append("")
    lines.append("> 没有 run 的契约级断言由 scripted 之外的确定性对象直接验证，不冒充端到端证据。")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines) + "\n", encoding="utf-8")
