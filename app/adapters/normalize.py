"""平台原始载荷 → 中立类型的唯一换算入口（CONTRACT §4.2 N1/N7）。

领域层不允许碰 float、不允许猜时区、不允许补默认值。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.contracts.models import DomainError, ErrorCode

CST = timezone(timedelta(hours=8))


def to_cents(raw: object, unit: str) -> int:
    """unit: 'cent' | 'yuan'。四舍五入只在这里做一次。"""
    if raw is None or raw == "":
        raise DomainError(ErrorCode.PLATFORM_ANOMALY, f"金额缺失: {raw!r}")
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise DomainError(ErrorCode.PLATFORM_ANOMALY, f"金额无法解析: {raw!r}") from exc
    if unit == "yuan":
        value *= 100
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(raw: object) -> datetime | None:
    """空串/None 一律返回 None——绝不补 now()（AC03）。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "T" in text:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(timezone.utc)
