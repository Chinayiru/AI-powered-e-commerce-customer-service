"""真实模型 provider 的离线测试：不联网、不需要 key。

覆盖三件事：
1. `OpenAICompatProvider` 的请求形状（json_mode/usage/Bearer）与响应解析；
2. 失败归类：400 摘掉 response_format 重试一次、超时/坏输出的异常类型；
3. pipeline 把 provider 失败落成 `timeout`/`degraded`，错误码仍在 13 个之内（AC26）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.adapters.base import FixtureAdapter
from app.cli import FIXTURES, build_ticket, default_policy, resolve_fixture
from app.contracts.models import ErrorCode, LLMConfig
from app.core.pipeline import run
from app.llm.factory import make_provider
from app.llm.openai_compat import OpenAICompatProvider, ProviderError, extract_json, mask_key
from app.llm.prompts import prompt_version
from app.llm.settings import provider_name, resolve
from app.llm.scripted import ScriptedProvider

NOW = datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc)
VALID = json.dumps({"intent": "refund", "aftersales_type": "REFUND_ONLY", "slots": {}}, ensure_ascii=False)


def fake_provider(transport, **kw) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="https://example.test/v1",
        api_key="sk-test-1234567890",
        model="fake-model",
        transport=transport,
        **kw,
    )


def ok_transport(payloads: list[dict] | None = None, content: str = VALID):
    def _t(url, headers, payload, timeout):
        if payloads is not None:
            payloads.append(payload)
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        }

    return _t


def test_request_shape_and_masking():
    prov = fake_provider(ok_transport())
    body = prov.payload("hi")
    assert body["model"] == "fake-model"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert prov.headers()["Authorization"].startswith("Bearer sk-test")
    assert "sk-test-1234567890" not in repr(prov)
    assert mask_key("sk-test-1234567890") == "sk-te***7890"


def test_propose_parses_usage_and_fenced_json():
    content = "好的，结果如下：\n```json\n" + VALID + "\n```"
    resp = fake_provider(ok_transport(content=content)).propose("p", "TB1001")
    assert json.loads(resp.raw)["intent"] == "refund"
    assert (resp.input_tokens, resp.output_tokens) == (120, 40)
    assert resp.estimated is False


def test_missing_usage_is_estimated():
    def transport(_url, _headers, _payload, _timeout):
        return {"choices": [{"message": {"content": VALID}}]}

    resp = fake_provider(transport).propose("x" * 40, "TB1001")
    assert resp.estimated is True
    assert resp.input_tokens >= 1 and resp.output_tokens >= 1


def test_400_with_response_format_retries_without_it():
    seen: list[dict] = []

    def transport(_url, _headers, payload, _timeout):
        seen.append(dict(payload))
        if "response_format" in payload:
            raise ProviderError("HTTP 400: unsupported", status=400)
        return {"choices": [{"message": {"content": VALID}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    prov = fake_provider(transport)
    prov.propose("p", "TB1001")
    assert len(seen) == 2
    assert "response_format" in seen[0] and "response_format" not in seen[1]


def test_non_400_errors_are_not_retried():
    calls = []

    def transport(_url, _headers, _payload, _timeout):
        calls.append(1)
        raise ProviderError("HTTP 500: upstream", status=500)

    with pytest.raises(ProviderError):
        fake_provider(transport).propose("p", "TB1001")
    assert len(calls) == 1


def test_bad_payload_raises_and_timeout_flag_survives():
    def transport(_url, _headers, _payload, _timeout):
        return {"choices": [{"message": {"content": "not json at all"}}]}

    with pytest.raises(ProviderError) as err:
        fake_provider(transport).propose("p", "TB1001")
    assert err.value.timeout is False

    def slow(_url, _headers, _payload, _timeout):
        raise ProviderError("timeout after 30s", timeout=True)

    with pytest.raises(ProviderError) as err:
        fake_provider(slow).propose("p", "TB1001")
    assert err.value.timeout is True


@pytest.mark.parametrize(
    "raw",
    ['{"a": 1}', '```json\n{"a":1}\n```', '前缀 {"a": 1} 后缀', '```\n{"a": 1}\n```'],
)
def test_extract_json_tolerates_wrappers(raw):
    assert json.loads(extract_json(raw)) == {"a": 1}


def test_settings_priority_and_missing(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AFTERSALE_LLM_PROVIDER=openai_compat\n"
        "AFTERSALE_LLM_BASE_URL=https://file.test/v1\n"
        "AFTERSALE_LLM_MODEL=file-model\n"
        "AFTERSALE_LLM_API_KEY=sk-file\n",
        encoding="utf-8",
    )
    for name in ("AFTERSALE_LLM_PROVIDER", "AFTERSALE_LLM_BASE_URL", "AFTERSALE_LLM_MODEL", "AFTERSALE_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    conf = resolve(env_file=env_file)
    assert (conf.base_url, conf.model) == ("https://file.test/v1", "file-model")
    assert provider_name(env_file=env_file) == "openai_compat"

    monkeypatch.setenv("AFTERSALE_LLM_MODEL", "env-model")
    assert resolve(env_file=env_file).model == "env-model"  # 进程环境 > .env
    assert resolve(model="cli-model", env_file=env_file).model == "cli-model"  # 显式 > 环境

    monkeypatch.delenv("AFTERSALE_LLM_MODEL")
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve(env_file=empty)


def test_factory_auto_requires_full_config(tmp_path: Path, monkeypatch):
    """`auto` 曾经缺配置就静默回退 scripted——线上会"以为在调模型、其实在念台词"。
    现在它与显式 openai_compat 同标准：缺配置就报错，报错文本只点名变量、不含 key。"""
    for name in ("AFTERSALE_LLM_PROVIDER", "AFTERSALE_LLM_BASE_URL", "AFTERSALE_LLM_MODEL", "AFTERSALE_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(ValueError) as auto_err:
        make_provider("auto", env_file=empty)
    assert "AFTERSALE_LLM_API_KEY" in str(auto_err.value)
    assert make_provider("scripted", env_file=empty).name == "scripted"
    with pytest.raises(ValueError):
        make_provider("openai_compat", env_file=empty)  # 显式选了真实模型，缺配置必须报错


class _Failing:
    name = "openai_compat"
    model = "fake-model"

    def __init__(self, *, timeout: bool) -> None:
        self.timeout = timeout

    def propose(self, prompt: str, key: str, *, timeout_ms: int | None = None):
        raise ProviderError("boom", timeout=self.timeout)


def _run(provider) -> object:
    platform, stem, path = resolve_fixture("tb_1001")
    return run(
        build_ticket(stem, path),
        adapter=FixtureAdapter(FIXTURES, platform),
        provider=provider,
        policy=default_policy(),
        llm=LLMConfig(provider="openai_compat", model="fake-model", prompt_version=prompt_version()),
        now=NOW,
    )


def test_pipeline_maps_timeout_to_timeout_stop():
    out = _run(_Failing(timeout=True)).out
    assert out.stop_reason == "timeout"
    assert out.draft.risk_flags == [ErrorCode.TIMEOUT.value]
    assert out.send_gate == "human"


def test_pipeline_maps_other_failures_to_degraded_with_existing_code():
    out = _run(_Failing(timeout=False)).out
    assert out.stop_reason == "degraded"
    assert out.draft.risk_flags == [ErrorCode.INVALID_OUTPUT.value]
    assert out.draft.risk_flags[0] in {c.value for c in ErrorCode}
