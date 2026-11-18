"""provider 工厂：CLI / API / 封存脚本共用，避免各自拼装。

`provider=None` 表示"按配置走"：`.env` / 环境变量里的 `AFTERSALE_LLM_PROVIDER`
（默认 `scripted`）。`provider="auto"` 与显式 `openai_compat` 一样要求配置齐备
（key/base_url/model），缺项直接报错——**不再静默回退 scripted**：那会让线上
"以为在调模型、其实在念台词"，而且只有翻记录才看得出来。
"""
from __future__ import annotations

from pathlib import Path

from app.llm.base import Provider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.scripted import ScriptedProvider
from app.llm.settings import provider_name, resolve


def make_provider(
    provider: str | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_ms: int = 30000,
    max_tokens: int = 1024,
    delay_ms: int = 0,
    env_file: Path | None = None,
) -> Provider:
    name = provider_name(provider, env_file=env_file)
    if name == "scripted":
        return ScriptedProvider(model=model, delay_ms=delay_ms)
    if name == "auto":
        try:
            resolve(base_url=base_url, model=model, api_key=api_key, env_file=env_file)
        except ValueError as exc:
            # 报错文本只含变量名，不含 key 值（resolve 保证）
            raise ValueError(f"provider=auto 需要完整模型：{exc}") from exc
        name = "openai_compat"
    if name == "openai_compat":
        conf = resolve(base_url=base_url, model=model, api_key=api_key, env_file=env_file)
        return OpenAICompatProvider(
            base_url=conf.base_url,
            api_key=conf.api_key,
            model=conf.model,
            timeout_s=max(1.0, timeout_ms / 1000),
            max_tokens=max_tokens,
        )
    raise ValueError(f"unknown provider: {provider}")
