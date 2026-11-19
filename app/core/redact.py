"""审计脱敏：日志里只留到"能定位、不能定位到人"的粒度（AC25）。

规则很土但够用：
- 手机号保留前 3 后 4；
- 地址保留到区/县，后面一律 ********；
- 身份证之类本期不出现，出现即视为缺陷（不静默放过）。
"""
from __future__ import annotations

import re

PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
ID_RE = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")
ADDR_CUT_RE = re.compile(r"^(.+?[区县])")
ADDR_TAIL_RE = re.compile(r"[路街道巷弄号幢栋室楼层].*$")


def mask_phone(text: str) -> str:
    return PHONE_RE.sub(r"\1****\2", text)


def mask_id(text: str) -> str:
    return ID_RE.sub(r"\1********\3", text)


def mask_address(addr: str) -> str:
    m = ADDR_CUT_RE.match(addr.strip())
    if m:
        return m.group(1) + "********"
    head = ADDR_TAIL_RE.sub("", addr.strip())
    return (head + "********") if head else "********"


def redact_text(text: str) -> str:
    return mask_id(mask_phone(text))


ADDRESS_KEYS = frozenset({"address", "receiver_address", "shipping_address"})


def audit_view(record):
    """日志落盘前的唯一出口。新增字段若含 PII，必须在这里显式处理。

    递归处理 dict/list：记录是嵌套结构（out/draft/trace），只扫顶层等于没扫。
    """
    return _walk(record, key=None)


def _walk(node, *, key: str | None):
    if isinstance(node, dict):
        return {k: _walk(v, key=k) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_walk(v, key=key) for v in node]
    if isinstance(node, str):
        return mask_address(node) if key in ADDRESS_KEYS else redact_text(node)
    return node
