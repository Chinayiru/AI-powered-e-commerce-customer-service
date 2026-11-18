"""OpenAI 兼容 `/chat/completions` Provider：真实模型接入（CONTRACT §8 的第二个 provider）。

设计约束：
- **只加一个 provider，不改契约**：返回仍是 `LLMResponse.raw = 一段 JSON 原文`，
  由 `parse_proposal` 统一校验；模型拿不准时只能通过 `confidence/needs_human` 影响策略，
  不能绕过策略层直接放行。
- **传输层可注入**：单测把 `transport` 换成假的，不联网、不依赖 key（AC20 的确定性不受影响）。
- **错误不新增错误码**：所有失败抛 `ProviderError`，由 pipeline 落 `timeout` / `degraded`，
  错误码仍限定在 CONTRACT §10 的 13 个之内（AC26）。
- **key 不进日志、不进 run 记录**：只在 Authorization 头里出现，`repr()` 一律打码。
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable

from app.llm.base import LLMResponse

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]

DEFAULT_MAX_TOKENS = 1024


class ProviderError(RuntimeError):
    """一次模型调用失败。`timeout=True` 时 pipeline 记 timeout，否则记 degraded。"""

    def __init__(self, message: str, *, status: int | None = None, timeout: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.timeout = timeout


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "***"
    return f"{key[:5]}***{key[-4:]}"


def extract_json(text: str) -> str:
    """从模型输出里取出一个 JSON 对象原文（容忍 ```json 围栏与前后废话）。"""
    raw = (text or "").strip()
    if not raw:
        raise ProviderError("empty content")
    candidates: list[str] = []
    if raw.startswith("```"):
        body = raw[3:]
        if body.lstrip().lower().startswith("json"):
            body = body.lstrip()[4:]
        end = body.rfind("```")
        if end != -1:
            body = body[:end]
        candidates.append(body.strip())
    candidates.append(raw)
    start, stop = raw.find("{"), raw.rfind("}")
    if start != -1 and stop > start:
        candidates.append(raw[start : stop + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return cand
    raise ProviderError("content is not a JSON object: " + raw[:120])


def _http_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """默认传输：标准库 urllib，不引第三方 HTTP 客户端。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ProviderError(
            f"HTTP {exc.code}: {detail}", status=exc.code, timeout=exc.code in (408, 504)
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError(f"timeout after {timeout}s", timeout=True) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderError(
            f"connection failed: {reason}", timeout=isinstance(reason, (TimeoutError, socket.timeout))
        ) from exc
    try:
        obj = json.loads(body)
    except ValueError as exc:
        raise ProviderError("response is not JSON: " + body[:200], status=502) from exc
    if not isinstance(obj, dict):
        raise ProviderError("response JSON is not an object", status=502)
    if obj.get("error") and not obj.get("choices"):
        raise ProviderError("upstream error: " + json.dumps(obj["error"], ensure_ascii=False)[:300], status=502)
    return obj


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
        json_mode: bool = True,
        transport: Transport | None = None,
    ) -> None:
        if not base_url:
            raise ProviderError("base_url is required")
        if not api_key:
            raise ProviderError("api_key is required (env AFTERSALE_LLM_API_KEY)")
        if not model:
            raise ProviderError("model is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = max(1.0, float(timeout_s))
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.json_mode = bool(json_mode)
        self._api_key = api_key
        self._transport: Transport = transport or _http_json
        self.calls = 0

    def __repr__(self) -> str:
        return f"OpenAICompatProvider(base_url={self.base_url!r}, model={self.model!r}, key={mask_key(self._api_key)})"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "aftersale-w1/1.0",
        }

    def payload(self, prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def propose(self, prompt: str, key: str, *, timeout_ms: int | None = None) -> LLMResponse:
        self.calls += 1
        url = f"{self.base_url}/chat/completions"
        body = self.payload(prompt)
        timeout_s = self.timeout_s if timeout_ms is None else max(0.5, min(self.timeout_s, timeout_ms / 1000))
        try:
            data = self._transport(url, self.headers(), body, timeout_s)
        except ProviderError as exc:
            # 有的中转不认 response_format：400 时摘掉再试一次（只降格式，不降校验）
            if self.json_mode and exc.status == 400 and "response_format" in json.dumps(body):
                body.pop("response_format", None)
                data = self._transport(url, self.headers(), body, timeout_s)
            else:
                raise
        return self._to_response(data, prompt)

    def _to_response(self, data: dict[str, Any], prompt: str) -> LLMResponse:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("empty choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # 少数实现返回分段
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        raw = extract_json(content or "")

        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens") or 0)
        out_tok = int(usage.get("completion_tokens") or 0)
        estimated = False
        if in_tok <= 0:
            in_tok, estimated = max(1, len(prompt) // 4), True
        if out_tok <= 0:
            out_tok, estimated = max(1, len(raw) // 4), True
        return LLMResponse(raw=raw, input_tokens=in_tok, output_tokens=out_tok, estimated=estimated)
