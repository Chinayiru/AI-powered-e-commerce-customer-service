"""HTTP API 契约测试：前端控制台依赖的每个端点。

这些测试只验证"API 是 pipeline 的薄封装"：不复制业务规则，不额外放宽闸门。
RUNS_PATH 一律指向 tmp_path，避免污染 reports/runs.jsonl。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.server import DIST, app
from app.core.auth import OperatorConfigError
from app.eval.retrieval import THRESHOLD_PT


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_PATH", str(tmp_path / "runs.jsonl"))
    # 契约测试不联网：.env 可能配了真实模型，这里强制回台词provider
    monkeypatch.setenv("AFTERSALE_LLM_PROVIDER", "scripted")
    # 写接口要求已验证的操作人；token 只在测试里存在，不进记录
    monkeypatch.setenv("AFTERSALE_OPERATORS", "demo1:tok-demo1")
    headers = {"X-Operator-Id": "demo1", "X-Operator-Token": "tok-demo1"}
    with TestClient(app, headers=headers) as c:
        yield c


def test_write_requires_operator(client):
    """没有身份就不能跑单/回放：审批人必须来自已验证的调用方，不是请求体。"""
    anon = TestClient(app)
    assert anon.post("/api/runs", json={"fixture": "tb_1001"}).status_code == 401
    assert anon.post("/api/replay", json={"run_id": "run_x"}).status_code == 401
    assert anon.get("/api/runs").status_code == 200  # 读接口不要求身份
    bad = {"X-Operator-Id": "demo1", "X-Operator-Token": "wrong"}
    assert anon.post("/api/runs", json={"fixture": "tb_1001"}, headers=bad).status_code == 401
    # confirm 只能是当前操作人，不能替别人签
    assert (
        anon.post(
            "/api/runs",
            json={"fixture": "tb_1001", "confirm": "human:someone-else"},
            headers={"X-Operator-Id": "demo1", "X-Operator-Token": "tok-demo1"},
        ).status_code
        == 403
    )


def test_write_fails_closed_when_operators_unconfigured(tmp_path, monkeypatch):
    """没配操作人表就一律 503：宁可不可用，也不允许匿名审批。"""
    monkeypatch.setenv("RUNS_PATH", str(tmp_path / "runs.jsonl"))
    monkeypatch.setattr("app.api.server.load_operators", lambda *a, **k: {})
    anon = TestClient(app)
    res = anon.post("/api/runs", json={"fixture": "tb_1001"})
    assert res.status_code == 503
    assert "AFTERSALE_OPERATORS" in res.json()["detail"]

    # 配置本身坏了（格式错/重复 id）同样是 503，而不是"当成没配"或 500
    def boom(*_a, **_k):
        raise OperatorConfigError("AFTERSALE_OPERATORS 格式应为 id:token")

    monkeypatch.setattr("app.api.server.load_operators", boom)
    bad = anon.post("/api/runs", json={"fixture": "tb_1001"})
    assert bad.status_code == 503
    assert "配置有误" in bad.json()["detail"]


# ---- 元信息 ----
def test_health_and_meta(client):
    assert client.get("/api/health").json()["ok"] is True

    meta = client.get("/api/meta").json()
    assert meta["provider"] == "scripted"
    assert meta["model"] == "scripted-v1"
    assert meta["configured"] is False
    assert meta["policy"]["version"]
    assert meta["prompt_version"]
    assert meta["fixtures_count"] == 10
    assert meta["baseline"]["baseline"] == "v0"
    assert set(meta["baseline"]["ac_results"]) >= {"AC01", "AC26"}
    assert meta["retrieval"]["keyword"]["recall_at_5"] > 0
    # 阈值只有 app.eval.retrieval 一处定义；前端拿它做展示，不自己硬编码
    assert meta["retrieval_threshold"] == THRESHOLD_PT


# ---- fixtures：只暴露中立字段 ----
def test_fixtures_are_normalized(client):
    items = client.get("/api/fixtures").json()["items"]
    assert len(items) == 10
    assert {i["platform"] for i in items} == {"taobao", "douyin"}
    assert all(i["short"] for i in items)

    # AC04：平台原始载荷不得越出 adapter
    assert "raw_ref" not in json.dumps(items, ensure_ascii=False)

    by_short = {i["short"]: i for i in items}
    assert by_short["dy_2002"]["order"]["status"] == "UNKNOWN"
    assert by_short["dy_2002"]["order"]["platform_anomaly"] is True
    assert by_short["tb_1001"]["order"]["status"] == "PAID"


# ---- 跑单 ----
def test_run_refund_only_flows_to_closed(client):
    res = client.post("/api/runs", json={"fixture": "tb_1001"})
    assert res.status_code == 200
    record = res.json()["record"]
    out = record["out"]

    assert out["verdict"] == "approve"
    assert out["send_gate"] == "auto"
    assert out["stop_reason"] == "finalized"
    assert out["intent"] == "refund"
    # NG-1：没有确认人，草稿再干净也只能停在 REVIEWING，不能自动打款
    assert out["case"]["status"] == "REVIEWING"
    assert out["draft"]["text"]
    assert [t["name"] for t in out["tool_calls"]] == [
        "fetch_order",
        "llm.propose",
        "policy.evaluate",
    ]
    # 记录可审计
    assert record["prompt_version"] == out["prompt_version"]
    assert record["policy_version"] == out["policy_version"]


def test_confirm_executes_refund_after_human_gate(client):
    # dy_2001 金额进人工档 → send_gate=human；业务结论是 approve，但没有确认人只能停 REVIEWING
    draft = client.post("/api/runs", json={"fixture": "dy_2001"}).json()["record"]["out"]
    assert draft["send_gate"] == "human"
    assert draft["case"]["status"] == "REVIEWING"

    done = client.post("/api/runs", json={"fixture": "dy_2001", "confirm": "human:demo1"}).json()[
        "record"
    ]["out"]
    assert done["case"]["status"] == "CLOSED"
    assert done["case"]["platform_refund_id"]


def test_missing_evidence_never_closes_even_with_confirm(client):
    """P8：缺凭证是 undecided，人工确认也不能把它变成打款。"""
    done = client.post("/api/runs", json={"fixture": "tb_1002", "confirm": "human:demo1"}).json()[
        "record"
    ]["out"]
    assert done["verdict"] == "undecided"
    assert done["case"]["status"] == "REVIEWING"
    assert "R_MISSING_EVIDENCE" in done["reason_codes"]


def test_text_override_is_accepted(client):
    """前端可改写工单原文；当前 ScriptedProvider 按 order_ref 取固定剧本，
    所以这里只断言请求被接受、记录仍可复现，不断言意图会随文本变化。"""
    out = client.post(
        "/api/runs",
        json={"fixture": "tb_1001", "text": "麻烦帮我改一下收货地址"},
    ).json()["record"]["out"]
    assert out["verdict"] in {"approve", "undecided"}
    assert out["run_id"]


def test_run_records_llm_choice(client):
    """记录里要能看出这次用的是哪个 provider/model，回放才有依据。"""
    record = client.post("/api/runs", json={"fixture": "tb_1001", "provider": "scripted"}).json()["record"]
    assert record["llm"]["provider"] == "scripted"
    assert record["llm"]["model"] == "scripted-v1"
    assert record["out"]["run_id"] == record["run_id"]
    # 未知 provider 在前端就是参数错误，不落到 pipeline 里再炸
    assert client.post("/api/runs", json={"fixture": "tb_1001", "provider": "bogus"}).status_code == 422


def test_bad_requests(client):
    assert client.post("/api/runs", json={"fixture": "nope"}).status_code == 404
    assert client.post("/api/runs", json={"fixture": "tb_1001", "text": "   "}).status_code == 422

    res = client.post("/api/runs", json={"fixture": "tb_1001", "budget": 0})
    assert res.status_code == 422
    # 前端要能把这层结构读成人话：detail 是数组，不是字符串
    detail = res.json()["detail"]
    assert isinstance(detail, list) and detail[0]["loc"][-1] == "budget"


# ---- 记录 / 回放 ----
def test_runs_are_listed_and_fetchable(client):
    created = client.post("/api/runs", json={"fixture": "tb_1001"}).json()["record"]

    listing = client.get("/api/runs").json()
    assert listing["total"] == 1
    assert listing["items"][0]["run_id"] == created["run_id"]

    one = client.get(f"/api/runs/{created['run_id']}").json()["record"]
    assert one["out"]["run_id"] == created["run_id"]
    assert client.get("/api/runs/run_missing").status_code == 404


def test_client_token_deduplicates_retry(client):
    """同一 client_token 的重试/双击只落一条记录，避免重复打款。"""
    payload = {"fixture": "tb_1002", "client_token": "tok-retry-1"}
    first = client.post("/api/runs", json=payload).json()
    assert first.get("deduplicated") is not True
    assert first["record"]["client_token"] == "tok-retry-1"

    again = client.post("/api/runs", json=payload).json()
    assert again["deduplicated"] is True
    assert again["record"]["run_id"] == first["record"]["run_id"]
    assert client.get("/api/runs").json()["total"] == 1

    # 新 token 是新的用户动作，正常再落一条
    other = client.post("/api/runs", json={**payload, "client_token": "tok-retry-2"}).json()
    assert "deduplicated" not in other
    assert other["record"]["client_token"] == "tok-retry-2"
    tokens = {r["client_token"] for r in client.get("/api/runs").json()["items"]}
    assert tokens == {"tok-retry-1", "tok-retry-2"}
    # token 是前端生成的不透明串，格式不对直接 422，不进 pipeline
    assert client.post("/api/runs", json={"fixture": "tb_1001", "client_token": "bad token!"}).status_code == 422


def test_replay_has_no_drift(client):
    created = client.post("/api/runs", json={"fixture": "dy_2001"}).json()["record"]
    replay = client.post("/api/replay", json={"run_id": created["run_id"]}).json()

    assert replay["drift"] == []
    assert replay["prompt_version"] == created["prompt_version"]
    assert replay["policy_version"] == created["policy_version"]
    assert client.post("/api/replay", json={"run_id": "run_missing"}).status_code == 404


# ---- 静态前端 ----
def test_spa_routes(client):
    root = client.get("/")
    assert root.status_code in (200, 503)  # 未构建时明确 503，而不是 404 噪音

    if (DIST / "index.html").exists():
        assert client.get("/runs").status_code == 200
        assert client.get("/api/unknown").status_code == 404
