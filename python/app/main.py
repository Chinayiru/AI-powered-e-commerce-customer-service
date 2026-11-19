"""FastAPI entrypoint: POST /internal/agent/ask.

Python is read-only. It never opens a database and never writes a ticket,
draft, status, or refund. The Java control plane remains the only decision
maker; `policyCheck` is intentionally absent from this service.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .agent import AgentService
from .config import Settings
from .contracts import AskRequest, AskResponse
from .identity import Identity, IdentityError, verify_identity
from .tools import ToolClient

logger = logging.getLogger("aftersale.agent")


def create_app(service: AgentService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    tools = ToolClient(settings) if service is None else None
    agent = service or AgentService(settings, tools)  # type: ignore[arg-type]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "agent ready provider=%s prompt=%s java=%s",
            settings.provider,
            settings.prompt_version,
            settings.java_base_url,
        )
        yield
        if tools is not None:
            tools.close()

    app = FastAPI(title="aftersale-agent-python", version="0.1.0", lifespan=lifespan)

    def require_internal(request: Request, payload: AskRequest) -> Identity:
        try:
            identity = verify_identity(
                request.headers.get("X-Internal-Identity"),
                request.url.path,
                settings.hmac_secret,
            )
        except IdentityError as exc:
            raise _Unauthorized(str(exc)) from exc

        # 身份里的 userId 是唯一可信来源：请求体自称的 userId 只能与它相等，
        # 否则就是“A 的签名 + body 写 B”的越权尝试。
        if identity.userId != payload.userId:
            raise _Forbidden("内部身份 userId 与请求体不一致")
        # /ask 只允许控制面/系统角色调用；Python 工具角色不能反过来打 Agent。
        if identity.role not in {"agent", "system"}:
            raise _Forbidden("该内部角色无权调用 Agent")
        return identity

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "aftersale-agent-python"}

    @app.post(
        "/internal/agent/ask",
        response_model=AskResponse,
        response_model_exclude_none=False,
    )
    def ask(
        payload: AskRequest,
        request: Request,
        identity: Identity = Depends(require_internal),
    ) -> AskResponse:
        started = time.perf_counter()
        # 工具调用一律使用验签身份里的 userId，而不是请求体字段。
        response = agent.answer(payload, user_id=identity.userId)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "ask trace_id=%s ticket_id=%s intent=%s confidence=%.2f "
            "reply_type=%s need_review=%s degraded=%s latency_ms=%.1f",
            payload.traceId,
            payload.ticketId,
            response.intent.value,
            response.confidence,
            response.replyType.value,
            response.needHumanReview,
            response.degraded,
            elapsed_ms,
        )
        return response

    @app.exception_handler(_Unauthorized)
    async def unauthorized(_: Request, exc: _Unauthorized) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "code": "UNAUTHENTICATED",
                "message": str(exc),
                "traceId": "",
                "retryable": False,
            },
        )

    @app.exception_handler(_Forbidden)
    async def forbidden(request: Request, exc: _Forbidden) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "code": "FORBIDDEN_SCOPE",
                "message": str(exc),
                "traceId": request.headers.get("X-Trace-Id", ""),
                "retryable": False,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_args(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_ARGS",
                "message": "请求参数不合法",
                "traceId": request.headers.get("X-Trace-Id", ""),
                "retryable": False,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 兜底不能把 FastAPI 默认的 500 纯文本/堆栈直接暴露给控制面：
        # 统一返回 Java 契约里的错误体，让 Java 能按 AGENT_UNAVAILABLE 降级。
        logger.exception(
            "unhandled agent error trace_id=%s path=%s",
            request.headers.get("X-Trace-Id", ""),
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "AGENT_UNAVAILABLE",
                "message": "Agent 内部错误，请稍后重试转人工",
                "traceId": request.headers.get("X-Trace-Id", ""),
                "retryable": True,
            },
        )

    return app


class _Unauthorized(Exception):
    pass


class _Forbidden(Exception):
    pass


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
