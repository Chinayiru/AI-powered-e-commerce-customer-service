"""生成脏数据快照。fixtures 是**版本化输入**，改这里等于换基线（ACCEPTANCE §3.2）。

故意保留的平台差异：
- 淘宝金额是分(string)，抖店金额是元(string "12.30")
- 淘宝状态是英文常量，抖店是数字字符串，且存在 ""
- 一单可能有 0/1/N 个包裹，允许部分签收
- 时间可能是 "YYYY-MM-DD HH:MM:SS"（平台本地 +08）或 ISO8601，或缺省 ""
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def tb(tid: str, status: str, payment: str, created: str, items: list[dict], logistics: list[dict] | None = None, **extra) -> dict:
    return {
        "fixture_version": "2026-11-09.1",
        "platform": "taobao",
        "order": {
            "tid": tid,
            "status": status,
            "payment": payment,
            "created": created,
            "orders": items,
            "logistics": logistics or [],
            **extra,
        },
    }


def dy(oid: str, status: str, pay_amount: str, create_time: str, items: list[dict], logistics: list[dict] | None = None, **extra) -> dict:
    return {
        "fixture_version": "2026-11-09.1",
        "platform": "douyin",
        "order": {
            "order_id": oid,
            "order_status": status,
            "pay_amount": pay_amount,
            "create_time": create_time,
            "product_items": items,
            "logistics": logistics or [],
            **extra,
        },
    }


def item(sku: str, title: str, num: int, price: str, category: str = "general") -> dict:
    return {"sku_id": sku, "title": title, "num": num, "price": price, "category": category}


TB_FIXTURES = {
    # AC06：未发货、50 元整，落在自动线以内
    "tb_1001_unship_cents": tb(
        "TB1001", "WAIT_SELLER_SEND_GOODS", "5000", "2026-11-08T19:00:00+08:00",
        [item("SKU-CUP", "保温杯 500ml", 1, "5000")],
    ),
    # AC02：一单两包裹，B 未签收
    "tb_1002_multi_pkg": tb(
        "TB1002", "TRADE_SUCCESS", "8900", "2026-10-28T10:00:00+08:00",
        [item("SKU-A", "马克杯", 1, "3900"), item("SKU-B", "托盘", 1, "5000")],
        [
            {"package_id": "PKG-A", "company": "中通", "out_sid": "ZT001", "consign_time": "2026-11-01 10:00:00", "delivery_time": "2026-11-03 12:00:00", "items": [{"sku_id": "SKU-A", "num": 1}]},
            {"package_id": "PKG-B", "company": "圆通", "out_sid": "YT002", "consign_time": "2026-11-04 09:00:00", "delivery_time": "", "items": [{"sku_id": "SKU-B", "num": 1}]},
        ],
    ),
    # AC08：签收 11 天，超出 7 天售后期
    "tb_1003_over_window": tb(
        "TB1003", "TRADE_SUCCESS", "6800", "2026-10-20T10:00:00+08:00",
        [item("SKU-D", "台灯", 1, "6800")],
        [{"package_id": "PKG-1", "company": "顺丰", "out_sid": "SF003", "consign_time": "2026-10-28 10:00:00", "delivery_time": "2026-10-30 09:00:00"}],
    ),
    # AC09：少件，申请部分退款 20 元（实付 89）
    "tb_1004_partial": tb(
        "TB1004", "TRADE_SUCCESS", "8900", "2026-11-01T10:00:00+08:00",
        [item("SKU-E", "杯子 x2", 2, "3450"), item("SKU-F", "杯垫", 1, "2000")],
        [{"package_id": "PKG-1", "company": "韵达", "out_sid": "YD004", "consign_time": "2026-11-04 10:00:00", "delivery_time": "2026-11-06 14:00:00"}],
    ),
    # AC14：威胁 + 金额超线
    "tb_1005_threat": tb(
        "TB1005", "TRADE_SUCCESS", "6800", "2026-11-02T10:00:00+08:00",
        [item("SKU-G", "电水壶", 1, "6800")],
        [{"package_id": "PKG-1", "company": "中通", "out_sid": "ZT005", "consign_time": "2026-11-05 10:00:00", "delivery_time": "2026-11-08 11:00:00"}],
    ),
    # AC13：数字类目，自动阈值 0 且排除
    "tb_1006_digital": tb(
        "TB1006", "TRADE_SUCCESS", "19900", "2026-11-02T10:00:00+08:00",
        [item("SKU-H", "虚拟会员年卡", 1, "19900", "digital")],
        [{"package_id": "PKG-1", "company": "虚拟发货", "out_sid": "V001", "consign_time": "2026-11-02 10:05:00", "delivery_time": "2026-11-07 10:05:00"}],
    ),
}

DY_FIXTURES = {
    # AC07：已签收 120 元（元字符串），超 50 强制人工
    "dy_2001_delivered_yuan": dy(
        "DY2001", "3", "120.00", "2026-11-01 09:00:00",
        [item("SKU-B", "蓝牙耳机", 1, "120.00")],
        [{"package_id": "PKG1", "company": "中通", "tracking_no": "ZT123", "ship_time": "2026-11-02 10:00:00", "receive_time": "2026-11-05 15:00:00"}],
    ),
    # AC03：状态为空、签收时间缺失
    "dy_2002_missing_state": dy(
        "DY2002", "", "99.00", "2026-11-03 09:00:00",
        [item("SKU-I", "手机壳", 1, "99.00")],
        [{"package_id": "PKG1", "company": "极兔", "tracking_no": "JT900", "ship_time": "", "receive_time": ""}],
    ),
    # AC05：平台同一事件推了两次
    "dy_2003_dup_events": dy(
        "DY2003", "3", "30.00", "2026-11-02 09:00:00",
        [item("SKU-J", "数据线", 1, "30.00")],
        [{"package_id": "PKG1", "company": "中通", "tracking_no": "ZT900", "ship_time": "2026-11-03 10:00:00", "receive_time": "2026-11-06 18:00:00"}],
        cases=[
            {
                "aftersales_id": "AS2003",
                "type": "refund_only",
                "status": "INITIATED",
                "amount": "30.00",
                "events": [
                    {"key": "apply", "at": "2026-11-07 10:00:00", "to": "INITIATED", "actor": "platform"},
                    {"key": "apply", "at": "2026-11-07 10:00:00", "to": "INITIATED", "actor": "platform"},
                ],
            }
        ],
    ),
    # AC10：退货退款
    "dy_2004_return": dy(
        "DY2004", "3", "260.00", "2026-11-01 09:00:00",
        [item("SKU-K", "羽绒服", 1, "260.00")],
        [{"package_id": "PKG1", "company": "顺丰", "tracking_no": "SF900", "ship_time": "2026-11-02 10:00:00", "receive_time": "2026-11-06 16:00:00"}],
    ),
}


def main() -> None:
    written = []
    for name, payload in {**TB_FIXTURES}.items():
        path = ROOT / "taobao" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    for name, payload in DY_FIXTURES.items():
        path = ROOT / "douyin" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    print(f"wrote {len(written)} fixtures")


if __name__ == "__main__":
    main()
