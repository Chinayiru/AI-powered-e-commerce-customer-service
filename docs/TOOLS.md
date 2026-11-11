# 工具清单与调用契约

| 项 | 内容 |
| --- | --- |
| 依据 | `docs/BOUNDARY_v1.md` v1.4.0 §7、§8 |
| 原则 | **事实由 Java 提供，解释由 RAG 提供，决策由策略 + 人做出**。三者不得互相替代 |
| 关键约束 | Python 不直连数据库；Python 不执行任何写操作；所有工具入参**不含 userId** |

---

## 1. 为什么工具在 Java 侧

| 若把工具放 Python | 后果 |
| --- | --- |
| 直连订单库 | 越权过滤靠 Python 自觉，一处漏判即数据泄露 |
| 自己执行退款 | 无审批、无幂等、无审计，出事无法追溯 |
| 自己拼金额 | 与 Java 结算口径漂移，客户看到"应退 58"实际退 57 |

因此：**Python 只有两只手**（看订单、看物流），其余动作一律回到 Java 的受控接口，由 Java 校验、落库、留痕。

---

## 2. 工具清单

| # | 工具 | 调用方 | 方向 | 读/写 | 幂等 |
| --- | --- | --- | --- | --- | --- |
| T1 | `queryOrder` | Python → Java | `/internal/tools/queryOrder` | 读 | 天然幂等 |
| T2 | `getLogistics` | Python → Java | `/internal/tools/getLogistics` | 读 | 天然幂等 |
| T3 | `createAftersaleDraft` | Java 内部 | 服务方法 | 写（草稿） | 由 `generationTaskId` 保证 |
| T4 | `transferToHuman` | Java 内部 | 服务方法 | 写（状态） | 由 `requestId` 保证 |
| T5 | `executeAftersale` | Java 内部 | 服务方法 | 写（**仅模拟**） | 由 `ticketId + version` 保证 |

T3–T5 **不暴露给 Python**：Python 只返回 `AskResponse`，草稿由 Java 落库。

---

## 3. T1 `queryOrder`

**用途**：取订单事实（状态、金额、可退金额、商品）。列表与详情共用此工具，禁止另读夹具。

请求：

```json
{ "orderNo": "O1001" }
```

响应：

```json
{
  "orderNo": "O1001",
  "userId": "U001",
  "status": "PAID",
  "amountCents": 5800,
  "refundedAmountCents": 0,
  "refundableAmountCents": 5800,
  "paidAt": "2026-11-01T10:00:00+08:00",
  "deliveredAt": null,
  "items": [{ "skuId": "SKU-1", "title": "无线耳机", "qty": 1, "unitAmountCents": 5800 }]
}
```

| 错误 | HTTP | 语义 |
| --- | --- | --- |
| `ORDER_NOT_FOUND` | 404 | 不存在**或不属于当前身份**（同文案，防枚举） |
| `TOOL_UNAVAILABLE` | 503 | 下游订单服务不可用 |
| `TOOL_TIMEOUT` | 504 | 超过 800ms |

约束：

- `userId` **只**来自 `X-Internal-Identity` 的 HMAC 载荷，请求体出现 `userId` 一律 422。
- 金额单位分；`refundableAmountCents` 由 Java 计算，Python 不得自行用 `amountCents` 代替。
- 不返回 `carrier`/`trackingNo`（那是 T2 的事实），避免两处真源。

---

## 4. T2 `getLogistics`

请求：

```json
{ "orderNo": "O1002" }
```

响应：

```json
{
  "orderNo": "O1002",
  "status": "IN_TRANSIT",
  "shipments": [
    {
      "carrierCode": "MOCK",
      "trackingNo": "MOCK002",
      "status": "IN_TRANSIT",
      "events": [{ "at": "2026-11-09T09:00:00+08:00", "code": "ARRIVED", "text": "到达分拨中心" }]
    }
  ]
}
```

| 情况 | 返回 |
| --- | --- |
| 未发货 | `200`，`status=NOT_SHIPPED`，`shipments: []`（**不是错误**，客户侧文案"还没有物流单号"） |
| 一单多包裹 | `shipments` 多个元素；`status` 取最差状态 |
| 归属不符 | `404 ORDER_NOT_FOUND`（与不存在同文案） |

---

## 5. T3 `createAftersaleDraft`（Java 内部）

输入来自 `AskResponse` 的**已验证部分**；Java 重新校验后才落库。`policyCheck` 不是 Python 给的——由 Java 规则引擎按订单与政策计算后传入。

```
createAftersaleDraft(ticketId, generationTaskId, draftVersion,
                     replyDraft, suggestedAction, citations, policyCheck, confidence)
```

| 校验 | 失败 |
| --- | --- |
| `generationTaskId` 未出现过 | 唯一键冲突 → 直接返回已有草稿（幂等） |
| `ticket.state == AI_RUNNING` | `STATE_NOT_ALLOWED` |
| `policyCheck.allowed` 与 `suggestedAction` 一致 | `POLICY_REJECTED` |
| 正文不含内部码（`REFUND_*` 等） | `INVALID_ARGS` |

---

## 6. T4 `transferToHuman`（Java 内部）

```
transferToHuman(ticketId, reason, note, requestId, expectedVersion)
```

- `reason` 必须在 9 个枚举内（见数据字典 §7.1）。
- 写 `UPDATE ... WHERE ticket_id=? AND state IN (...) AND version=?`；0 行 → `STALE_STATE`。
- 客户只看"已转交人工"，原因码仅进坐席视图。

---

## 7. T5 `executeAftersale`（Java 内部，`SIMULATED`）

**演示环境不调用任何真实退款接口。** 执行器只做三件事：

1. 校验 `state=CONFIRMED` 且 `version` 匹配；
2. 写一条 `tool_call(name=executeAftersale, ok=1)` 与一条客户可见结果消息；
3. 状态转 `EXECUTING → CLOSED`。

```json
{ "ticketId": "T202611100001", "action": "REFUND", "amountCents": 5800, "mode": "SIMULATED" }
```

| 模式 | 行为 |
| --- | --- |
| `SIMULATED` | 不产生资金动作，响应里 `"simulated": true` |
| `REAL` | **未实现**，调用直接 `POLICY_REJECTED`（本阶段禁止） |

**调用时机（v1.4 澄清）**：T5 由 `send` 在**同一次请求内**触发，不是坐席再点一次"执行"。

| 步骤 | 事务 | 内容 | 失败处理 |
| --- | --- | --- | --- |
| 1 | 事务 1 | 守卫全过 → `DRAFT_READY/TRANSFERRED → CONFIRMED`，写人工消息与审计 | 失败即整体失败，状态不变 |
| 2 | **事务外** | 调 T5（`SIMULATED`，幂等键 `generationTaskId`） | 失败不回滚 `CONFIRMED`；响应返回 `CONFIRMED` + `TOOL_FAILED`（非 5xx）；后台补偿，坐席可重试 |
| 3 | 事务 2 | `CONFIRMED → EXECUTING → CLOSED` + 结果消息 | 失败留 `EXECUTING`，由补偿任务推进；不重复执行 |

响应体在成功后返回最终态（`CLOSED` + `version`），客户侧只看到"已完成（演示环境，未真实退款）"。**不允许**把"已确认"直接当"已退款"返回。

---

## 8. 错误与重试策略

| 错误 | Python 侧 | Java 侧 |
| --- | --- | --- |
| `ORDER_NOT_FOUND` | 第一次：请客户核对单号（不转人工）；第二次仍无 → `INSUFFICIENT_INFO` 转人工 | 不重试 |
| `TOOL_TIMEOUT` | 重试 1 次（200ms 退避，共 2 次尝试）；仍失败 → `TOOL_FAILED` 转人工 | — |
| `TOOL_UNAVAILABLE` | 同上；不编造事实 | 熔断 30s |
| `INVALID_ARGS` | 不重试，记日志（属契约 bug） | 500 监控告警 |

**模型超时不在此表**：AI 层超时**不重试**（见 `AGENT_RAG_SPEC` §10），直接降级转人工。工具重试与模型重试是两条策略，不要合并。

**越权口径统一**：订单/物流一律 `404 ORDER_NOT_FOUND`（不区分"不属于你"与"不存在"）；`403 FORBIDDEN_SCOPE` 只用于"ticketToken 与 ticketId 不匹配"这类工单级越权。

**任何情况下不得把工具错误码原文返回给客户。**

---

## 9. 可观测

每次调用落一行：

| 字段 | 说明 |
| --- | --- |
| `trace_id` | 全链路透传（Java 生成，Python 原样带回） |
| `ticket_id` / `step` | 时间线顺序 |
| `name` / `ok` / `latency_ms` / `error_code` | — |
| `request_hash` / `response_hash` | sha256，用于事后复核"当时到底返回了什么" |
| `prompt_version` | 仅 AI 步骤 |

目标：任一条客户投诉，能在 1 分钟内还原"Agent 看到了什么、基于什么说了那句话"。

---

## 10. 禁止事项（评审时逐条对照）

1. ❌ Python 直连 MySQL。
2. ❌ 工具入参带 `userId`。
3. ❌ 工具返回值里带内部错误码给客户。
4. ❌ 用 `amountCents` 代替 `refundableAmountCents`。
5. ❌ 在 `SIMULATED` 模式下调用真实退款。
6. ❌ 重试写操作（T5）——写操作只能靠 `version` 乐观锁重放，不能盲重试。
