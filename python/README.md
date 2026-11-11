# Python AI 层（售后 Agent）

只读的意图 / 槽位 / 检索 / 草稿服务。它不连数据库、不写工单、不执行退款，也不返回 `policyCheck`；金额与政策结论由 Java 规则引擎裁决。

## 快速开始

```powershell
cd H:\电商工单ai\python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q

# 启动（默认 127.0.0.1:8000）
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
curl.exe http://127.0.0.1:8000/healthz
```

## 与 Java 联调

Python 调用 Java 的 `/internal/tools/queryOrder` 与 `/internal/tools/getLogistics`，Java 调用本服务的 `/internal/agent/ask`。两边共用 `app.security.hmac-secret` / `AFTERSALE_HMAC_SECRET`。

```powershell
# 1) 启动 Java（HTTP 模式）
cd H:\电商工单ai\java
java -jar target\aftersale-agent-java-0.1.0-SNAPSHOT.jar --app.agent.mode=http

# 2) 启动 Python
cd H:\电商工单ai\python
$env:AFTERSALE_HMAC_SECRET="dev-only-hmac-secret-change-me-please"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Java 默认配置：

```yaml
app:
  agent:
    mode: http
    base-url: http://localhost:8000
    timeout-ms: 8000
```

> Java 的 `HttpAgentClient` 使用严格 Jackson（未知字段即失败）。因此本服务的响应字段必须与 `docs/api/openapi.yaml` 完全一致，尤其不能返回 `slots.conditional` 或 `policyCheck`。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AFTERSALE_JAVA_BASE_URL` | `http://localhost:8080` | Java 工具服务地址 |
| `AFTERSALE_HMAC_SECRET` | `dev-only-hmac-secret-change-me-please` | 内部 HMAC 共享密钥 |
| `AFTERSALE_TOOL_TIMEOUT_SECONDS` | `1.0` | 单次工具调用超时 |
| `AFTERSALE_TOOL_RETRIES` | `1` | 超时/503/504 重试次数 |
| `AFTERSALE_CONFIDENCE_THRESHOLD` | `0.60` | 低置信阈值 |
| `AFTERSALE_AUTO_SUGGEST_LIMIT_CENTS` | `5000` | 免复核金额上限（分） |
| `AFTERSALE_RETURN_WINDOW_DAYS` | `7` | 无理由退货窗口 |
| `AFTERSALE_POLICY_VERSION` | `2026-11` | 政策版本 |
| `AFTERSALE_PROMPT_VERSION` | `p1.0.0` | 提示词/规则版本 |
| `AFTERSALE_AGENT_PROVIDER` | `scripted` | 响应中的 provider 标识 |

## 接口

### `POST /internal/agent/ask`

必须带 `X-Internal-Identity`。格式与 Java 一致：

```text
base64url(JSON{"userId","role","exp","nonce"}) + "." + base64url(HMAC_SHA256(payload))
```

示例请求：

```json
{
  "traceId": "trace-1",
  "ticketId": "T20261111000001",
  "requestId": "00000000-0000-4000-8000-000000000001",
  "attempt": 1,
  "taskEpoch": 1,
  "userId": "U001",
  "category": "CONSULT",
  "message": "订单 O1001 还能退吗",
  "context": {
    "orderNo": "O1001",
    "summary": "客户咨询退款",
    "history": []
  }
}
```

响应示例：

```json
{
  "intent": "REFUND_ELIGIBILITY",
  "slots": {"orderNo": "O1001", "missing": []},
  "confidence": 0.9,
  "replyType": "INFORMATIONAL",
  "needHumanReview": false,
  "transferReason": null,
  "suggestedAction": null,
  "replyDraft": "查到了：订单 O1001，待发货，实付 ¥58.00，可退 ¥58.00。未发货可申请仅退款；七天无理由自签收次日起算。[refund-policy#3.1]",
  "citations": [
    {
      "docId": "refund-policy",
      "title": "七天无理由与退款适用范围",
      "clauseId": "3.1",
      "policyVersion": "2026-11"
    }
  ],
  "degraded": false,
  "model": {"provider": "scripted", "promptVersion": "p1.0.0"}
}
```

## 规则要点

- 安全闸优先：投诉 / 12315 / 律师 / 监管 / 人身安全 → `HANDOFF(OUT_OF_SCOPE)`。
- 明确退款动作 → `REFUND_REQUEST`；条件式“能退的话就退了吧”也按请求处理。
- 明确要人工 → `HANDOFF(USER_REQUESTED)`；越界诉求（换货、价保、改地址、发票、赔偿）→ `OUT_OF_SCOPE`。
- 政策 / 物流 / 退款资格分别走检索与工具事实。
- 退款金额只取 `refundableAmountCents`；可退为 0 时不返回金额，并标记需人工复核。
- 金额 > 5000 分 → `needHumanReview=true`。
- 工具超时或 503/504：重试 1 次，仍失败 → `HANDOFF(TOOL_FAILED)` + `degraded=true`。
- 响应 `replyDraft` 不超过 200 字，不含“赔付 / 保证 / 已退款”等禁用表述。
- 无命中模糊文本 → `OTHER` + `confidence=0.42` + `needHumanReview=true`，有效订单仍给安全草稿。

## 测试

`tests/test_agent.py` 覆盖 21 个场景：鉴权、签名/nonce 重放、严格字段、意图、槽位、金额、复核、低置信、安全闸、转人工、多订单、工具失败、政策引用、物流、响应安全与契约形状。测试使用 `FakeTools`，不依赖 Java 进程。

## 目录

```text
python/
  app/
    contracts.py   # Pydantic 请求/响应模型（严格）
    config.py      # 环境变量
    identity.py    # HMAC 身份签发/校验 + nonce
    tools.py       # Java 内部工具客户端
    intent.py      # 规则意图与槽位
    knowledge.py   # 政策语料 + 词法检索
    agent.py       # 编排与草稿
    main.py        # FastAPI
  tests/
    conftest.py
    test_agent.py
```
