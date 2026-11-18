"""模型接入配置：env > .env 文件 > 显式参数（显式参数优先于两者）。

密钥只从环境/`.env` 读，不写死在代码、不写进 run 记录、不进 git（`.env` 已在 .gitignore）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENV_PROVIDER = "AFTERSALE_LLM_PROVIDER"
ENV_BASE_URL = "AFTERSALE_LLM_BASE_URL"
ENV_MODEL = "AFTERSALE_LLM_MODEL"
ENV_API_KEY = "AFTERSALE_LLM_API_KEY"

DEFAULT_ENV_FILE = ROOT / ".env"


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str
    source: str  # 说明这份配置从哪来，便于排障（不打印 key）

    def masked(self) -> str:
        from app.llm.openai_compat import mask_key

        return f"{self.base_url} model={self.model} key={mask_key(self.api_key)} ({self.source})"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            values[name] = value
    return values


def provider_name(explicit: str | None = None, *, env_file: Path | None = None) -> str:
    """决定用哪个 provider：显式参数 > 进程环境 > .env > 默认 scripted。

    只读配置，不校验 key：`auto` 由调用方翻译成"有 key 就用真实模型"。
    """
    if explicit:
        return explicit
    if os.environ.get(ENV_PROVIDER):
        return os.environ[ENV_PROVIDER].strip() or "scripted"
    file_values = read_env_file(env_file or DEFAULT_ENV_FILE)
    return (file_values.get(ENV_PROVIDER) or "scripted").strip() or "scripted"


def resolve(
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    env_file: Path | None = None,
) -> LLMSettings:
    """优先级：显式参数 > 进程环境变量 > .env 文件。缺项直接报错，不猜默认模型。"""
    file_values = read_env_file(env_file or DEFAULT_ENV_FILE)
    sources: list[str] = []

    def pick(explicit: str | None, env_name: str) -> str:
        if explicit:
            sources.append(f"{env_name}=cli")
            return explicit
        if os.environ.get(env_name):
            sources.append(f"{env_name}=env")
            return os.environ[env_name]
        if file_values.get(env_name):
            sources.append(f"{env_name}=.env")
            return file_values[env_name]
        return ""

    resolved_url = pick(base_url, ENV_BASE_URL)
    resolved_model = pick(model, ENV_MODEL)
    resolved_key = pick(api_key, ENV_API_KEY)
    missing = [
        name
        for name, value in (
            (ENV_BASE_URL, resolved_url),
            (ENV_MODEL, resolved_model),
            (ENV_API_KEY, resolved_key),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "缺少模型配置：" + ", ".join(missing) + "；可写入 .env 或设置环境变量，"
            "也可用 --base-url/--model/--api-key 显式传入"
        )
    return LLMSettings(
        base_url=resolved_url,
        model=resolved_model,
        api_key=resolved_key,
        source=", ".join(sources),
    )
