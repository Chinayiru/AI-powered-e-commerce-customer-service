"""End-to-end smoke test: Java control plane + Python AI layer, both live.

Prerequisites (both must already be running):
    cd python && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    cd java   && java -jar target/aftersale-agent-java-0.1.0-SNAPSHOT.jar \
                   --app.agent.mode=http --app.agent.base-url=http://127.0.0.1:8000

Usage:
    python scripts/e2e_smoke.py [--java http://127.0.0.1:8080] [--python http://127.0.0.1:8000]

It walks five real conversations through the public API and prints a
pass/fail table. Exit code is 1 if any functional check failed, 0 otherwise.
Read-only against the codebase; it only calls HTTP endpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

AGENT_TOKEN = "demo-agent-token"
HMAC_SECRET = "dev-only-hmac-secret-change-me-please"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def call(method: str, url: str, body: object | None = None, headers: dict[str, str] | None = None):
    data = None
    hdrs = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json; charset=utf-8"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, _maybe_json(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, _maybe_json(raw)


def _maybe_json(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def rid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def check_single_error(status: int, payload, want_status: int, want_code: str, name: str) -> None:
    code = payload.get("code") if isinstance(payload, dict) else None
    record(name, status == want_status and code == want_code,
           f"status={status} code={code}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--java", default="http://127.0.0.1:8080")
    ap.add_argument("--python", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    java, py = args.java.rstrip("/"), args.python.rstrip("/")

    # ---------- 0. health ----------
    status, body = call("GET", f"{java}/actuator/health")
    record("java health", status == 200 and body.get("status") == "UP", f"status={status}")
    status, body = call("GET", f"{py}/healthz")
    record("python health", status == 200 and body.get("status") == "ok", f"status={status}")
    if any(not ok for _, ok, _ in RESULTS):
        print("\n服务未就绪，终止。")
        return 1

    # ---------- 1. Python AI 层直连（校验 HMAC 身份 + 契约字段） ----------
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "python"))
    from app.identity import issue_identity  # noqa: E402

    ask_body = {
        "traceId": rid("trace"),
        "ticketId": "T-E2E-001",
        "requestId": rid("req"),
        "attempt": 0,
        "taskEpoch": 0,
        "userId": "U001",
        "category": "AFTERSALE",
        "message": "O1001这个我不要了，帮我退了",
        "context": {"orderNo": None, "summary": None, "history": []},
    }
    identity = issue_identity("system", "system", HMAC_SECRET)
    status, body = call("POST", f"{py}/internal/agent/ask", ask_body,
                        {"X-Internal-Identity": identity})
    ok = (status == 200 and body.get("intent") == "REFUND_REQUEST"
          and isinstance(body.get("suggestedAction"), dict)
          and "policyCheck" not in body)
    record("python ask 直连", ok,
           f"status={status} intent={body.get('intent')} conf={body.get('confidence')} "
           f"action={body.get('suggestedAction', {}).get('action')} "
           f"citations={len(body.get('citations') or [])}")
    record("python 不收 policyCheck", "policyCheck" not in body, f"keys={sorted(body)}")

    status, body = call("POST", f"{py}/internal/agent/ask", ask_body)
    check_single_error(status, body, 401, "UNAUTHENTICATED", "python 缺身份头 401")

    # ---------- 2. 售后主链路：建单 → 坐席视图 → 发送 → 幂等重放 → 关闭 ----------
    create = {"category": "AFTERSALE", "text": "这个订单我不要了，帮我退款", "orderNo": "O1001",
              "requestId": rid("create")}
    status, created = call("POST", f"{java}/api/tickets", create, {"X-User-Id": "U001"})
    ticket_id, token = created.get("ticketId"), created.get("ticketToken")
    record("建单 AFTERSALE", status == 201 and created.get("displayState") == "处理中",
           f"status={status} state={created.get('displayState')} version={created.get('version')} "
           f"mode={created.get('executionMode')}")
    auth = {"Authorization": f"Bearer {token}"}
    agent = {"X-Agent-Token": AGENT_TOKEN}

    status, view = call("GET", f"{java}/api/agent/tickets/{ticket_id}", None, agent)
    draft = view.get("draft") or {}
    citations = draft.get("citations") or []
    latency = [tc.get("latencyMs") for tc in view.get("toolCalls") or []]
    record("坐席视图（含 AI 产出）",
           status == 200 and bool(draft.get("replyDraft")) and view.get("intent") == "REFUND_REQUEST",
           f"status={status} intent={view.get('intent')} conf={view.get('confidence')} "
           f"needReview={view.get('needHumanReview')} action={(draft.get('suggestedAction') or {}).get('action')}")
    record("AI 引用与 policyCheck 落库", bool(citations) and (view.get("policyCheck") or {}).get("allowed") is not None,
           f"citations={[c.get('clauseId') for c in citations]} "
           f"policy.allowed={(view.get('policyCheck') or {}).get('allowed')} "
           f"maxRefund={(view.get('policyCheck') or {}).get('maxRefundableCents')}")
    record("工具调用延迟非零", bool(latency) and all((v or 0) > 0 for v in latency),
           f"toolCalls={[(tc.get('name'), tc.get('latencyMs'), tc.get('ok')) for tc in view.get('toolCalls') or []]}")

    status, cview = call("GET", f"{java}/api/tickets/{ticket_id}", None, auth)
    record("消费者视图白名单",
           status == 200 and "intent" not in cview and "draft" not in cview
           and "toolCalls" not in cview and cview.get("displayState") == "处理中",
           f"status={status} keys={sorted(cview)}")

    version = view["ticket"]["version"]
    draft_version = draft["draftVersion"]
    send = {"text": draft["replyDraft"], "draftVersion": draft_version,
            "reviewNote": "已人工复核，客户订单在七天无理由期内",
            "expectedVersion": version, "requestId": rid("send")}
    status, sent = call("POST", f"{java}/api/agent/tickets/{ticket_id}/send", send, agent)
    record("send 批准并执行", status == 200 and sent.get("state") == "CLOSED",
           f"status={status} state={sent.get('state')} version={sent.get('version')} "
           f"edited={sent.get('edited')} editDistance={sent.get('editDistance')}")

    status, replay = call("POST", f"{java}/api/agent/tickets/{ticket_id}/send", send, agent)
    record("send 幂等重放", status == 200 and replay == sent,
           f"status={status} same_body={replay == sent}")

    status, cview = call("GET", f"{java}/api/tickets/{ticket_id}", None, auth)
    last_agent = [m for m in cview.get("messages") or [] if m.get("role") == "AGENT"]
    record("消费者看到关闭与坐席回复",
           status == 200 and cview.get("displayState") == "已完成" and bool(cview.get("reply")),
           f"state={cview.get('displayState')} reply={cview.get('reply')} agentMsgs={len(last_agent)}")

    # ---------- 3a. 咨询自动回复（物流类，不需人工） ----------
    status, created = call("POST", f"{java}/api/tickets",
                           {"category": "CONSULT", "text": "O1002我的快递到哪儿了，一直没到",
                            "orderNo": "O1002", "requestId": rid("create")},
                           {"X-User-Id": "U001"})
    consult_id, consult_token = created.get("ticketId"), created.get("ticketToken")
    consult_auth = {"Authorization": f"Bearer {consult_token}"}
    status, cview = call("GET", f"{java}/api/tickets/{consult_id}", None, consult_auth)
    record("咨询单直接回复（无需坐席）",
           status == 200 and cview.get("displayState") == "已回复" and bool(cview.get("reply")),
           f"state={cview.get('displayState')} reply={(cview.get('reply') or '')[:48]}")

    # ---------- 3b. 低置信 → 转人工 → 坐席回复 → 关闭 ----------
    status, created = call("POST", f"{java}/api/tickets",
                           {"category": "CONSULT", "text": "你们公司今年营收多少", "requestId": rid("create")},
                           {"X-User-Id": "U001"})
    low_id, low_token = created.get("ticketId"), created.get("ticketToken")
    low_auth = {"Authorization": f"Bearer {low_token}"}
    status, lowview = call("GET", f"{java}/api/agent/tickets/{low_id}", None, agent)
    reason = lowview["ticket"].get("transferReason")
    record("低置信自动转人工",
           status == 200 and lowview["ticket"]["state"] == "TRANSFERRED" and reason == "LOW_CONFIDENCE",
           f"state={lowview['ticket']['state']} reason={reason}")

    status, rp = call("POST", f"{java}/api/agent/tickets/{low_id}/reply",
                      {"text": "您好，营收数据不在售后服务范围内，已为您记录诉求。",
                       "expectedVersion": lowview["ticket"]["version"], "requestId": rid("reply")}, agent)
    record("坐席回复已转人工工单", status == 200 and rp.get("state") == "REPLIED",
           f"status={status} state={rp.get('state')}")
    status, cl = call("POST", f"{java}/api/agent/tickets/{low_id}/close",
                      {"expectedVersion": rp.get("version"), "requestId": rid("close")}, agent)
    record("关闭工单", status == 200 and cl.get("state") == "CLOSED",
           f"status={status} state={cl.get('state')}")
    status, cview = call("GET", f"{java}/api/tickets/{low_id}", None, low_auth)
    record("消费者看到人工回复",
           cview.get("displayState") == "已完成" and "营收" in (cview.get("reply") or ""),
           f"state={cview.get('displayState')} reply={(cview.get('reply') or '')[:40]}")

    # ---------- 4. 咨询转售后（AC20）：建单即转，凭据必须指向新售后单 ----------
    status, conv = call("POST", f"{java}/api/tickets",
                        {"category": "CONSULT", "text": "我要把 O1005 这笔退掉，不想要了",
                         "orderNo": "O1005", "requestId": rid("create")},
                        {"X-User-Id": "U001"})
    conv_auth = {"Authorization": f"Bearer {conv.get('ticketToken')}"}
    status2, conv_view = call("GET", f"{java}/api/tickets/{conv.get('ticketId')}", None, conv_auth)
    record("咨询转售后：返回新售后单凭据",
           status == 201 and conv.get("category") == "AFTERSALE" and status2 == 200,
           f"status={status} category={conv.get('category')} newTicket={conv.get('ticketId')} "
           f"view={conv_view.get('displayState')}")

    # ---------- 4b. 咨询追加消息触发转售后（AC20 的另一条入口） ----------
    status, conv2 = call("POST", f"{java}/api/tickets",
                         {"category": "CONSULT", "text": "退货运费谁承担？", "orderNo": "O1007",
                          "requestId": rid("create")}, {"X-User-Id": "U001"})
    conv2_auth = {"Authorization": f"Bearer {conv2.get('ticketToken')}"}
    status, msg_result = call("POST", f"{java}/api/tickets/{conv2.get('ticketId')}/messages",
                              {"text": "那我直接退掉吧，帮我退", "requestId": rid("msg")}, conv2_auth)
    created_ticket = (msg_result or {}).get("createdTicket") or {}
    record("咨询追问退款：messages 回传 createdTicket",
           status == 200 and created_ticket.get("category") == "AFTERSALE"
           and bool(created_ticket.get("ticketToken")),
           f"status={status} created={created_ticket.get('ticketId')} "
           f"state={created_ticket.get('displayState')}")

    # ---------- 5. 负向：鉴权 / 越权 / 版本冲突 / 终态不可再发消息 ----------
    status, body = call("POST", f"{java}/api/agent/tickets/{ticket_id}/send", send)
    check_single_error(status, body, 401, "UNAUTHENTICATED", "缺坐席凭证 401")

    other = call("POST", f"{java}/api/tickets",
                 {"category": "AFTERSALE", "text": "退款", "orderNo": "O1006",
                  "requestId": rid("create")}, {"X-User-Id": "U002"})
    other_ticket = other[1].get("ticketId")
    status, body = call("GET", f"{java}/api/tickets/{other_ticket}", None, auth)
    check_single_error(status, body, 403, "FORBIDDEN_SCOPE", "他人 ticketToken 越权 403")

    status, body = call("POST", f"{java}/api/tickets/{ticket_id}/messages",
                        {"text": "还在吗", "requestId": rid("msg")}, auth)
    check_single_error(status, body, 409, "STATE_NOT_ALLOWED", "已关闭工单再发消息 409")

    status, body = call("POST", f"{java}/api/tickets",
                        {"category": "AFTERSALE", "text": "x", "orderNo": "O1001"}, {"X-User-Id": "U001"})
    check_single_error(status, body, 422, "INVALID_ARGS", "缺 requestId 422")

    status, body = call("POST", f"{java}/api/tickets",
                        {"category": "AFTERSALE", "text": "我要退款", "orderNo": "O9999",
                         "requestId": rid("create")}, {"X-User-Id": "U001"})
    check_single_error(status, body, 404, "ORDER_NOT_FOUND", "非本人/不存在订单 404")

    status, orders = call("GET", f"{java}/api/me/orders", None, {"X-User-Id": "U001"})
    record("我的订单列表", status == 200 and isinstance(orders, list) and len(orders) > 0,
           f"status={status} count={len(orders) if isinstance(orders, list) else 'n/a'}")

    # ---------- 汇总 ----------
    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 72)
    print(f"共 {len(RESULTS)} 项检查，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}")
    if failed:
        print("失败项：" + "；".join(failed))
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
