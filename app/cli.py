"""命令行入口：一条命令 = 一次可复现的 run。

    python -m app.cli run --fixture tb_1001 --confirm human:demo1
    python -m app.cli replay --run-id run_xxxxxxxxxxxx
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.base import FixtureAdapter
from app.contracts.models import DomainError, LLMConfig, QaDoc, RefundPolicy, TicketIn
from app.core.pipeline import run
from app.core.redact import audit_view
from app.llm.factory import make_provider
from app.llm.prompts import prompt_version

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
KB_PATH = ROOT / "data" / "kb" / "qa_40.jsonl"
RUNS = Path(os.environ.get("RUNS_PATH", ROOT / "reports" / "runs.jsonl"))


def load_kb() -> tuple[object, dict[str, str]]:
    """知识库：检索器 + qa_id→answer 映射（后者用于引用逐字校验）。"""
    from app.retrieval.keyword import KeywordRetriever

    docs = [
        QaDoc.model_validate(json.loads(line))
        for line in KB_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retriever = KeywordRetriever()
    retriever.index(docs)
    return retriever, {d.qa_id: d.answer for d in docs}


def kb_context(retriever, answers: dict[str, str], text: str, k: int = 3) -> tuple[list[str], dict[str, str]]:
    hits = retriever.search(text, k=k)
    lines = [f"{h.qa_id}｜{answers.get(h.qa_id, '')}" for h in hits if answers.get(h.qa_id)]
    quotes = {h.qa_id: answers[h.qa_id] for h in hits if answers.get(h.qa_id)}
    return lines, quotes



def resolve_fixture(name: str) -> tuple[str, str, Path]:
    """支持短名（tb_1001）与全名（tb_1001_unship_cents）。"""
    for platform in ("taobao", "douyin"):
        for path in sorted((FIXTURES / platform).glob("*.json")):
            if path.stem == name or path.stem.startswith(name):
                return platform, path.stem, path
    raise SystemExit(f"fixture not found: {name}")


def default_policy() -> RefundPolicy:
    return RefundPolicy(
        version="2026-11-09.1",
        auto_limit_cents=5000,
        human_floor_cents=5000,
        window_days=7,
        per_category={"digital": {"auto_limit_cents": 0, "human_floor_cents": 0, "excluded": True}},
    )


def build_ticket(fixture: str, path: Path) -> TicketIn:
    from app.llm.scripted import SCRIPTED

    ref = SCRIPTED  # noqa: F841 - 仅为保持 import 显式
    data = json.loads(path.read_text(encoding="utf-8"))
    order = data["order"]
    order_ref = order.get("tid") or order.get("order_id")
    text = {
        "tb_1001_unship_cents": "还没发货，我不想要了，申请退款。",
        "tb_1002_multi_pkg": "收到一个包裹，另一个还没到，我要退款。",
        "tb_1003_over_window": "东西不好用，我要退款。",
        "tb_1004_partial": "少发了一个杯子，退我 20 元。",
        "tb_1005_threat": "再不退款我就去 12315 投诉，还要曝光你们。",
        "tb_1006_digital": "会员卡不想要了，退款。",
        "dy_2001_delivered_yuan": "耳机有杂音，申请仅退款。",
        "dy_2002_missing_state": "我的订单一直没动静，要退款。",
        "dy_2003_dup_events": "数据线坏了，退款。",
        "dy_2004_return": "衣服尺码不对，申请退货退款。",
    }.get(fixture, "申请售后。")
    return TicketIn(
        ticket_id=f"T{order_ref}",
        user_id="u_demo",
        text=text,
        order_ref=order_ref,
        created_at=datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc),
    )


def cmd_run(args: argparse.Namespace) -> int:
    platform, fixture, path = resolve_fixture(args.fixture)
    adapter = FixtureAdapter(FIXTURES, platform)
    if args.api_key:
        # 明文密钥会留在 shell 历史、进程表和 CI 日志里；只提示，不阻断（本地排障仍可用）
        print(
            "警告：--api-key 会进 shell 历史与进程列表，建议改用 .env / AFTERSALE_LLM_API_KEY",
            file=sys.stderr,
        )
    provider = make_provider(
        args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_ms=args.timeout_ms,
        max_tokens=args.max_tokens,
        delay_ms=args.delay_ms,
    )
    llm = LLMConfig(
        provider=provider.name,
        model=provider.model,
        prompt_version=prompt_version(),
        token_budget=args.budget,
        timeout_ms=args.timeout_ms,
    )
    ticket = build_ticket(fixture, path)
    kb_hits: list[str] = []
    kb_quotes: dict[str, str] = {}
    if not args.no_kb and KB_PATH.is_file():
        retriever, answers = load_kb()
        kb_hits, kb_quotes = kb_context(retriever, answers, ticket.text)
    result = run(
        ticket,
        adapter=adapter,
        provider=provider,
        policy=default_policy(),
        llm=llm,
        now=datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc),
        confirm=args.confirm,
        kb_quotes=kb_quotes,
        kb_hits=kb_hits,
    )
    out = result.out
    record = {
        "run_id": out.run_id,
        "fixture": fixture,
        "confirm": args.confirm,
        "llm": llm.model_dump(),
        "prompt_version": out.prompt_version,
        "policy_version": out.policy_version,
        "kb_hits": [line.split("｜", 1)[0] for line in kb_hits],
        "out": out.model_dump(mode="json"),
        "trace": result.trace,
    }
    record = audit_view(record)  # 落盘前的唯一出口：PII 只能以脱敏形态进日志（AC25）
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(f"run_id       {out.run_id}")
        print(f"fixture      {fixture}")
        print(f"provider     {llm.provider} / {out.model}")
        print(f"intent       {out.intent.value} / {out.aftersales_type.value if out.aftersales_type else '-'}")
        print(f"verdict      {out.verdict.value}   gate={out.send_gate.value}   stop={out.stop_reason.value}")
        print(f"reasons      {[r.value for r in out.reason_codes]}")
        print(f"case         {out.case.status.value if out.case else '-'}  amount={out.case.amount_cents if out.case else 0}")
        print(f"draft        {out.draft.text}")
        print(f"usage        in={out.usage.input_tokens} out={out.usage.output_tokens} estimated={out.usage.estimated}")
        print(f"latency      {out.latency_ms}ms")
    return 0 if out.stop_reason.value == "finalized" else 2


def cmd_replay(args: argparse.Namespace) -> int:
    if not RUNS.exists():
        raise SystemExit("no runs recorded")
    rows = [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines() if line.strip()]
    hit = next((r for r in rows if r["run_id"] == args.run_id), None)
    if hit is None:
        raise SystemExit(f"run not found: {args.run_id}")

    platform, fixture, path = resolve_fixture(hit["fixture"])
    policy = default_policy()
    policy.version = hit["policy_version"]  # 回放用 run 里记录的版本，不追最新
    llmconf = hit.get("llm") or {"provider": "scripted", "model": "scripted-v1"}
    if llmconf.get("provider") != "scripted":
        print(f"note: 回放真实模型 provider={llmconf['provider']}；模型非确定性，drift 属正常", file=sys.stderr)
    provider = make_provider(
        llmconf.get("provider", "scripted"),
        model=llmconf.get("model"),
        timeout_ms=int(llmconf.get("timeout_ms", 30000)),
    )
    llm = LLMConfig(
        provider=llmconf.get("provider", "scripted"),
        model=provider.model,
        prompt_version=hit["prompt_version"],
        token_budget=int(llmconf.get("token_budget", 6000)),
        timeout_ms=int(llmconf.get("timeout_ms", 30000)),
    )
    retriever, answers = load_kb()
    ticket = build_ticket(fixture, path)
    kb_hits, kb_quotes = kb_context(retriever, answers, ticket.text)
    result = run(
        ticket,
        adapter=FixtureAdapter(FIXTURES, platform),
        provider=provider,
        policy=policy,
        llm=llm,
        now=datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc),
        confirm=hit["confirm"],
        kb_quotes=kb_quotes,
        kb_hits=kb_hits,
    )
    now_out = audit_view(result.out.model_dump(mode="json"))
    old_out = hit["out"]
    drift = [
        k
        for k in now_out
        if k not in {"run_id", "latency_ms", "tool_calls"} and now_out[k] != old_out.get(k)
    ]
    print(f"replayed {hit['run_id']} with policy_version={policy.version} prompt_version={hit['prompt_version']}")
    print("drift:", drift or "none")
    return 0 if not drift else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="跑一张工单")
    p_run.add_argument("--fixture", required=True)
    p_run.add_argument(
        "--provider",
        choices=("scripted", "openai_compat", "auto"),
        default=None,
        help="默认按 .env/环境变量 AFTERSALE_LLM_PROVIDER；auto=有配置用真实模型",
    )
    p_run.add_argument("--model", default=None, help="默认取 .env / AFTERSALE_LLM_MODEL")
    p_run.add_argument("--base-url", default=None, help="OpenAI 兼容基址，如 https://host/v1")
    p_run.add_argument("--api-key", default=None, help="不推荐明文传；优先用 .env / AFTERSALE_LLM_API_KEY")
    p_run.add_argument("--max-tokens", type=int, default=1024)
    p_run.add_argument("--no-kb", action="store_true", help="不把知识库检索结果注入 prompt")
    p_run.add_argument("--confirm", default=None, help="human:<id>，模拟人工确认")
    p_run.add_argument("--budget", type=int, default=6000)
    p_run.add_argument("--timeout-ms", type=int, default=30000)
    p_run.add_argument("--delay-ms", type=int, default=0, help="给 scripted provider 加延迟，用测超时")
    p_run.add_argument("--json", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_replay = sub.add_parser("replay", help="按旧版本回放")
    p_replay.add_argument("--run-id", required=True)
    p_replay.set_defaults(func=cmd_replay)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DomainError as exc:
        print(f"error {exc.code.value}: {exc.message}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
