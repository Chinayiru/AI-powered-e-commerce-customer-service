"""Read-only Java tool client (T1 queryOrder / T2 getLogistics).

Python has exactly two hands: it may read order and logistics facts, never
write. Tool request bodies never contain ``userId``.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Settings
from .identity import issue_identity


class ToolUnavailable(Exception):
    def __init__(self, code: str = "TOOL_UNAVAILABLE", message: str = "tool unavailable"):
        super().__init__(message)
        self.code = code


class ToolClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            base_url=settings.java_base_url,
            timeout=settings.tool_timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def query_order(self, user_id: str, order_no: str) -> dict[str, Any] | None:
        return self._post("/internal/tools/queryOrder", {"orderNo": order_no}, user_id)

    def get_logistics(self, user_id: str, order_no: str) -> dict[str, Any] | None:
        return self._post("/internal/tools/getLogistics", {"orderNo": order_no}, user_id)

    def _post(self, path: str, body: dict[str, Any], user_id: str) -> dict[str, Any] | None:
        last_code = "TOOL_UNAVAILABLE"
        attempts = max(0, self._settings.tool_retries) + 1
        for attempt in range(attempts):
            identity = issue_identity(user_id, "python", self._settings.hmac_secret)
            try:
                response = self._client.post(
                    path,
                    json=body,
                    headers={
                        "X-Internal-Identity": identity,
                        "Content-Type": "application/json",
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError):
                last_code = "TOOL_TIMEOUT"
                if attempt + 1 < attempts:
                    time.sleep(0.2)
                    continue
                raise ToolUnavailable(last_code, "tool timeout") from None

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ToolUnavailable("TOOL_UNAVAILABLE", "tool returned invalid JSON") from exc
            if response.status_code == 404:
                return None

            code = _error_code(response)
            last_code = code
            if response.status_code in (503, 504) and attempt + 1 < attempts:
                time.sleep(0.2)
                continue
            raise ToolUnavailable(code, f"tool returned HTTP {response.status_code}")

        raise ToolUnavailable(last_code, "tool unavailable")


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("code"), str):
            return payload["code"]
    except ValueError:
        pass
    if response.status_code == 504:
        return "TOOL_TIMEOUT"
    if response.status_code == 422:
        return "INVALID_ARGS"
    return "TOOL_UNAVAILABLE"
