"""Environment-backed configuration.

The defaults are deliberately the local demo values also used by the Java
`application.yml`; production must override the HMAC secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            java_base_url=os.getenv("AFTERSALE_JAVA_BASE_URL", "http://localhost:8080").rstrip("/"),
            hmac_secret=os.getenv(
                "AFTERSALE_HMAC_SECRET", "dev-only-hmac-secret-change-me-please"
            ),
            tool_timeout_seconds=_env_float("AFTERSALE_TOOL_TIMEOUT_SECONDS", 1.0),
            tool_retries=_env_int("AFTERSALE_TOOL_RETRIES", 1),
            confidence_threshold=_env_float("AFTERSALE_CONFIDENCE_THRESHOLD", 0.60),
            auto_suggest_limit_cents=_env_int("AFTERSALE_AUTO_SUGGEST_LIMIT_CENTS", 5000),
            return_window_days=_env_int("AFTERSALE_RETURN_WINDOW_DAYS", 7),
            policy_version=os.getenv("AFTERSALE_POLICY_VERSION", "2026-11"),
            prompt_version=os.getenv("AFTERSALE_PROMPT_VERSION", "p1.0.0"),
            provider=os.getenv("AFTERSALE_AGENT_PROVIDER", "scripted"),
        )
