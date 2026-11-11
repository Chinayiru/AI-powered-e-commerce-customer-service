from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent import AgentService
from app.config import Settings
from app.identity import issue_identity
from app.main import create_app
from app.tools import ToolUnavailable


class FakeTools:
    def __init__(self) -> None:
        self.orders = {
            "O1001": {
                "orderNo": "O1001",
                "userId": "U001",
                "status": "PAID",
                "amountCents": 5800,
                "refundedAmountCents": 0,
                "refundableAmountCents": 5800,
                "paidAt": "2026-11-01T10:00:00+08:00",
                "deliveredAt": None,
            },
            "O1002": {
                "orderNo": "O1002",
                "userId": "U001",
                "status": "SHIPPED",
                "amountCents": 12900,
                "refundedAmountCents": 0,
                "refundableAmountCents": 12900,
                "paidAt": "2026-11-05T10:00:00+08:00",
                "deliveredAt": None,
            },
            "O1003": {
                "orderNo": "O1003",
                "userId": "U001",
                "status": "DELIVERED",
                "amountCents": 8800,
                "refundedAmountCents": 0,
                "refundableAmountCents": 8800,
                "paidAt": "2026-09-20T10:00:00+08:00",
                "deliveredAt": "2026-10-01T10:00:00+08:00",
            },
            "O1005": {
                "orderNo": "O1005",
                "userId": "U001",
                "status": "PAID",
                "amountCents": 3000,
                "refundedAmountCents": 0,
                "refundableAmountCents": 3000,
                "paidAt": "2026-11-02T10:00:00+08:00",
                "deliveredAt": None,
            },
            "O1006": {
                "orderNo": "O1006",
                "userId": "U001",
                "status": "PAID",
                "amountCents": 25000,
                "refundedAmountCents": 0,
                "refundableAmountCents": 25000,
                "paidAt": "2026-11-03T10:00:00+08:00",
                "deliveredAt": None,
            },
            "O1007": {
                "orderNo": "O1007",
                "userId": "U001",
                "status": "DELIVERED",
                "amountCents": 6600,
                "refundedAmountCents": 0,
                "refundableAmountCents": 6600,
                "paidAt": "2026-11-01T10:00:00+08:00",
                "deliveredAt": "2026-11-10T10:00:00+08:00",
            },
            "O1010": {
                "orderNo": "O1010",
                "userId": "U001",
                "status": "DELIVERED",
                "amountCents": 5000,
                "refundedAmountCents": 5000,
                "refundableAmountCents": 0,
                "paidAt": "2026-10-01T10:00:00+08:00",
                "deliveredAt": "2026-10-05T10:00:00+08:00",
            },
            "O1012": {
                "orderNo": "O1012",
                "userId": "U001",
                "status": "CLOSED",
                "amountCents": 4500,
                "refundedAmountCents": 0,
                "refundableAmountCents": 0,
                "paidAt": "2026-09-01T10:00:00+08:00",
                "deliveredAt": None,
            },
        }
        self.shipments = {
            "O1002": {
                "orderNo": "O1002",
                "status": "IN_TRANSIT",
                "shipments": [
                    {
                        "carrierCode": "MOCK",
                        "trackingNo": "MOCK002",
                        "status": "IN_TRANSIT",
                        "events": [
                            {
                                "at": "2026-11-09T09:00:00+08:00",
                                "code": "ARRIVED",
                                "text": "到达分拨中心",
                            }
                        ],
                    }
                ],
            }
        }

    def query_order(self, user_id: str, order_no: str) -> dict[str, Any] | None:
        if order_no == "O5000":
            raise ToolUnavailable("TOOL_UNAVAILABLE", "boom")
        return self.orders.get(order_no)

    def get_logistics(self, user_id: str, order_no: str) -> dict[str, Any] | None:
        if order_no == "O5001":
            raise ToolUnavailable("TOOL_TIMEOUT", "timeout")
        return self.shipments.get(order_no)


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        java_base_url="http://localhost:8080",
        hmac_secret="test-secret",
        tool_timeout_seconds=1.0,
        tool_retries=1,
        confidence_threshold=0.60,
        auto_suggest_limit_cents=5000,
        return_window_days=7,
        policy_version="2026-11",
        prompt_version="p1.0.0",
        provider="scripted",
    )


@pytest.fixture()
def fake_tools() -> FakeTools:
    return FakeTools()


@pytest.fixture()
def client(settings: Settings, fake_tools: FakeTools) -> TestClient:
    service = AgentService(settings, fake_tools)  # type: ignore[arg-type]
    return TestClient(create_app(service=service, settings=settings))


@pytest.fixture()
def auth(settings: Settings):
    def headers(user_id: str = "U001") -> dict[str, str]:
        return {
            "X-Internal-Identity": issue_identity(user_id, "agent", settings.hmac_secret),
            "X-Trace-Id": "trace-test",
        }

    return headers
