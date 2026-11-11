# 边界确认书 v1.4.1（评审裁决修订）

| 项 | 内容 |
| --- | --- |
| 版本 | **v1.4.1（基于 v1.4.0 的裁决修订，范围未变）** |
| 冻结日期 | 2026-11-10（v1.4.0 修订日期 2026-11-11；v1.4.1 修订日期 2026-11-11） |
| 配套 | OpenAPI **v1.5.0**（本版未改接口形状语义，仅同步 `send` 的 202 与描述）；两者对应关系见 `docs/contract-snapshot.json` |
| 状态 | 冻结。此后任何契约变更按 §16 走版本递增，不得在代码里单方面改 |
| 已确认 | 验收口径 **S+Q**；前端 **Vue 3 + Vite + SFC**，三个页面；转人工 9 枚举；错误码 17 个；Q 段 go/no-go 0.85 / 5% / 0.80 |
| 本轮 | 按文档评审补齐：状态数、幂等作用域、尝试计数、多轮口径、写接口参数、工具错误响应、Python 与 policyCheck 的边界、关联单凭据，见 §17 |

---

## 0. 验收：S+Q 两个里程碑，分开报告

| 里程碑 | 验什么 | 退出条件 |
| --- | --- | --- |
| **M-S** | 系统闭环：消息进 → 受控查询 → 结构化建议 → Java 校验落草稿 → 人工确认/转交 → 客户看到状态 | §15.1 AC01–AC26 全绿；scripted + Mock |
| **M-Q** | 回答质量：意图、槽位、检索、草稿可用率、引用、幻觉、置信度分层 | §15.2 QC01–QC12；真实模型 + 冻结验收集 |

**分开报告的理由**：scripted 只能证伪"流程设计错误"，不能证伪"模型不行"。合表会让低分被"流程都对"掩盖，或让高分被读成"AI 好用"。

**M-Q 是"完成评测即交付"，不是"指标达标才通过"**：go/no-go 阈值预设（§15.2），最多 2 轮调参，之后无论结果如何都出报告；若未达标，报告写"未达标 + 差距 + 原因假设"，不改阈值凑数。

---

## 0.1 一期目标的准确表述

> **售后辅助处理闭环**：单平台、Mock 数据下，支持多轮咨询、受控只读查询、生成可追溯草稿、人工审核与转交。
> **不包含**：真实退款、真实物流、真实政策库。模型质量由 M-Q 单独验证，不计入 M-S。

`CLOSED` 只表示"本系统流程终结"，**不代表业务结果**；一期工单恒 `executionMode=SIMULATED`，客户文案必须出现"演示环境，未真实退款"。

---

## 1. 三条原则

1. **Java 是唯一裁决方**。Python 产出解释与建议，不落业务状态、不写草稿、不碰资金。
2. **事实 / 解释 / 决策三权分立**：事实由工具给（归属、状态、金额、退余额）；解释由 Python 给（政策版本、条款、话术）；决策由 Java 规则引擎给（允不允许、上限、是否必须人工）。引用政策 ≠ 政策允许。
3. **写操作分两类**：业务写（退款/补发/改状态，本期全不做）与记录写（会话、草稿、转交、审计，本期做，且只由 Java 执行）。

---

## 2. 范围

### 2.1 做

| 能力 | 归属 | 说明 |
| --- | --- | --- |
| 多轮会话 | Java 存，Python 无状态 | 客户可继续发消息 |
| 意图/槽位 | Python | 咨询 / 售后 / 其他 |
| 只读查询 | Java 工具 | 订单、物流（一单多包裹） |
| 政策检索 | Python | 带 `policyVersion` / `clauseId` |
| 结构化建议 | Python | `replyDraft` + `suggestedAction` + `citations` + `confidence` + `replyType` |
| 草稿落库与版本 | Java | `draftVersion` 保存成功后才分配 |
| 状态机 / 幂等 / 审计 | Java | |
| 人工确认 / 转交 / 回复 / 关闭 | Java | 坐席动作 |
| 前端 | Vue 3 + Vite + SFC | 三个页面，见 §13 |

### 2.2 不做

自动退款、补发、改地址、改状态；真实资金/物流；真实政策库；多平台（留 Adapter）；SSO（演示身份，见 §2.3）；消息队列；模型微调；向量库集群。**退货退款移出一期**，仅保留字典值。

### 2.3 入口身份（v1.2 的缺口，此处闭合）

建单前不可能有 `ticketToken`，因此入口身份必须显式规定：

| 场景 | 规则 |
| --- | --- |
| 演示环境 | 请求头 `X-User-Id`，仅接受白名单 `U001`/`U002`；由配置 `demo.allow_header_identity=true` 控制 |
| 生产环境 | 该开关必须为 false；未接 SSO 前服务拒绝启动（fail-fast），**不允许静默降级** |
| 建单后 | Java 签发 `ticketToken`（HMAC，绑定 ticketId+userId+exp），此后该工单只认 token |
| 服务间 | Java 签发 `X-Internal-Identity`（HMAC 签名），Python 与工具校验；**任何接口不接受自报 userId**，入口头只在 Java 边界被读取一次 |

`GET /api/me/orders`（我的订单）同样依赖入口身份；生产模式下必须由 SSO 提供。

---

## 3. 两个对象：咨询 ≠ 售后申请

| 对象 | 订单号 | 草稿 | 状态机 | 解决的定义 |
| --- | --- | --- | --- | --- |
| `CONSULT` | 可无 | 无 | §5.1 | 给出带依据的回答，且客户未再追问同一问题 |
| `AFTERSALE` | **建单时可不填，生成草稿前必填** | 有（多版本） | §5.2 | 草稿被人工确认，或转交人工 |

### 3.1 售后缺订单号的路径（v1.2 断裂处）

`AFTERSALE` 允许在 `PENDING_ACCEPT → AI_RUNNING` 阶段无 `orderNo`，此时进入 **`WAITING_INPUT`**（"等客户补信息"），不生成草稿、不给金额结论。客户补充后回到 `AI_RUNNING`**硬规则**：草稿生成（`DRAFT_READY` 的入口）校验 `orderNo` 非空且归属校验通过，否则 `STATE_NOT_ALLOWED`。

### 3.2 咨询中途要退款

**一律新建关联售后单**，不转换原单：新单 `parentConsultTicketId = 原 CONSULT.ticketId`，并复制最近 6 条消息作为上下文；原咨询单保留原状态（通常是 `REPLIED`），不因新单而关闭。理由：转换会让"咨询已答复"的历史与"退款被驳回"的结果混在一条状态线上，事后无法归因。

**凭据回传（v1.4 补）**：触发建单的那次响应必须同时回传新单的 `ticketId` 与 `ticketToken`（复用建单响应的同一结构，不另造字段）。否则客户与前端只能靠坐席口头告知单号，新单等于没有入口。

---

## 4. 领域模型

金额一律**分**；时间 ISO-8601 带 `+08:00`；枚举大写。

### 4.1 Order（只读）

`{orderNo, userId, status: PAID|SHIPPED|DELIVERED|CLOSED, amountCents, refundedAmountCents, refundableAmountCents, refundedItems[], paidAt, deliveredAt?, items[]}`
一期 Mock：`refundedAmountCents=0`、`refundableAmountCents=amountCents`、`refundedItems=[]`。

### 4.2 Shipment（只读）

`{status: NOT_SHIPPED|IN_TRANSIT|DELIVERED|EXCEPTION, shipments:[{carrierCode, trackingNo, status, events[]}]}`

### 4.3 Ticket

| 字段 | 说明 |
| --- | --- |
| ticketId | `T{yyyyMMdd}{4 位}` |
| category | `CONSULT` / `AFTERSALE` |
| parentConsultTicketId | 由咨询转来的售后单才有 |
| userId / orderNo? | AFTERSALE 生成草稿前必填 orderNo |
| state | §5 |
| version | 乐观锁，每次迁移 +1 |
| taskEpoch | 生成任务代次，见 §7.3 |
| currentAttempt | 当前**生成任务**的尝试序号（随 `generationTaskId` 重置，不是整单调用次数） |
| stalledRounds | 连续无进展轮数（内部字段，仅坐席视图） |
| executionMode | 一期恒 `SIMULATED` |
| transferReason | 9 枚举之一 |
| activeOrderKey | `userId:orderNo`，仅未结束时有值（§7.4） |

### 4.4 Draft（仅 Java 写）

`{draftId, ticketId, draftVersion, generationTaskId, suggestedAction, replyDraft, citations[], confidence, replyType, policyCheck, policyVersion, needHumanReview, createdAt, superseded}`

`needHumanReview` 是**生成时**按当时的政策版本算出的快照，随草稿落库；`send` 只读草稿上的值，不重算。这样"生成后政策变了"不会让一张已经展示给坐席的草稿突然改变语义。

### 4.5 PolicyCheck（Java 规则引擎）

`{allowed, code, policyVersion, clauseId, maxRefundableCents, needHumanConfirm: true}`

### 4.6 ToolCall（审计）

`{traceId, toolName, argsDigest, ok, errorCode, durationMs, attempt, at}`

---

## 5. 状态机

### 5.1 咨询 `CONSULT`（7 态）

```
OPEN ──首条消息──▶ AI_RUNNING ──有依据且非决策类──▶ REPLIED
                        │  │                          │
                        │  └──缺必要信息──▶ WAITING_INPUT ──补齐──▶ AI_RUNNING
                        │                             │
                        └──低置信/无依据/决策类/失败──▶ TRANSFERRED
                                                      │
REPLIED ──客户继续问──▶ AI_RUNNING                      ├──坐席回复──▶ REPLIED
REPLIED ──7 天无活动──▶ CLOSED（系统关闭 ≠ 已解决）      ├──坐席关闭──▶ CLOSED
                                                      └──客户撤销──▶ CANCELLED
```

### 5.2 售后 `AFTERSALE`（10 态）

状态全集 11 个中，售后用到 10 个（与咨询共享 `REPLIED`：转人工后坐席直接答复，客户看得到，但仍算售后单，不并入咨询）。

```
PENDING_ACCEPT ──▶ AI_RUNNING ──缺订单号── WAITING_INPUT ──补齐──▶ AI_RUNNING
                       │                                              │
                       │◀──────────────── 建议就绪 ───────────────────┘
                       ▼
                  DRAFT_READY ──坐席确认（守卫 §5.3）──▶ CONFIRMED
                       │                                    │
                       ├──坐席转交──▶ TRANSFERRED             ├──发起模拟执行──▶ EXECUTING
                       ├──客户改需求──▶ AI_RUNNING             └──回执──▶ CLOSED
                       └──客户撤销──▶ CANCELLED
TRANSFERRED ──坐席确认（同守卫）──▶ CONFIRMED
TRANSFERRED ──坐席回复──▶ REPLIED ──客户再追问──▶ AI_RUNNING
TRANSFERRED / REPLIED ──坐席关闭──▶ CLOSED
```

> 箭头标注：`CONFIRMED → EXECUTING` 是"发起模拟执行"，`EXECUTING → CLOSED` 才是"Mock 回执到达"。v1.2 把两步画成一条，易被读成"确认即完成"。

### 5.3 迁移守卫矩阵（v1.2 缺失，导致"Java 裁决"落不了地）

| 动作 | 允许状态 | 守卫 | 失败 |
| --- | --- | --- | --- |
| 建售后单 | — | 同 `userId+orderNo` 无未结束单（§7.4），DB 唯一索引兜底 | `DUPLICATE_REQUEST` |
| 生成草稿 | `AI_RUNNING` | `orderNo` 非空 + 归属校验通过 | `STATE_NOT_ALLOWED` |
| **坐席确认** | `DRAFT_READY`、`TRANSFERRED` | `policyCheck.allowed=true` **且** `suggestedAction.amountCents ≤ policyCheck.maxRefundableCents` **且** `draftVersion` 匹配 **且** `expectedVersion` 匹配 | `POLICY_REJECTED` / `STALE_DRAFT` / `STALE_STATE` |
| 坐席转交 | `AI_RUNNING`、`DRAFT_READY`、`WAITING_INPUT` | `reason ∈ 9 枚举` | `INVALID_ARGS` |
| 坐席回复 | `TRANSFERRED` | 文本非空、≤500 字 | `STATE_NOT_ALLOWED` |
| 坐席关闭 | `TRANSFERRED`、`REPLIED` | — | `STATE_NOT_ALLOWED` |
| 草稿重生成 | `DRAFT_READY` | 旧草稿置 `superseded`、`taskEpoch+1` | `STATE_NOT_ALLOWED` |
| 客户追加消息 | `WAITING_INPUT`、`DRAFT_READY`、`REPLIED`、`TRANSFERRED` | `DRAFT_READY` 收到 → 回 `AI_RUNNING` 重生成；`TRANSFERRED` 收到 → **保持 `TRANSFERRED`**，消息落库并标记待坐席处理，不自动回到 AI | `STATE_NOT_ALLOWED` |
| **客户撤销** | **白名单：`PENDING_ACCEPT`、`WAITING_INPUT`、`AI_RUNNING`、`DRAFT_READY`、`REPLIED`、`TRANSFERRED`** | `expectedVersion` | `STATE_NOT_ALLOWED`（CONFIRMED/EXECUTING/CLOSED）/ `STALE_STATE` |
| 模拟执行 | `CONFIRMED` | `executionMode=SIMULATED` | — |

**`send` 与模拟执行的时序（v1.4 澄清，v1.4.1 补响应语义）**：`send` 是一个请求内的三段，不是两次用户操作——①事务 1 提交 `→CONFIRMED`、写人工消息、**落库待执行任务**与审计；②**事务外**调用 T5 `executeAftersale`（`SIMULATED`，无外部副作用，幂等键 `generationTaskId`）；③事务 2 写 `CONFIRMED→EXECUTING→CLOSED` 与结果消息。若第②步失败，第①步的 `CONFIRMED` **不回滚**，响应语义如下：

| 结果 | HTTP | 响应体 | 说明 |
| --- | --- | --- | --- |
| 三段全完成 | `200` | `SendResult`，`state=CLOSED` | 客户侧文案含"演示环境，未真实退款" |
| ①成功、②未完成 | `202` | `SendResult`，`state=CONFIRMED`（或当前实际状态） | **受理成功、执行未完成**；详细错误码只进坐详情与审计，本期不为它新增响应字段；后台按任务记录重试，坐席可手动重试 |
| ①的守卫失败 | `409` / `422` | `Error` | `POLICY_REJECTED` / `STALE_DRAFT` / `STALE_STATE` / `STATE_NOT_ALLOWED` / `REVIEW_NOTE_REQUIRED` |
| ①的落库失败 | `500` | `Error`（`PERSISTENCE_FAILED`） | 不进入 `CONFIRMED`，无副作用 |

`202` 的前提是**待执行任务已持久化**（与 `CONFIRMED` 同一事务提交），重启后可从任务表恢复重试；只有内存后台任务的实现不满足本承诺。同一 `requestId` 重复提交返回**原受理结果**（`202` 仍为 `202`、`200` 仍为 `200`），不得重复批准或重复执行。这样"确认"与"执行"各自可重入，不会出现钱没退却显示完成。

**确认与撤销竞争**：两者都是 `UPDATE ... WHERE state=? AND version=?`，`rowsAffected=1` 者胜，另一个 `409 STALE_STATE`，不重试、不合并。取消白名单刻意排除 `CONFIRMED/EXECUTING`——已批准进入执行的单子不能由客户单方面撤销，只能走人工。

### 5.4 咨询是否免审（v1.2 未定，此处定）

| 类型 | 判定 | 处理 |
| --- | --- | --- |
| `INFORMATIONAL` | 物流进度、政策原文、流程说明；有引用且置信度达阈值 | **直接回复**，不需坐席 |
| `DECISIONAL` | 涉及"能不能退/退多少/是否赔付"等结论 | 一律 `TRANSFERRED`，由坐席答复；Python 只能给建议 |

Java 用 `replyType` 字段裁决；`CONSULT` 收到 `DECISIONAL` 时不回客户，直接转交。这是 §1 原则 2 在接口层的落点。

---

## 6. 多轮会话

- Java 存全部消息；Python 无状态，每次**只收最近 6 轮 + 摘要**。口径固定：1 轮 = 客户 1 条 + 坐席 1 条，因此最多 12 条消息；超出部分压成 `summary`（≤300 字，Java 生成，不得含内部码）。单条 `text` 截断 500 字；`history` 项为 `{role, text, createdAt}`。
- 接口 `POST /api/tickets/{id}/messages`：body `{text, requestId}`，返回 `{displayState, version, messages[], createdTicket?}`；消息白名单仅 `CUSTOMER`/`AGENT`，`SYSTEM` 不外露。`createdTicket` 仅在"咨询转售后"创建新单时出现，结构同建单响应（`ticketId`/`ticketToken`/`displayState`/`version`），解决新单凭据的交付问题。
- 客户消息在 `DRAFT_READY` 会触发重生成；在 `CONFIRMED/EXECUTING/CLOSED` 返回 `STATE_NOT_ALLOWED`。

**"无进展"判定**（不用关键词）：
- 有进展 = 新槽位被填 / 新事实返回 / 草稿版本 +1 / 诉求对象变化。
- 缺必要槽位被**连续索取 2 次** → `stalledRounds += 2` → 转交 `INSUFFICIENT_INFO`。
- 工具可重试失败 ≥2 次 → 直接 `TOOL_FAILED`，不计轮数。
- 客户要人工：由 Python 判 `intent=HANDOFF` 返回，Java 只信枚举；不匹配"不/算了"等词。

---

## 7. 幂等、生成任务与并发

### 7.1 幂等键（前移到客户端）

- **Vue 在首次发送前生成 `requestId`（UUIDv4），重试复用同一个**；不再依赖服务端回传。
- 作用域：`(userId, endpoint, targetId, requestId)` 唯一索引。同一 `requestId` 打到不同接口或不同工单互不影响。
- `targetId` 的定义（v1.4 补齐，之前只写名字）：

| 端点 | `targetId` |
| --- | --- |
| `POST /api/tickets` | `orderNo`；无订单号时用字面量 `NOORDER`（建单前还没有 ticketId） |
| `POST /api/tickets/{id}/messages`、`/cancel` | `ticketId` |
| `POST /api/agent/tickets/{id}/send`、`/regenerate`、`/handoff`、`/reply`、`/close` | `ticketId` |
| `GET /api/me/orders`、`GET /api/tickets/{id}` | 不参与幂等（读请求） |

`targetId` 缺失或为空 → `INVALID_ARGS`，不允许退化成"只按 userId+requestId"去重。
- 同 key 同请求体：返回首次结果；同 key 不同请求体：`409 IDEMPOTENCY_CONFLICT`，不执行。
- 并发同请求：先插入者执行，后到者若结果未就绪返回 `409 IN_PROGRESS`（`retryable=true`，`Retry-After: 1`），就绪后返回同一结果。
- 保留 24h；`traceId` 只做追踪，不承担幂等。

### 7.2 生成任务

- 一次逻辑生成 = 一个 `generationTaskId`（Java 生成）；重试**复用**，不新建。
- 草稿保存有唯一索引 `(ticketId, generationTaskId)`，重复回调只更新不改写。
- `draftVersion` 在**保存成功后**分配（同 ticket 单调 +1），不在请求时预分配。

### 7.3 结果作废（比"只比 attempt"完整）

Ticket 有 `taskEpoch`。以下动作 `taskEpoch += 1`：客户新消息、坐席草稿重生成、转交、撤销、关闭。规则：

- **`currentAttempt` 是"生成任务的尝试序号"，不是整单调用次数**：每个新 `generationTaskId` 从 0 开始，同一任务内最多 2 次尝试（即 1 次重试），失败超限才转 `TOOL_FAILED`。客户第 5 轮追问会开启第 5 个任务，`currentAttempt` 重新从 0 计，不会因为"单子聊得多"被误判超限。
1. 响应发布条件：`attempt == currentAttempt` **且** `epoch == ticket.taskEpoch` **且** 状态仍为 `AI_RUNNING`。
2. 任一不满足 → 丢弃，记 `LATE_RESULT_DROPPED`，**不改状态、不写草稿**。
3. 超时后 Java 已迁移 `TRANSFERRED`；迟到响应只能进审计。

### 7.4 同订单唯一未结束单

DB 生成列 `activeOrderKey = CONCAT(userId,':',orderNo)`，仅当状态 ∉ `{CLOSED, CANCELLED}` 时有值，否则 NULL；对 `activeOrderKey` 建**唯一索引**（MySQL 允许 NULL 重复）。并发建单由索引兜底，捕获重复键转 `409 DUPLICATE_REQUEST`，不做"先查后插"。

---

## 8. 接口

### 8.1 消费者

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/tickets` | 建单（`requestId`），返回 `ticketId` + `ticketToken` + `displayState` + `version`；响应不含 intent/confidence，也不含内部 `state` |
| POST | `/api/tickets/{id}/messages` | 追加消息；响应含 `createdTicket?`（咨询转售后时带回新单凭据） |
| GET | `/api/tickets/{id}` | 状态 + 最新回复（客户语义六态，见数据字典 §4） |
| POST | `/api/tickets/{id}/cancel` | 撤销（白名单见 §5.3） |
| GET | `/api/me/orders` | **我的订单**（v1.2 缺）→ `[{orderNo, statusLabel, amountCents}]`，数据逐个经 `queryOrder` 取，不读夹具 |

### 8.2 坐席

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/agent/tickets/{id}` | 三栏数据 |
| POST | `/api/agent/tickets/{id}/send` | `{text, draftVersion, reviewNote?, expectedVersion, requestId}` |
| POST | `/api/agent/tickets/{id}/regenerate` | **重生成草稿**；`{note?, expectedVersion, requestId}` → `AI_RUNNING`，`taskEpoch+1` |
| POST | `/api/agent/tickets/{id}/handoff` | `{reason, note?, expectedVersion, requestId}` |
| POST | `/api/agent/tickets/{id}/reply` | **转交后直接回复**；`{text, expectedVersion, requestId}` → `REPLIED` |
| POST | `/api/agent/tickets/{id}/close` | 关闭；`{note?, expectedVersion, requestId}` |

所有写接口（含 `reply`/`close`）都必须带 `requestId`，否则"前端重试"在这两个端点上会重复产生消息；读接口不需要。

`send` 的派生：`edited = (text != draft.replyDraft)`，`editDistance` 由服务端计算（Levenshtein），**不信任前端传值**。

### 8.3 Java → Python

`POST /internal/agent/ask`：`{traceId, ticketId, requestId, attempt, taskEpoch, userId, category, message, context:{orderNo?, summary?, history[{role,text,createdAt}]}}`（`history` ≤12 条，见 §6）。
响应新增：`replyType: INFORMATIONAL|DECISIONAL`、`needHumanReview`、`transferReason?`。超时 8s，Python 无状态、不落库。
**Python 看不到 `policyCheck`**：该字段由 Java 规则引擎在生成前后计算并随草稿落库，不进入 `/internal/agent/ask` 的请求或响应。Python 只说"事实与建议"，"能不能退"由 Java 判。

### 8.4 Python → Java（只读两项）

`queryOrder(orderNo)`、`getLogistics(orderNo)`；userId 从签名身份取，不接受入参。草稿与转交由 Java 执行。

### 8.5 错误码（17 个，封闭集）

| 码 | HTTP | retryable | 场景 |
| --- | --- | --- | --- |
| `INVALID_ARGS` | 422 | 否 | 参数缺失/非法 |
| `UNAUTHENTICATED` | 401 | 否 | 无/坏 token |
| `FORBIDDEN_SCOPE` | 403 | 否 | `ticketToken` 与 `ticketId` 不匹配；订单级越权一律 404 |
| `ORDER_NOT_FOUND` | 404 | 否 | |
| `TICKET_NOT_FOUND` | 404 | 否 | |
| `STATE_NOT_ALLOWED` | 409 | 否 | 当前状态不允许该动作 |
| `DUPLICATE_REQUEST` | 409 | 否 | 幂等键重复/同订单已有未结束单 |
| `IDEMPOTENCY_CONFLICT` | 409 | 否 | 同 key 不同体 |
| `IN_PROGRESS` | 409 | **是** | 同 key 并发，结果未就绪 |
| `STALE_DRAFT` | 409 | 否 | draftVersion 过期 |
| `STALE_STATE` | 409 | 否 | version 过期（并发确认/撤销） |
| `POLICY_REJECTED` | 409 | 否 | 政策或金额不允许 |
| `REVIEW_NOTE_REQUIRED` | 422 | 否 | 需复核但未填意见 |
| `TOOL_UNAVAILABLE` | 503 | 是 | |
| `TOOL_TIMEOUT` | 504 | 是 | |
| `AGENT_UNAVAILABLE` | 503 | 是 | AI 层不可用 |
| `PERSISTENCE_FAILED` | 500 | 是 | 落库失败 |

### 8.6 转人工原因（9 个，封闭集）

`LOW_CONFIDENCE`、`NO_EVIDENCE`、`POLICY_BLOCKED`、`TOOL_FAILED`、`AMBIGUOUS_ORDER`、`ORDER_NOT_FOUND`、`OUT_OF_SCOPE`、`USER_REQUESTED`、`INSUFFICIENT_INFO`。
（v1.2 里 `REPEAT_UNRESOLVED` 与 `INSUFFICIENT_INFO` 语义重叠，已删除前者，统一由"连续索取 2 次"触发 `INSUFFICIENT_INFO`。）

**`TOOL_FAILED` 的覆盖范围（v1.4.1 裁决）**：包含**工具调用失败与 AI 服务故障**两类，不新增第十个枚举。区分方式不是原因码，而是 HTTP 码 `AGENT_UNAVAILABLE`（AI 层）与组件日志：审计里 `toolName` 为空或组件字段为 `agent` 即为 AI 故障，否则为工具失败。
**`OUT_OF_SCOPE` 与 `USER_REQUESTED` 的边界（v1.4.1 裁决）**：投诉/威胁/监管等**关键词本身不算客户要求人工**，归 `OUT_OF_SCOPE`；只有客户**明确要求人工**（"转人工""找客服""要真人"）才用 `USER_REQUESTED`。

---

## 9. 归属

| 动作 | Java | Python |
| --- | --- | --- |
| 读订单/物流 | 执行 | 发起 |
| 政策检索与解释 | — | 执行 |
| 判断能否退 | 规则引擎 | 只给建议 |
| 保存草稿 / 状态迁移 / 转交 | 执行 | — |
| 咨询是否免审 | 依 `replyType` 裁决 | 提供 `replyType` |

---

## 10. 阈值

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `intent.confidence_threshold` | 0.60 | 低于 → `needHumanReview`（草稿照出，坐席需写复核说明） |
| `refund.auto_suggest_limit_cents` | 5000 | **建议档位**：≤ 时草稿普通；> 时草稿 `needHumanReview=true`、`reviewNote` 必填（仍然只是建议，必须人工确认） |
| `consult.stall_rounds` | 2 | 无进展阈值 |
| `agent.timeout_ms` | 8000 | 超时降级 |

**上一版的两个退款阈值（`auto_suggest_limit_cents` / `manual_confirm_above_cents`）值相同、作用未定义，v1.4 合并为一个。** 政策硬上限是 `policyCheck.maxRefundableCents`（由规则引擎按订单与政策算出，不是配置项）：`suggestedAction.amountCents` 超过它 → `POLICY_REJECTED`。**两个阈值都不等于"低金额免人工"**：本系统没有任何自动执行路径，确认永远是人工动作。

**金额建议硬限定**：整单、`refundedAmountCents=0`、无部分退款；否则直接 `TRANSFERRED`（`POLICY_BLOCKED`），不给金额。

**已发货与"七天无理由"不矛盾**：已发货/已签收订单可以申请**退货退款**（七天无理由，自签收次日起算）；"仅退款"只在**未发货**状态成立。两者是不同售后类型，不能拿"已发货"直接推定"不能退"。

---

## 11. 降级

| 场景 | 行为 | 状态 |
| --- | --- | --- |
| Python 超时/5xx/熔断 | 不二次重试，降级转人工 | `TRANSFERRED` |
| 工具可重试失败 | 同工具 ≤2 次 | 视结果 |
| `ORDER_NOT_FOUND` | 首次提示核对；第 2 次转人工 | 一致文案 |
| 落库失败 | `PERSISTENCE_FAILED`，不迁移 | — |

---

## 12. 鉴权

消费者 `ticketToken`（HMAC，绑定 ticketId+userId+exp）；坐席 `agentToken`（环境变量注入，演示用）；入口身份见 §2.3；内部 `X-Internal-Identity`（HMAC `{userId, role, exp, nonce}`，防重放：nonce 5 分钟内唯一）。

---

## 13. 前端（Vue 3 + Vite + SFC）

| 页面 | 路由 | 只做 |
| --- | --- | --- |
| P1 消费者咨询 | `/` | 对话、状态、我的订单侧栏 |
| P2 工单查询 | `/ticket/:ticketNo` | 工单号 + 凭据查状态；凭据不落 localStorage |
| P3 坐席工作台 | `/agent/:ticketId` | 三栏 + 确认/重生成/转交/回复/关闭 |

`requestId` 由前端首次发送时生成并复用；轮询 5s；`dist` 由 Java 静态托管，生产不开第二端口；移动端只保证 P1/P2 在 390px 可用。

---

## 14. 假设与前置

| # | 项 | 默认 | 状态 |
| --- | --- | --- | --- |
| A1 | 范围 | 咨询 + 售后草稿；退货退款移出 | 待讨论 |
| A2 | 金额建议 | 整单、未退过款 | 待讨论 |
| A3 | 阈值 | §10 | 待讨论 |
| A4 | Mock 脏数据 | 分/元混用、一单多包裹、状态缺失 | 待讨论 |
| A5 | 模型 | M-S 用 scripted；M-Q 用真实模型 | 已定（随 S+Q） |
| A6 | 向量库/队列 | 均不上 | 待讨论 |
| A7 | 登录 | 演示身份（§2.3） | 待讨论 |
| A8 | 前端 | Vue 3 + Vite + SFC，三页 | ✅ 已定 |
| A9 | 验收 | S+Q 分开报告 | ✅ 已定 |

**前置项（不阻塞 M-S 的编码，只阻塞对应里程碑）**：

| 级别 | 项 | 阻塞什么 |
| --- | --- | --- |
| **真实接入前置** | 平台与订单字段来源 | 只阻塞真实 Adapter 映射；Mock 与契约可照写 |
| **M-Q 前置** | 模型供应商、预算、验收集负责人、评分口径 | 只阻塞 M-Q；M-S 先行 |

---

## 15. 验收

### 15.1 M-S（scripted + Mock；AC01–AC26）

| # | 验收 | 方法 |
| --- | --- | --- |
| AC01 | 同 key 同体重放返回同一 ticketId | 连发两次 |
| AC02 | 同 key 不同体 → 409 `IDEMPOTENCY_CONFLICT` | 改字段重发 |
| AC03 | 并发同 key → 一件执行、另一件 `IN_PROGRESS` 或同结果 | 两个并发请求 |
| AC04 | 消费者响应字段白名单：**状态只用 `displayState`**，其余字段按各响应自己的白名单 | 比对建单/查询/追加消息/撤销四个响应的 schema |
| AC05 | 多轮 `stalledRounds` 按 §6 变化 | 反复不给单号 |
| AC06 | **"只有 Java 能写草稿"的三重证据**：① Python 进程无 DB 写凭据/无写路径（代码审查 + 依赖清单）② Java 审计表有每条草稿的 `insert` 记录 ③ 同一 `generationTaskId` 重放不产生第二条草稿 | 代码审查 + 查审计表 + 重放 |
| AC07 | 迟到响应被丢弃：`taskEpoch` 变化后旧结果不改状态、不落草稿 | 延迟 Python 12s + 期间发新消息 |
| AC08 | `send` 的 `draftVersion` 不匹配 → 409 `STALE_DRAFT` | 改两次草稿后发旧版本 |
| AC09 | `needHumanReview=true` 且无 `reviewNote` → 422 `REVIEW_NOTE_REQUIRED` | |
| AC10 | 转交非法枚举 → 422；合法 → `TRANSFERRED` | |
| AC11 | 撤销白名单：`CONFIRMED` 撤销 → 409 `STATE_NOT_ALLOWED`；`DRAFT_READY` 撤销成功 | 两条 |
| AC12 | 确认与撤销并发，只有一个 `rowsAffected=1`，另一个 409 | 并发打 |
| AC13 | `policyCheck.allowed=false` 时确认 → 409 `POLICY_REJECTED`，状态不变 | 构造超期单 |
| AC14 | 金额 > `maxRefundableCents` → 拒绝；部分退款/已退过款 → 直接转交 | 三条样例 |
| AC15 | 同订单并发建单：唯一索引生效，仅一单成功，另一单 409 | 并发建 |
| AC16 | 售后无订单号 → `WAITING_INPUT`，且**不**生成草稿、不给金额 | 建单后查状态 |
| AC17 | 补齐订单号 → 回 `AI_RUNNING` → `DRAFT_READY` | |
| AC18 | 政策咨询（无订单号）不进售后状态机，不因缺单号转交 | 发"退货运费谁承担" |
| AC19 | `DECISIONAL` 咨询不直接回复，转 `TRANSFERRED`；`INFORMATIONAL` 直接回复 | 两条 |
| AC20 | 咨询转退款 → 新建 `AFTERSALE`、`parentConsultTicketId` 正确、原单状态不变，且响应回传新单 `ticketId` + `ticketToken` | 检查 `createdTicket` 可用 |
| AC21 | `CONFIRMED → EXECUTING → CLOSED`，且 `executionMode=SIMULATED`、客户文案含"演示环境" | |
| AC22 | 越权订单 → **404 `ORDER_NOT_FOUND`**，与"不存在"同状态、同代码、同文案；403 `FORBIDDEN_SCOPE` 只用于 `ticketToken` 与 `ticketId` 不匹配（v1.4.1 裁决，此前与 §8.5 冲突） | |
| AC23 | 工具时间线顺序与 `errorCode` 正确 | |
| AC24 | 停 Python → Java 降级转人工，不 5xx | |
| AC25 | `traceId` 在 Java/Python/工具日志一致 | grep |
| AC26 | 编辑距离服务端计算：请求里伪造 `editDistance` 并夹带未知字段 | 返回值 = 服务端计算值；未知字段被忽略（公共接口）而不导致 400 |

### 15.2 M-Q（真实模型；QC01–QC12；单独报告）

**集合划分**：开发集 30 例（可调 prompt/阈值）+ 冻结验收集 50 例（只在最终报告使用，调参期间不可看）。

**意图类**（先列清再分层取样，不硬凑组合）：`REFUND_ELIGIBILITY`（能不能退/退多少）、`REFUND_REQUEST`（我要退）、`LOGISTICS`、`POLICY`（时效/运费/流程）、`OTHER`。

| # | 指标 | 口径 |
| --- | --- | --- |
| QC01 | 集合完整性 | 验收集 50 例，5 类各 ≥8 例，覆盖 3 种订单状态与 2 种异常（无单号/查无此单） |
| QC02 | 意图准确率 | 对人工标注；报混淆矩阵 |
| QC03 | 槽位抽取 | `orderNo` 准确率/召回分报 |
| QC04 | 检索命中 | 金标条款 top-3，Recall@3 |
| QC05 | 草稿可用率 | 可直接发/小改/不可用，双人独立评分 + κ |
| QC06 | 引用正确性 | 正确引用/总引用（人工判） |
| QC07 | 幻觉率 | 无依据的事实性断言条数/总条数 |
| QC08 | 置信度分层 | 分别报低置信组、高置信组的错误率；**n=50 不要求"显著"**，只报点估计与区间 |
| QC09 | 成本 | 每例 token、费用 |
| QC10 | 延迟 | P50/P95 |
| QC11 | 版本记录 | 模型版本、prompt 版本、语料版本、检索参数、规则版本全部写入报告 |
| QC12 | 重复运行 | 同集重跑两次，报**意图准确率的差值（百分点）**；不承诺 ≤5%，只报实测波动 |

**go/no-go 预设**（不过线也出报告）：意图准确率 ≥ 0.85；幻觉率 ≤ 5%；草稿可用率 ≥ 0.80。**最多 2 轮调参**，之后冻结出报告；报告写"未达标 + 差距 + 原因假设"，不得改阈值凑数。

---

## 16. 变更规则

1. **v1.3-final 已冻结（2026-11-10）**。契约变更须：改本文 → 升版本（v1.3.1 / v1.4.0…）→ 同步接口/枚举/验收 → 记 §17。代码与本文冲突以本文为准。
2. 不得在代码里临时加枚举/状态/字段而不回写。
3. §0 的验收口径、§13 的前端栈属已确认项，变更需明确说明理由。

---

## 17. 修订记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-11-09 | 首版 |
| v1.1 | 2026-11-10 | 七点修正 |
| v1.2 | 2026-11-10 | 落定 S+Q；前端 Vue3+Vite+SFC；阻塞项拆分 |
| v1.3 | 2026-11-10 | ①补 `WAITING_INPUT` 与售后补单路径、咨询转售后关联规则；②明确咨询免审边界（`replyType`）；③补迁移守卫矩阵、撤销白名单、确认/撤销竞争、`TRANSFERRED` 处理路径；④恢复同订单唯一性（生成列+唯一索引）；⑤入口身份闭合（`X-User-Id` 白名单 + fail-fast）；⑥幂等键前移前端、作用域四元组、并发规则、`taskEpoch` 作废规则；⑦补 9 枚举 / 17 错误码 / `me/orders`、`regenerate`、`reply`、`close`；⑧AC 扩到 26 条（含 AC06 三重证据、政策拒绝、超额、部分退款、并发）；⑨M-Q 改为 dev/held-out、预设 go/no-go、版本记录与重复运行口径；清理残留表述 |
| **v1.3-final** | 2026-11-10 | **冻结**。确认 9 转人工枚举、17 错误码、Q 段阈值 0.85/5%/0.80；冻结后按 §16 变更 |
| **v1.3.1** | 2026-11-10 | 契约评审修订（不改范围）：消费者响应统一 `displayState` + `version`；`/agent/ask` 统一为 `/internal/agent/ask`；建单/追加消息响应字段同步。§11 AC 与阈值口径不变 |
| **v1.4.0** | 2026-11-11 | 一致性修订：①售后补 `REPLIED`，实为 10 态；②`targetId` 逐端点定义；③`currentAttempt` 改为"每生成任务"计数；④多轮口径固定为 6 轮/12 条 + `summary`；⑤`reply`/`close` 补 `requestId`、`regenerate` 补 `expectedVersion`、`send` 去掉服务端派生的 `edited`；⑥`createdTicket` 回传关联单凭据（AC20）；⑦`TRANSFERRED` 收到客户消息保持原状态；⑧退款双阈值合并为一个并写明用途；⑨`needHumanReview` 定义为草稿上的生成时快照；⑩明确 Python 不接收 `policyCheck`；⑪AC04/AC26 措辞按白名单与未知字段语义修正 |
| **v1.4.1** | 2026-11-11 | 评审裁决修订（四项，不改范围）：①AC22 越权订单改为 404 `ORDER_NOT_FOUND`，403 只留给 `ticketToken` 不匹配；②`send` 补响应语义——全部完成 `200`+`CLOSED`、受理成功但执行未完 `202`+`CONFIRMED`（待执行任务须与确认同事务持久化、同 `requestId` 返回原受理结果）、守卫失败 `409/422`、落库失败 `500`；③`TOOL_FAILED` 明确包含 AI 服务故障，靠 `AGENT_UNAVAILABLE` 与组件日志区分，不新增第十个原因；④投诉关键词归 `OUT_OF_SCOPE`，仅明确要求人工才用 `USER_REQUESTED` |
