"""测试统一离线：不管 .env 是否配了真实模型，测试都走 scripted。

真实模的输出不确定（temperature/后端差异），AC16 回放、AC20 两次运行一致
都要求确定性；联网测试还会让 CI 依赖外部 API。需要验证真实 provider 时，
用 `--provider openai_compat` 手动跑 CLI，或用测试里的假 transport。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _offline_provider(monkeypatch):
    monkeypatch.setenv("AFTERSALE_LLM_PROVIDER", "scripted")
