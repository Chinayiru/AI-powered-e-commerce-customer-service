from __future__ import annotations

import json

from app.main import create_app


def payload(message: str, *, order_no: str | None = None, category: str = "CONSULT", history=None):
    context = {
        "orderNo": order_no,
        "summary": f"客户诉求：{message[:80]}",
        "history": history or [],
    }
    return {
        "traceId": "trace-test",
        "ticketId": "T20261111000001",
        "requestId": "00000000-0000-4000-8000-000000000001",
        "attempt": 1,
        "taskEpoch": 1,
        "userId": "U001",
        "category": category,
        "message": message,
        "context": context,
    }


def post(client, auth, body, *, user_id: str = "U001"):
    return client.post("/internal/agent/ask", json=body, headers=auth(user_id))


def test_healthz_is_public(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_internal_endpoint_requires_identity(client):
    response = client.post("/internal/agent/ask", json=payload("订单 O1001 还能退吗"))
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_bad_signature_is_rejected(client, auth):
    headers = auth()
    headers["X-Internal-Identity"] = headers["X-Internal-Identity"] + "x"
    response = client.post("/internal/agent/ask", json=payload("订单 O1001 还能退吗"), headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_replayed_identity_is_rejected(client, auth):
    headers = auth()
    body = payload("订单 O1001 还能退吗", order_no="O1001")
    first = client.post("/internal/agent/ask", json=body, headers=headers)
    assert first.status_code == 200
    second = client.post("/internal/agent/ask", json=body, headers=headers)
    assert second.status_code == 401
    assert second.json()["code"] == "UNAUTHENTICATED"


def test_unknown_field_is_rejected(client, auth):
    body = payload("订单 O1001 还能退吗")
    body["unexpected"] = True
    response = post(client, auth, body)
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_ARGS"


def test_eligibility_is_informational_and_cites_policy(client, auth):
    response = post(client, auth, payload("订单 O1001 还能退吗", order_no="O1001"))
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "REFUND_ELIGIBILITY"
    assert body["replyType"] == "INFORMATIONAL"
    assert body["suggestedAction"] is None
    assert body["needHumanReview"] is False
    assert "¥58.00" in body["replyDraft"]
    assert "待发货" in body["replyDraft"]
    assert body["citations"]
    assert body["model"]["provider"] == "scripted"


def test_refund_question_is_eligibility_not_an_instruction(client, auth):
    response = post(client, auth, payload("我买的订单 O1001 想退款，怎么办？", order_no="O1001"))
    body = response.json()
    assert body["intent"] == "REFUND_ELIGIBILITY"
    assert body["replyType"] == "INFORMATIONAL"
    assert body["suggestedAction"] is None


def test_refund_request_returns_amount_and_review_for_large_amount(client, auth):
    response = post(client, auth, payload("那就帮我退了吧", order_no="O1001"))
    body = response.json()
    assert body["intent"] == "REFUND_REQUEST"
    assert body["replyType"] == "DECISIONAL"
    assert body["suggestedAction"]["action"] == "REFUND"
    assert body["suggestedAction"]["amountCents"] == 5800
    assert body["needHumanReview"] is True
    assert "未真实退款" in body["replyDraft"]


def test_small_amount_does_not_require_review(client, auth):
    response = post(client, auth, payload("我要退款", order_no="O1005"))
    body = response.json()
    assert body["suggestedAction"]["amountCents"] == 3000
    assert body["needHumanReview"] is False


def test_already_refunded_order_has_no_amount(client, auth):
    response = post(client, auth, payload("帮我退款", order_no="O1010"))
    body = response.json()
    assert body["suggestedAction"] is None
    assert body["needHumanReview"] is True
    assert "暂无可退金额" in body["replyDraft"]


def test_fuzzy_request_has_low_confidence_and_review(client, auth):
    response = post(
        client,
        auth,
        payload("那个东西不太行，你看看怎么弄", order_no="O1006", category="AFTERSALE"),
    )
    body = response.json()
    assert body["intent"] == "OTHER"
    assert body["confidence"] == 0.42
    assert body["needHumanReview"] is True


def test_safety_gate_turns_complaint_into_out_of_scope(client, auth):
    response = post(client, auth, payload("我要投诉你们，还要找 12315", order_no="O1001"))
    body = response.json()
    assert body["intent"] == "HANDOFF"
    assert body["transferReason"] == "OUT_OF_SCOPE"
    assert body["degraded"] is False


def test_explicit_human_request(client, auth):
    response = post(client, auth, payload("转人工，让真人跟我说"))
    body = response.json()
    assert body["intent"] == "HANDOFF"
    assert body["transferReason"] == "USER_REQUESTED"


def test_missing_order_is_a_slot_not_a_guess(client, auth):
    response = post(client, auth, payload("还能退吗"))
    body = response.json()
    assert body["slots"]["missing"] == ["orderNo"]
    assert body["slots"]["orderNo"] is None
    assert body["suggestedAction"] is None


def test_unknown_order_does_not_crash(client, auth):
    response = post(client, auth, payload("O9999 我要退款", order_no="O9999"))
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "REFUND_REQUEST"
    assert body["suggestedAction"] is None
    assert "没查到订单 O9999" in body["replyDraft"]


def test_tool_unavailable_degrades_to_tool_failed(client, auth):
    response = post(client, auth, payload("我要退款", order_no="O5000"))
    body = response.json()
    assert body["intent"] == "HANDOFF"
    assert body["transferReason"] == "TOOL_FAILED"
    assert body["degraded"] is True


def test_multiple_orders_are_ambiguous(client, auth):
    response = post(client, auth, payload("O1001 和 O1002 都退了吧"))
    body = response.json()
    assert body["intent"] == "HANDOFF"
    assert body["transferReason"] == "AMBIGUOUS_ORDER"


def test_policy_question_uses_policy_corpus(client, auth):
    response = post(client, auth, payload("退货运费谁出"))
    body = response.json()
    assert body["intent"] == "POLICY"
    assert body["replyType"] == "INFORMATIONAL"
    assert body["citations"][0]["docId"] == "return-shipping"
    assert "商家承担" in body["replyDraft"]


def test_logistics_uses_tool_facts(client, auth):
    response = post(client, auth, payload("发到哪了", order_no="O1002"))
    body = response.json()
    assert body["intent"] == "LOGISTICS"
    assert "MOCK002" in body["replyDraft"]
    assert "运输中" in body["replyDraft"]
    assert body["citations"][0]["docId"] == "logistics-sla"


def test_response_contract_is_strict_and_safe(client, auth):
    response = post(client, auth, payload("我要退款", order_no="O1001"))
    body = response.json()
    assert set(body).issubset(
        {
            "intent",
            "slots",
            "confidence",
            "replyType",
            "needHumanReview",
            "transferReason",
            "suggestedAction",
            "replyDraft",
            "citations",
            "degraded",
            "model",
        }
    )
    assert "policyCheck" not in body
    assert len(body["replyDraft"]) <= 200
    for banned in ("赔付", "赔偿", "保证", "一定", "百分百", "已退款", "已处理"):
        assert banned not in body["replyDraft"]
    assert "REFUND_REQUEST" not in body["replyDraft"]


def test_contract_shape_matches_java_slots(client, auth):
    response = post(client, auth, payload("我要退款", order_no="O1001"))
    body = response.json()
    assert set(body["slots"]) == {"orderNo", "missing"}
    dumped = json.dumps(body, ensure_ascii=False)
    assert "conditional" not in dumped
    assert "policyCheck" not in dumped
