"""HTTP API：把 CLI 已有能力暴露给前端控制台。

原则：**不新增业务规则**。这里只做三件事——列 fixture、跑单/回放、读评测与基线；
所有判断仍然走 app.core.pipeline / app.policy，服务端不复制一份逻辑。

启动：
    python -m app.api.server                 # 127.0.0.1:8000
    uvicorn app.api.server:app --port 8000   # 等价
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.adapters.base import FixtureAdapter
from app.cli import KB_PATH, FIXTURES, ROOT, build_ticket, default_policy, kb_context, load_kb, resolve_fixture
from app.contracts.models import DomainError, LLMConfig
from app.core.auth import OperatorConfigError, load_operators, verify as verify_operator
from app.core.pipeline import run as run_pipeline
from app.core.redact import audit_view
from app.eval.retrieval import THRESHOLD_PT
from app.llm.factory import make_provider
from app.llm.prompts import prompt_version

DIST = ROOT / "web" / "dist"
BASELINE = ROOT / "reports" / "baseline_v0.json"
RETRIEVAL = ROOT / "reports" / "retrieval_v0.json"
PLATFORMS = ("taobao", "douyin")
# 带 client_token 的跑单串行化：查重与写入之间不留 TOCTOU 窗口
_run_lock = threading.Lock()

app = FastAPI(title="售后工单处置 API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 请求体
# --------------------------------------------------------------------------
class RunRequest(BaseModel):
    fixture: str = Field(min_length=1)
    text: str | None = Field(default=None, max_length=2000)
    confirm: str | None = None
    budget: int = Field(default=6000, ge=1)
    timeout_ms: int = Field(default=30000, ge=1)
    delay_ms: int = Field(default=0, ge=0, le=10000)
    # auto = 走 .env/环境变量；scripted = 离线台词；openai_compat = 真实模型
    provider: str | None = Field(default=None, pattern="^(auto|scripted|openai_compat)$")
    max_tokens: int = Field(default=1024, ge=64, le=8192)
    # 前端每次用户动作生成一个；网络重试/双击复用同一个 token，避免重复打款
    client_token: str | None = Field(default=None, max_length=64, pattern="^[A-Za-z0-9_.:-]{1,64}$")


class ReplayRequest(BaseModel):
    run_id: str = Field(min_length=1)


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------
def _runs_path() -> Path:
    return Path(os.environ.get("RUNS_PATH", ROOT / "reports" / "runs.jsonl"))


def _read_runs() -> list[dict[str, Any]]:
    path = _runs_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _append_run(record: dict[str, Any]) -> None:
    path = _runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _make_provider(override: str | None = None, *, timeout_ms: int = 30000, max_tokens: int = 1024, delay_ms: int = 0):
    """None = 走 .env/环境变量的选择；auto 与 openai_compat 都要求配置齐备（缺 key 直接报错）。"""
    return make_provider(
        override,
        timeout_ms=timeout_ms,
        max_tokens=max_tokens,
        delay_ms=delay_ms,
    )


def _llm_meta(override: str | None = None) -> dict[str, Any]:
    try:
        provider = _make_provider(override)
    except ValueError as exc:  # 显式配了 openai_compat 却缺 key：别让 /api/meta 直接 500
        return {"provider": "scripted", "model": "scripted-v1", "configured": False, "config_error": str(exc)}
    return {
        "provider": provider.name,
        "model": provider.model,
        "configured": provider.name != "scripted",
    }


def _kb(text: str) -> tuple[list[str], dict[str, str]]:
    """与 CLI 同一条检索路径：API 不另造一套 KB 注入逻辑，否则两边引用可校验性不同。"""
    if not KB_PATH.is_file():
        return [], {}
    try:
        retriever, answers = load_kb()
    except (OSError, ValueError):
        return [], {}
    return kb_context(retriever, answers, text)


def _require_operator(request: Request, confirm: str | None = None) -> str:
    """审批人身份来自**已验证的调用方**，不是请求体里的字符串（CONTRACT §9.1）。

    没有这一层，任何能访问端口的人填 `confirm="human:任意id"` 就能触发退款。
    """
    try:
        operators = load_operators()
    except OperatorConfigError as exc:
        raise HTTPException(status_code=503, detail=f"操作人配置有误：{exc}") from exc
    if not operators:
        raise HTTPException(
            status_code=503,
            detail="未配置操作人；请在 .env 设置 AFTERSALE_OPERATORS=id:token[,id:token]",
        )
    operator_id = (request.headers.get("x-operator-id") or "").strip()
    token = (request.headers.get("x-operator-token") or "").strip()
    if not operator_id or not token or not verify_operator(operators, operator_id, token):
        raise HTTPException(status_code=401, detail="操作人身份校验失败（X-Operator-Id / X-Operator-Token）")
    if confirm not in (None, "") and confirm != f"human:{operator_id}":
        raise HTTPException(status_code=403, detail=f"confirm 必须是当前操作人 human:{operator_id}")
    return operator_id


def _order_view(platform: str, order_ref: str) -> dict[str, Any]:
    order = FixtureAdapter(FIXTURES, platform).fetch_order(order_ref)
    data = order.model_dump(mode="json")
    data.pop("raw_ref", None)  # 平台原始载荷只允许留在 adapters（AC04）
    return data


def _fixture_view(platform: str, path: Path) -> dict[str, Any]:
    stem = path.stem
    short = "_".join(stem.split("_")[:2])
    ticket = build_ticket(stem, path)
    view: dict[str, Any] = {
        "platform": platform,
        "stem": stem,
        "short": short,
        "order_ref": ticket.order_ref,
        "text": ticket.text,
        "order": None,
        "error": None,
    }
    try:
        view["order"] = _order_view(platform, ticket.order_ref or "")
    except DomainError as exc:  # 快照本身坏掉：照样展示，标成不可跑
        view["error"] = exc.code.value
    if view["order"] is None and view["error"] is None:
        view["error"] = "E_ORDER_NOT_FOUND"
    return view


@app.exception_handler(DomainError)
async def _domain_error_handler(_request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": exc.code.value, "message": exc.message, "hint": exc.hint},
    )


# --------------------------------------------------------------------------
# 元信息 / 健康
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    # 配置问题要在健康检查里看得见，但绝不回显 key（只给 provider/model/configured）
    return {"ok": True, "now": datetime.now(timezone.utc).isoformat(), "llm": _llm_meta()}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    policy = default_policy()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    retrieval = json.loads(RETRIEVAL.read_text(encoding="utf-8")) if RETRIEVAL.exists() else None
    fixtures = list_fixtures()
    return {
        **_llm_meta(),
        "prompt_version": prompt_version(),
        "policy": policy.model_dump(mode="json"),
        "baseline": baseline,
        "retrieval": retrieval,
        # 阈值只由 app.eval.retrieval 定义；前端只展示，不自己复刻比较逻辑（NG-6）
        "retrieval_threshold": THRESHOLD_PT,
        "fixtures_count": len(fixtures["items"]),
        "runs_count": len(_read_runs()),
        "dist_ready": DIST.is_dir(),
    }


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@app.get("/api/fixtures")
def list_fixtures() -> dict[str, Any]:
    items = [
        _fixture_view(platform, path)
        for platform in PLATFORMS
        for path in sorted((FIXTURES / platform).glob("*.json"))
    ]
    return {"items": items}


# --------------------------------------------------------------------------
# 跑单 / 回放
# --------------------------------------------------------------------------
def _execute(body: RunRequest, operator: str | None = None) -> dict[str, Any]:
    try:
        platform, stem, path = resolve_fixture(body.fixture)
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ticket = build_ticket(stem, path)
    if body.text is not None:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="ticket 文本不能为空")
        ticket = ticket.model_copy(update={"text": text[:2000]})

    provider = _make_provider(
        body.provider,
        timeout_ms=body.timeout_ms,
        max_tokens=body.max_tokens,
        delay_ms=body.delay_ms,
    )
    llm = LLMConfig(
        provider=provider.name,
        model=provider.model,
        prompt_version=prompt_version(),
        token_budget=body.budget,
        timeout_ms=body.timeout_ms,
    )
    if body.confirm and operator is None:
        # 内部调用也必须走同一规则：没有已验证身份就没有审批人
        raise HTTPException(status_code=403, detail="confirm 需要先通过操作人身份校验")
    confirm = f"human:{operator}" if (body.confirm and operator) else None
    kb_hits, kb_quotes = _kb(ticket.text)
    result = run_pipeline(
        ticket,
        adapter=FixtureAdapter(FIXTURES, platform),
        provider=provider,
        policy=default_policy(),
        llm=llm,
        now=datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc),
        confirm=confirm,
        kb_quotes=kb_quotes,
        kb_hits=kb_hits,
    )
    out = result.out
    record = audit_view(
        {
            "run_id": out.run_id,
            "fixture": stem,
            "confirm": confirm,
            "operator": operator,
            "client_token": body.client_token,
            "prompt_version": out.prompt_version,
            "policy_version": out.policy_version,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "llm": llm.model_dump(),
            "out": out.model_dump(mode="json"),
            "trace": result.trace,
        }
    )
    _append_run(record)
    return record


@app.post("/api/runs")
def create_run(request: Request, body: RunRequest) -> dict[str, Any]:
    operator = _require_operator(request, body.confirm)
    if body.client_token:
        # 同一 token 只执行一次：网络重试、双击、刷新重发都命中同一条记录
        with _run_lock:
            for row in _read_runs():
                if row.get("client_token") == body.client_token:
                    return {"record": row, "deduplicated": True}
            return {"record": _execute(body, operator)}
    return {"record": _execute(body, operator)}


@app.get("/api/runs")
def list_runs(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    rows = _read_runs()
    return {"items": list(reversed(rows))[:limit], "total": len(rows)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    for row in _read_runs():
        if row.get("run_id") == run_id:
            return {"record": row}
    raise HTTPException(status_code=404, detail=f"run not found: {run_id}")


@app.post("/api/replay")
def replay(request: Request, body: ReplayRequest) -> dict[str, Any]:
    _require_operator(request)  # 回放会重放历史审批动作，同样要求身份
    hit = next((r for r in _read_runs() if r.get("run_id") == body.run_id), None)
    if hit is None:
        raise HTTPException(status_code=404, detail=f"run not found: {body.run_id}")

    try:
        platform, stem, path = resolve_fixture(hit["fixture"])
    except SystemExit as exc:  # 记录里的 fixture 被改名/删除：这是数据问题，不是 500
        raise HTTPException(status_code=409, detail=f"记录里的 fixture 已不存在: {hit.get('fixture')!r}") from exc
    policy = default_policy()
    policy.version = hit["policy_version"]  # 回放用记录里的版本，不追最新
    llm_record = hit.get("llm") or {"provider": "scripted", "model": "scripted-v1"}
    llm = LLMConfig(
        provider=llm_record.get("provider", "scripted"),
        model=llm_record.get("model", "scripted-v1"),
        prompt_version=hit["prompt_version"],
        token_budget=int(llm_record.get("token_budget") or 6000),
        timeout_ms=int(llm_record.get("timeout_ms") or 30000),
    )
    try:
        provider = _make_provider(llm.provider, timeout_ms=llm.timeout_ms)
    except ValueError as exc:  # 回放真实模型但 key 缺失：明确的配置错误，不是 500
        raise HTTPException(status_code=400, detail=f"回放所需模型配置缺失：{exc}") from exc
    ticket = build_ticket(stem, path)
    # 回放必须和首次运行注入同一份 KB 上下文，否则 prompt 不同、usage 会被误判成漂移
    kb_hits, kb_quotes = _kb(ticket.text)
    result = run_pipeline(
        ticket,
        adapter=FixtureAdapter(FIXTURES, platform),
        provider=provider,
        policy=policy,
        llm=llm,
        now=datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc),
        confirm=hit.get("confirm"),
        kb_quotes=kb_quotes,
        kb_hits=kb_hits,
    )
    now_out = audit_view(result.out.model_dump(mode="json"))
    old_out = hit.get("out", {})
    drift = [
        key
        for key in now_out
        if key not in {"run_id", "latency_ms", "tool_calls"} and now_out[key] != old_out.get(key)
    ]
    return {
        "run_id": body.run_id,
        "drift": drift,
        "policy_version": policy.version,
        "prompt_version": hit["prompt_version"],
        "replayed": now_out,
    }


# --------------------------------------------------------------------------
# 静态前端：web/dist（构建后存在才挂载）
# --------------------------------------------------------------------------
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if (DIST / "index.html").exists():
        return FileResponse(DIST / "index.html")
    return JSONResponse(
        status_code=503,
        content={"error": "前端未构建", "hint": "cd web && npm install && npm run build"},
    )


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="unknown api route")
    if (DIST / "index.html").exists():
        return FileResponse(DIST / "index.html")
    raise HTTPException(status_code=404, detail="not found")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
