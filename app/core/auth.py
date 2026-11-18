"""操作人身份校验：审批人身份必须来自"已验证的调用方"，不能由请求体自称。

为什么要有这一层：`confirm="human:xxx"` 只是一个字符串。没有鉴权时，任何能访问
HTTP 端口的人都能把任意 id 填进去触发退款——等于"审批"这道闸门只存在于文案里。

配置（进程环境 > `.env`，与模型配置同一套读取规则）：

    AFTERSALE_OPERATORS=alice:<token-a>,bob:<token-b>

未配置时写接口一律拒绝（503）：宁可不可用，也不允许匿名审批。
token 不进日志不进 run 记录、不回显；比较用 `hmac.compare_digest`。
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from app.llm.settings import DEFAULT_ENV_FILE, read_env_file

ENV_OPERATORS = "AFTERSALE_OPERATORS"


class OperatorConfigError(ValueError):
    """配置本身坏了（格式错、重复 id），与"没配"、与"验证失败"是三种不同的事。"""


def parse_operators(raw: str) -> dict[str, str]:
    """把 `id:token,id:token` 解析成映射；格式错误立刻报，不猜。"""
    operators: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise OperatorConfigError(f"{ENV_OPERATORS} 格式应为 id:token，收到 {chunk!r}")
        operator_id, _, token = chunk.partition(":")
        operator_id, token = operator_id.strip(), token.strip()
        if not operator_id or not token:
            raise OperatorConfigError(f"{ENV_OPERATORS} 的 id/token 不能为空：{chunk!r}")
        if operator_id in operators:
            raise OperatorConfigError(f"{ENV_OPERATORS} 操作人重复：{operator_id!r}")
        operators[operator_id] = token
    return operators


def load_operators(env_file: Path | None = None) -> dict[str, str]:
    raw = os.environ.get(ENV_OPERATORS)
    if raw is None:
        raw = read_env_file(env_file or DEFAULT_ENV_FILE).get(ENV_OPERATORS, "")
    return parse_operators(raw)


def verify(operators: dict[str, str], operator_id: str, token: str) -> bool:
    """常数时间比较，避免按字符提前返回泄露 token 前缀。"""
    expected = operators.get(operator_id or "")
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, token)
