"""操作人身份配置（CONTRACT §9.1 / ADR-013）。

这里只测"配置解析 + 比对"两件事；"没身份就不许写"在 tests/test_api.py 走 HTTP 断言。
"""
from __future__ import annotations

import pytest

from app.core.auth import OperatorConfigError, load_operators, parse_operators, verify


def test_parse_operators_keeps_order_and_allows_colon_in_token():
    ops = parse_operators(" alice:tok-a , bob:tok:b , ")
    assert ops == {"alice": "tok-a", "bob": "tok:b"}


@pytest.mark.parametrize("raw", ["alice", "alice:", ":tok", "a:1,a:2"])
def test_parse_operators_rejects_bad_config(raw):
    """格式错误必须报配置错误：不能把坏配置当成"没配置"，也不能猜一个默认口令。"""
    with pytest.raises(OperatorConfigError):
        parse_operators(raw)


def test_env_wins_over_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "ops.env"
    env_file.write_text("AFTERSALE_OPERATORS=demo1:file-token\n", encoding="utf-8")
    monkeypatch.delenv("AFTERSALE_OPERATORS", raising=False)
    assert load_operators(env_file) == {"demo1": "file-token"}

    monkeypatch.setenv("AFTERSALE_OPERATORS", "demo1:env-token")
    assert load_operators(env_file) == {"demo1": "env-token"}


def test_verify_needs_exact_id_and_token():
    ops = {"demo1": "tok-demo1"}
    assert verify(ops, "demo1", "tok-demo1") is True
    assert verify(ops, "demo1", "tok-demo") is False  # 前缀不算
    assert verify(ops, "demo2", "tok-demo1") is False
    assert verify(ops, "", "") is False
    assert verify({}, "demo1", "tok-demo1") is False
