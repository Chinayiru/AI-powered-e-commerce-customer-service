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
from .identity import IdentityError, verify_identity
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

    def require_internal(request: Request) -> None:
        try:
            verify_identity(
                request.headers.get("X-Internal-Identity"),
                request.url.path,
                settings.hmac_secret,
            )
        except IdentityError as exc:
            raise _Unauthorized(str(exc)) from exc

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
        _: None = Depends(require_internal),
    ) -> AskResponse:
        started = time.perf_counter()
        response = agent.answer(payload)
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

    return app


class _Unauthorized(Exception):
    pass


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
