"""平台适配层：只有这里能读平台原始字段（AC04 静态扫描的允许清单）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.adapters.normalize import CST, parse_dt, to_cents
from app.contracts.models import (
    AftersalesCase,
    AftersalesType,
    CaseEvent,
    CaseStatus,
    DomainError,
    ErrorCode,
    Order,
    OrderItem,
    OrderStatus,
    Shipment,
    ShipmentItem,
)


class PlatformAdapter(Protocol):
    platform: str

    def fetch_order(self, order_ref: str) -> Order: ...
    def fetch_shipments(self, order_ref: str) -> list[Shipment]: ...
    def fetch_cases(self, order_ref: str) -> list[AftersalesCase]: ...
    def map_status(self, raw: str) -> OrderStatus: ...
    def execute_refund(self, case_id: str, amount_cents: int, approver_id: str) -> str: ...


TAOBAO_STATUS = {
    "WAIT_BUYER_PAY": OrderStatus.CREATED,
    "WAIT_SELLER_SEND_GOODS": OrderStatus.PAID,
    "WAIT_BUYER_CONFIRM_GOODS": OrderStatus.SHIPPED,
    "TRADE_SUCCESS": OrderStatus.DELIVERED,
    "TRADE_FINISHED": OrderStatus.DELIVERED,
    "TRADE_CLOSED": OrderStatus.CANCELLED,
}

DOUYIN_STATUS = {
    "0": OrderStatus.CREATED,
    "1": OrderStatus.PAID,
    "2": OrderStatus.SHIPPED,
    "3": OrderStatus.DELIVERED,
    "4": OrderStatus.CANCELLED,
}


class FixtureAdapter:
    """只对 fixtures/ 下的版本化快照工作；没有网络、没有 OAuth（NG-4）。"""

    def __init__(self, root: Path, platform: str):
        self.root = Path(root)
        self.platform = platform
        self._cache: dict[str, dict] = {}
        self._paths: dict[str, Path] = {}
        self.refund_calls: list[tuple[str, int, str]] = []

    # ---- 原始载荷 ----
    def _index(self) -> dict[str, Path]:
        """文件名是场景名，不是订单号。按 order.tid / order.order_id 建索引。"""
        if not self._paths:
            for path in sorted((self.root / self.platform).glob("*.json")):
                raw = json.loads(path.read_text(encoding="utf-8"))
                order = raw.get("order", {})
                ref = order.get("tid") or order.get("order_id")
                if ref:
                    self._paths[str(ref)] = path
        return self._paths

    def _load(self, order_ref: str) -> dict:
        if order_ref not in self._cache:
            path = self._index().get(order_ref)
            if path is None:
                raise DomainError(ErrorCode.ORDER_NOT_FOUND, f"无此订单快照: {order_ref}")
            self._cache[order_ref] = json.loads(path.read_text(encoding="utf-8"))
        return self._cache[order_ref]

    def map_status(self, raw: str) -> OrderStatus:
        table = TAOBAO_STATUS if self.platform == "taobao" else DOUYIN_STATUS
        return table.get(str(raw).strip(), OrderStatus.UNKNOWN)

    # ---- 归一化 ----
    def fetch_order(self, order_ref: str) -> Order:
        raw = self._load(order_ref)["order"]
        if self.platform == "taobao":
            return self._taobao_order(order_ref, raw)
        return self._douyin_order(order_ref, raw)

    def _taobao_order(self, ref: str, raw: dict) -> Order:
        status = self.map_status(raw.get("status", ""))
        items = [
            OrderItem(
                sku=str(it.get("sku_id", "")),
                title=str(it.get("title", "")),
                qty=int(it.get("num", 0) or 0),
                unit_cents=to_cents(it.get("price"), "cent"),
                category=str(it.get("category", "general")),
            )
            for it in raw.get("orders", [])
        ]
        shipments = [self._shipment(s) for s in self._raw_packages(raw)]
        signed = max((s.delivered_at for s in shipments if s.delivered_at), default=None)
        anomaly = status is OrderStatus.UNKNOWN or (
            status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED) and signed is None
        )
        return Order(
            order_ref=ref,
            status=status,
            paid_cents=to_cents(raw.get("payment"), "cent"),
            created_at=parse_dt(raw.get("created")) or _created_or_raise(raw),
            signed_at=signed,
            items=items,
            shipments=shipments,
            raw_ref=json.dumps(raw, ensure_ascii=False, sort_keys=True),
            platform_anomaly=anomaly,
        )

    def _douyin_order(self, ref: str, raw: dict) -> Order:
        status = self.map_status(raw.get("order_status", ""))
        items = [
            OrderItem(
                sku=str(it.get("sku_id", "")),
                title=str(it.get("title", "")),
                qty=int(it.get("num", 0) or 0),
                unit_cents=to_cents(it.get("price"), "yuan"),
                category=str(it.get("category", "general")),
            )
            for it in raw.get("product_items", [])
        ]
        shipments = [self._shipment(s) for s in self._raw_packages(raw)]
        signed = max((s.delivered_at for s in shipments if s.delivered_at), default=None)
        anomaly = status is OrderStatus.UNKNOWN or (
            status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED) and signed is None
        )
        return Order(
            order_ref=ref,
            status=status,
            paid_cents=to_cents(raw.get("pay_amount"), "yuan"),
            created_at=parse_dt(raw.get("create_time")) or _created_or_raise(raw),
            signed_at=signed,
            items=items,
            shipments=shipments,
            raw_ref=json.dumps(raw, ensure_ascii=False, sort_keys=True),
            platform_anomaly=anomaly,
        )

    def _raw_packages(self, raw: dict) -> list[dict]:
        # 两平台字段名不同，但都可能是 0..N 个包裹（AC02）
        pkgs = raw.get("logistics") or raw.get("packages") or []
        return list(pkgs)

    def _shipment(self, raw: dict) -> Shipment:
        return Shipment(
            package_id=str(raw.get("package_id") or raw.get("out_sid") or ""),
            carrier=str(raw.get("company") or raw.get("company_name") or ""),
            tracking_no=str(raw.get("tracking_no") or raw.get("out_sid") or ""),
            shipped_at=parse_dt(raw.get("ship_time") or raw.get("consign_time")),
            delivered_at=parse_dt(raw.get("receive_time") or raw.get("delivery_time")),
            items=[
                ShipmentItem(sku=str(i.get("sku_id", "")), qty=int(i.get("num", 0) or 0))
                for i in raw.get("items", [])
            ],
        )

    def fetch_shipments(self, order_ref: str) -> list[Shipment]:
        return self.fetch_order(order_ref).shipments

    # ---- 平台侧已有售后单 ----
    def fetch_cases(self, order_ref: str) -> list[AftersalesCase]:
        payload = self._load(order_ref)
        raw = payload.get("cases") or payload.get("order", {}).get("cases", [])
        out: list[AftersalesCase] = []
        for c in raw:
            case = AftersalesCase(
                case_id=str(c["aftersales_id"]),
                ticket_id="",
                order_ref=order_ref,
                type=_enum(AftersalesType, c.get("type", "refund_only"), "cases.type"),
                requested_cents=to_cents(c.get("amount"), "yuan" if self.platform == "douyin" else "cent"),
                status=_enum(CaseStatus, c.get("status", "INITIATED"), "cases.status"),
            )
            for ev in sorted(c.get("events", []), key=lambda e: str(e.get("at"))):
                case.append_event(
                    CaseEvent(
                        event_id="",
                        to_status=_enum(CaseStatus, ev.get("to", "INITIATED"), "cases.events.to"),
                        actor=str(ev.get("actor", "platform")),
                        at=parse_dt(ev.get("at")),
                    ),
                    idem_key=str(ev.get("key", "")),
                )
            out.append(case)
        return out

    # ---- 退款执行（mock，仍要求 approver） ----
    def execute_refund(self, case_id: str, amount_cents: int, approver_id: str) -> str:
        if not approver_id:
            raise DomainError(ErrorCode.CONFIRM_REQUIRED, "缺 approver_id")
        self.refund_calls.append((case_id, amount_cents, approver_id))
        return f"MOCK-REFUND-{case_id}"


def _created_or_raise(raw: dict):
    raise DomainError(ErrorCode.PLATFORM_ANOMALY, f"创建时间缺失: {raw.get('created') or raw.get('create_time')!r}")


def _enum(cls, value, field: str):
    """平台脏值不许直穿成 ValueError（那会变成 500）：统一报 E_PLATFORM_ANOMALY。"""
    try:
        return cls(value)
    except ValueError as exc:
        raise DomainError(ErrorCode.PLATFORM_ANOMALY, f"平台脏值 {field}={value!r}") from exc
