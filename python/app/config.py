"""Environment-backed configuration.

The HMAC secret has no repository default: a missing or too-short
``AFTERSALE_HMAC_SECRET`` aborts startup instead of silently falling back to a
well-known demo value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

_MIN_SECRET_LENGTH = 32


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _required_hmac_secret() -> str:
    value = (os.getenv("AFTERSALE_HMAC_SECRET") or "").strip()
    if not value:
        raise RuntimeError(
            "AFTERSALE_HMAC_SECRET 未配置；拒绝使用仓库默认密钥启动 Agent"
        )
    if len(value) < _MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"AFTERSALE_HMAC_SECRET 长度不足 {_MIN_SECRET_LENGTH} 字符"
        )
    return value


def _required_java_base_url() -> str:
    value = (os.getenv("AFTERSALE_JAVA_BASE_URL") or "").strip().rstrip("/")
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username is not None or url.password is not None
                or url.query or url.fragment or url.hostname.endswith(".invalid")):
            raise ValueError
        _ = url.port
    except ValueError:
        # Do not include a possibly credential-bearing value in the error.
        raise RuntimeError("AFTERSALE_JAVA_BASE_URL 未配置或无效，地址不得包含凭证、查询串或片段") from None
    return value


@dataclass(frozen=True)
class Settings:
    java_base_url: str
    hmac_secret: str
    tool_timeout_seconds: float
    tool_retries: int
    confidence_threshold: float
    auto_suggest_limit_cents: int
    return_window_days: int
    policy_version: str
    prompt_version: str
    provider: str

    def __post_init__(self) -> None:
        # 显式构造 Settings 时同样拒绝短密钥，避免测试/运维绕开 from_env 的校验。
        if len(self.hmac_secret or "") < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"hmac_secret 长度不足 {_MIN_SECRET_LENGTH} 字符；"
                "请通过 AFTERSALE_HMAC_SECRET 注入"
            )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            java_base_url=_required_java_base_url(),
            hmac_secret=_required_hmac_secret(),
            tool_timeout_seconds=_env_float("AFTERSALE_TOOL_TIMEOUT_SECONDS", 1.0),
            tool_retries=_env_int("AFTERSALE_TOOL_RETRIES", 1),
            confidence_threshold=_env_float("AFTERSALE_CONFIDENCE_THRESHOLD", 0.60),
            auto_suggest_limit_cents=_env_int("AFTERSALE_AUTO_SUGGEST_LIMIT_CENTS", 5000),
            return_window_days=_env_int("AFTERSALE_RETURN_WINDOW_DAYS", 7),
            policy_version=os.getenv("AFTERSALE_POLICY_VERSION", "2026-11"),
            prompt_version=os.getenv("AFTERSALE_PROMPT_VERSION", "p1.0.0"),
            provider=os.getenv("AFTERSALE_AGENT_PROVIDER", "scripted"),
        )
