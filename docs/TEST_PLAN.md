# 测试与验收用例

| 项 | 内容 |
| --- | --- |
| 依据 | `docs/BOUNDARY_v1.md` v1.4.0 §15.1（AC01–AC26）、§15.2（QC01–QC12） |
| 范围 | 接口、状态机、幂等、越权、降级、前端呈现 |
| 原则 | **每条用例都必须能变红**；只会一直绿的测试视为未编写 |
| 现状 | M0 未开工；"通过"列全部为空，未执行 |
| 编号 | AC01–AC26 取自边界书 §15.1；AC03b/AC03c/AC04b/AC15b/AC19b 为本文件补充（评审后新增，边界书未收录）；AG-R1/AG-C1 覆盖 `reply`/`close` 两个此前无直接用例的端点 |

---

## 1. 分层

| 层 | 工具 | 覆盖 | 频率 |
| --- | --- | --- | --- |
| L1 单元 | JUnit 5 / pytest | 状态迁移、守卫、编辑距离、槽位抽取 | 每次提交 |
| L2 契约 | `springdoc` + `openapi-diff`；pytest 校验 `AskResponse` | 字段名/枚举/必填/`additionalProperties` | 每次提交 |
| L3 集成 | Spring Boot Test + H2(dev)；**MySQL 用 Testcontainers 或本地实例** | 接口 + DB 行为 | 每次提交 |
| L4 端到端 | Playwright | 三页面 + 演示脚本 | 发版 |
| L5 非功能 | 并发/故障注入 | AC03/AC12/AC15/AC24 | 发版前 |

> 数据库行为（生成列唯一索引、`INSERT ... ON DUPLICATE KEY`、租约接管）**必须在真实 MySQL 8 上验一次**，H2 通过不算数。

---

## 2. AC 用例表

前置：`dev` profile；操作者 U001（7 单）、U002（1 单，O1004）。

| ID | 用例 | 步骤 | 期望 | 通过 |
| --- | --- | --- | --- | --- |
| AC01 | 幂等重放 | 同 `requestId` 同体连发两次建单 | 同 `ticketId`；DB 1 行 | ☐ |
| AC02 | 幂等冲突 | 同 `requestId` 改文本重发 | `409 IDEMPOTENCY_CONFLICT` | ☐ |
| AC03 | 幂等并发 | 两个并发请求同 key | 一个成功，另一个 `409 IN_PROGRESS` 或同结果；DB 1 行 | ☐ |
| AC03b | 键跨目标复用 | 工单 A 的 `requestId` 拿去建工单 B（同 endpoint、不同 `targetId`） | 两个都成功（作用域含 `targetId`）；反例：去掉 `targetId` 后 AC03b 必须失败 | ☐ |
| AC03c | 僵死租约 | 手工把 `IN_PROGRESS` 行的 `updated_at` 改到 61 秒前，再发同 key | 被接管并完成，不永久 409 | ☐ |
| AC04 | 消费者字段白名单 | `GET /api/tickets/{id}`、建单、追加消息、撤销四个响应 | **状态只用 `displayState`**；其余按各响应白名单（建单：`ticketId/ticketToken/version/category/createdAt/executionMode`；查询：`ticketId/reply/messages/updatedAt`）；无 `state`、`intent`、`confidence`、`toolCalls`、`policyCheck`、`transferReason`、`SYSTEM` | ☐ |
| AC04b | 撤销可构造 | 建单取 `version` → 直接 `cancel(expectedVersion)` | 200；不再出现"前端拿不到版本" | ☐ |
| AC05 | 连续缺槽位 | 连续 2 轮不发订单号 | 第 1 轮追问；第 2 轮 `TRANSFERRED(INSUFFICIENT_INFO)`；坐席视图 `stalledRounds=2`，消费者响应**不含**该字段 | ☐ |
| AC06 | 写权归属 | ① 查 Python 依赖与代码无 DB 写 ② 查审计 ③ 重放同 `generationTaskId` | 三条均成立；草稿仅 1 条 | ☐ |
| AC07 | 迟到响应 | **用可注入延迟的测试桩**（scripted 本身是同步的，不能真等 12s）：先让 `ask` 停在桩里，期间客户发新消息（`taskEpoch+1`），再放行旧响应 | 旧响应丢弃，状态与草稿均不被改写 | ☐ |
| AC08 | 旧草稿 | 生成两次后用 v1 发送 | `409 STALE_DRAFT` | ☐ |
| AC09 | 复核说明 | `needHumanReview=true` 且 `reviewNote` 空 | `422 REVIEW_NOTE_REQUIRED` | ☐ |
| AC10 | 转交枚举 | 发 `reason=FOO`；再发 `POLICY_BLOCKED` | 前者 422；后者 `TRANSFERRED` | ☐ |
| AC11 | 撤销白名单 | `DRAFT_READY` 撤销；`CONFIRMED` 撤销 | 前者成功；后者 `409 STATE_NOT_ALLOWED` | ☐ |
| AC12 | 确认/撤销并发 | 同时打 `send` 与 `cancel` | 只有一个 `rowsAffected=1`，另一个 409 | ☐ |
| AC13 | 政策拦截 | 已签收超期单点发送 | `409 POLICY_REJECTED`，状态仍 `DRAFT_READY` | ☐ |
| AC14 | 金额守卫 | ① 金额 > `maxRefundableCents` ② 部分退款 ③ 已退过款 | ① 拒绝 ②③ 转交 | ☐ |
| AC15 | 同单唯一 | 并发建两张 `(U001,O1001)` 售后单 | 仅 1 成功，另一 409 | ☐ |
| AC15b | 咨询不占键 | 先建 `(U001,O1001)` 咨询单，再建同订单售后单 | 售后单成功（`active_order_key` 对 CONSULT 置 NULL） | ☐ |
| AC16 | 无单号售后 | 建售后单不给订单号 | `WAITING_INPUT`；无草稿、无金额 | ☐ |
| AC17 | 补齐单号 | AC16 后补 `O1001` | `AI_RUNNING → DRAFT_READY` | ☐ |
| AC18 | 政策咨询 | 新建咨询问"退货运费谁承担" | 不因缺单号转交；`REPLIED` | ☐ |
| AC19 | 回复类型 | ① "七天从哪天算" ② "订单实付多少钱" ③ "帮我退了吧" | ① `INFORMATIONAL` ② `INFORMATIONAL`（**含金额不等于决策**）③ `DECISIONAL` 转交 | ☐ |
| AC19b | 条件式诉求 | "能退的话就退了吧" | `REFUND_REQUEST` 且 `slots.conditional=true`，仍需确认 | ☐ |
| AC20 | 咨询转售后 | 咨询中表达退款 | 新建 `AFTERSALE`，`parentConsultTicketId` 正确，原单状态不变；响应含 `createdTicket.ticketId` + `ticketToken`，用该 token 能直接查新单 | ☐ |
| AC21 | 模拟执行 | 确认后观察链路 | `CONFIRMED→EXECUTING→CLOSED`；`SIMULATED`；客户文案含"演示环境，未真实退款" | ☐ |
| AC22 | 越权 | U001 的 token 查 O1004 | `404 ORDER_NOT_FOUND`，与不存在同文案 | ☐ |
| AC23 | 时间线 | 触发一次含失败工具的流程 | 步骤递增、`errorCode` 正确、失败标红 | ☐ |
| AC24 | 降级 | 停掉 Python 后建单 | 转人工，HTTP 非 5xx | ☐ |
| AC25 | traceId | 同一请求三处日志 | `traceId` 一致 | ☐ |
| AC26 | 编辑距离 | 发送改动后的正文，并在请求体夹带伪造 `editDistance=0` 与未知字段 `foo` | 服务端重算并返回真实距离（与库一致）；未知字段被忽略，不返回 422 | ☐ |
| AG-R1 | 坐席回复 | `TRANSFERRED` 状态 `reply`；再对 `DRAFT_READY` `reply` | 前者 `REPLIED` + 消息入库；后者 `409 STATE_NOT_ALLOWED` | ☐ |
| AG-C1 | 坐席关闭 | `TRANSFERRED` → `close`；再对 `CLOSED` `close` | 前者 `CLOSED` + `closed_at`；后者 409 | ☐ |

---

## 3. QC 用例（M-Q，50 条 holdout）

| ID | 指标 | 方法 | 性质 |
| --- | --- | --- | --- |
| QC01 | 集合完整性 | 50 例，5 类各 ≥8，覆盖 3 种订单状态 + 2 种异常 | 前置条件 |
| QC02 | 意图准确率 | 5 类混淆矩阵；`HANDOFF` 单列不计入分母 | **go/no-go ≥ 0.85** |
| QC03 | 槽位抽取 | `orderNo` 精确率/召回分报 | 报告项（开发目标 ≥0.90） |
| QC04 | 检索命中 | 金标条款 Recall@3 | 报告项 |
| QC05 | 草稿可用率 | 双人独立评分 + Cohen's κ | **go/no-go ≥ 0.80**（κ 同时报告） |
| QC06 | 引用正确性 | 引用是否支持结论 | 报告项（开发目标 ≥0.85） |
| QC07 | 幻觉率 | 无依据事实断言 / 总断言 | **go/no-go ≤ 5%** |
| QC08 | 置信度分层 | 高/低置信组错误率 | 报告项，只报点估计 |
| QC09 | 成本 | 每例 token、费用 | 直接报数值 |
| QC10 | 延迟 | P50/P95 | 直接报数值 |
| QC11 | 版本记录 | 模型/prompt/语料/检索参数/规则版本 | 缺一项即报告无效 |
| QC12 | 重复运行 | 同集跑两次，报意图准确率差值（百分点） | 报实测波动，不承诺 ≤5% |

**编号以边界书 §15.2 为准**（QC03=槽位、QC04=检索、QC05=草稿、QC07=幻觉），本表已对齐。只有 **QC02/QC05/QC07** 是 go/no-go，其余**不得**被追加为验收门槛。

---

## 4. 测试数据

| 数据集 | 内容 | 用途 |
| --- | --- | --- |
| `orders-basic` | U001：O1001 PAID / O1002 SHIPPED / O1003 DELIVERED 超期 / O1005 PAID / O1006 PAID 25k / O1007 DELIVERED 期内 / O1008 SHIPPED；U002：O1004 | AC 全量 |
| `orders-dirty` | 金额 0、已全额退款、一单两包裹、状态缺失、`paidAt` 为空 | 防御性（AC14/AC23） |
| `policies-v1` | 4 篇政策，≥40 chunk（**检索语料**） | RAG |
| `qa-200` | 30 dev / 50 holdout / 120 regression（**评测样本，人工编写**） | QC |

**语料与评测集必须分离**：`qa-200` 的答案不得直接抄 `policies-v1` 原文，否则 Recall@3 虚高；两者的题目重合度需在 QC01 时人工抽查一遍并记录。

夹具要**故意脏**：字段缺失、状态与物流不一致、金额为分但页面显示元。

---

## 5. 反向注入（证明测试有效）

| # | 注入缺陷 | 应失败 |
| --- | --- | --- |
| 1 | 消费者视图透传 `transferReason` 或 `state` | AC04 |
| 2 | 去掉 `active_order_key` 唯一索引 | AC15 |
| 3 | `send` 不校验 `draftVersion` | AC08 |
| 4 | 编辑距离用前端传值 | AC26 |
| 5 | 幂等作用域去掉 `targetId` | **AC03b**（AC03 检测不到：它只测同目标并发） |
| 6 | 降级时返回 500 | AC24 |
| 7 | 撤销白名单加上 `CONFIRMED` | AC11 |
| 8 | 幂等不比对 `request_hash` | AC02 |
| 9 | `active_order_key` 未排除 CONSULT | AC15b |
| 10 | 消费者响应透传 `state` / `stalledRounds` / `transferReason` | AC04 |
| 11 | `reply` 忽略 `requestId`（重试产生两条消息） | AG-R1 |
| 12 | 关联单创建后不返回 `ticketToken` | AC20 |

---

## 6. 运行方式（M0 落地后）

```bash
# Java（dev = H2）
mvn -q -Dspring.profiles.active=dev test

# 真实 MySQL（容器或本地）
mvn -q -Pmysql -Dtest='*MysqlIT' test

# 契约
mvn -q springdoc:generate && openapi-diff docs/api/openapi.yaml target/openapi.json

# Python
pytest -q

# 端到端
npx playwright test
```

---

## 7. 通过判定

| 门 | 条件 |
| --- | --- |
| 合入 | L1–L3 全绿；AC01–AC26 + AG-R1/AG-C1 至少 25 条绿且无 P0 缺陷 |
| 演示 | AC04/AC05/AC16/AC17/AC19/AC19b/AC21/AC22/AC24 必绿 |
| 发版 | 全部绿 + 9 条注入全红 + MySQL 行为已验证 |
| 禁止 | 用 mock 替换被测逻辑后宣称通过；跳过失败用例；只跑一次就宣称稳定 |

---

## 8. 明确不测

- 真实资金链路（`REAL` 未实现）
- 大促并发（无容量结论）
- 真实模型效果（QC 只在 50 条 holdout 上给点估计，不做显著性）
- 浏览器兼容（只测 Chromium）
