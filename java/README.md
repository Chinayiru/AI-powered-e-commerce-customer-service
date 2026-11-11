# 售后辅助处理 Agent — Java 业务后端

客户提交售后请求 → AI 只给出意图、事实、政策依据与回复草稿 → 坐席确认后由 Java 执行（当前为 `SIMULATED`，不碰真实资金）。本仓库实现契约中的 **Java 业务后端（M-S）**；Python AI 层不在本仓库内，默认使用内置 `scripted` 桩完成确定性验收。

- 契约：`docs/BOUNDARY_v1.md` v1.4.1、`docs/api/openapi.yaml` v1.5.1、`docs/DATA_DICTIONARY.md` v1.5
- 技术栈：Java 17、Spring Boot 3.3.5、MyBatis、H2（dev/test）/ MySQL 8（prod）、Lombok、springdoc
- 金额单位：**分**
- 执行模式：`SIMULATED`

## 1. 快速开始

环境要求：JDK 17、Maven 3.6+。当前机器 PATH 上默认是 JDK 8，必须显式指定：

```powershell
$env:JAVA_HOME="$env:USERPROFILE\.jdks\corretto-17.0.9"
$env:Path="$env:JAVA_HOME\bin;$env:Path"
```

```powershell
cd H:\电商工单ai\java
mvn -B test                 # 19 个 H2 集成测试
mvn -DskipTests package
java -jar target\aftersale-agent-java-0.1.0-SNAPSHOT.jar
# http://localhost:8080 ，Swagger: /swagger-ui.html
```

> 本机在中文路径下执行 `mvn spring-boot:run` 曾出现 `ClassNotFoundException`（Maven fork 的 classpath 问题）。推荐使用上面的 `package` + `java -jar`。dev 使用 H2 内存库，重启后数据清空。

可用 profile：

| profile | 说明 |
| --- | --- |
| `dev`（默认） | H2 内存库、MySQL 兼容模、H2 Console `/h2-console` |
| `test` | 独立 H2 内存库，集成测试使用 |
| `mysql` | 读 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`，执行 `db/schema-mysql.sql` |
| `prod` | 关闭演示头身份，要求 SSO/真实密钥，启动自检失败即拒绝启动 |

## 2. 5 分钟冒烟

```bash
# 1) 咨询：订单 O1001 想退款
curl -X POST http://localhost:8080/api/tickets \
  -H "Content-Type: application/json" -H "X-User-Id: U001" \
  -d '{"category":"CONSULT","text":"我买的订单 O1001 想退款","orderNo":"O1001","requestId":"11111111-1111-4111-8111-111111111111"}'

# 2) 用返回的 ticketId + ticketToken 继续对话，会新建关联售后单
curl -X POST http://localhost:8080/api/tickets/{ticketId}/messages \
  -H "Content-Type: application/json" -H "Authorization: Bearer {ticketToken}" \
  -d '{"text":"那就帮我退了吧","requestId":"22222222-2222-4222-8222-222222222222"}'

# 3) 坐席视图：看到 DRAFT_READY、退款 5800 分、needHumanReview=true
curl http://localhost:8080/api/agent/tickets/{afterSaleTicketId} \
  -H "X-Agent-Token: demo-agent-token"

# 4) 坐席确认发送（金额 > 5000 必须写复核说明）
curl -X POST http://localhost:8080/api/agent/tickets/{afterSaleTicketId}/send \
  -H "Content-Type: application/json" -H "X-Agent-Token: demo-agent-token" \
  -d '{"text":"已为您提交退款申请（演示环境，未真实退款）。","draftVersion":1,"reviewNote":"已核对订单与金额","expectedVersion":3,"requestId":"33333333-3333-4333-8333-333333333333"}'
```

演示订单夹具（`OrderToolService`）：

| 订单 | 用户 | 状态 | 额/可退 | 用途 |
| --- | --- | --- | --- | --- |
| O1001 | U001 | PAID | 5800 / 5800 | 待发货可退，超过 5000 需复核 |
| O1002 | U001 | SHIPPED | 12900 | 物流咨询 |
| O1003 | U001 | DELIVERED | 8800 / 8800 | 签收 30 天，超 7 天窗口 |
| O1004 | U002 | SHIPPED | 9900 | U001 访问应 404 |
| O1006 | U001 | PAID | 25000 | 高金额必须复核 |
| O1007 | U001 | DELIVERED | 6600 / 6600 | 签收 1 天，窗口内 |
| O1008 | U001 | SHIPPED | 4000 | 两包裹，一签收一在途 |
| O1010 | U001 | DELIVERED | 5000 / 0 | 已全额退款 |
| O1011 | U001 | SHIPPED | 7200 | 物流异常 |
| O9999 | — | — | — | 查无订单，两轮后转人工 |

## 3. 目录

```
java/
├── pom.xml
└── src/
    ├── main/java/com/chinayiru/aftersale/
    │   ├── api/           消费者、坐席、内部工具 Controller + DTO
    │   ├── auth/          ticketToken、内部 HMAC、演示身份守卫
    │   ├── common/        错误码、异常、traceId、JSON、哈希
    │   ├── domain/        11 态状态机、实体、展示状态
    │   ├── mapper/        MyBatis 注解 Mapper
    │   ├── policy/        退款政策规则引擎
    │   ├── service/       幂等、建单、生成、确认执行、审计
    │   ├── tool/          订单/物流 Mock 工具
    │   └── agent/         Scripted / HTTP 两种 Agent 客户端
    ├── main/resources/
    │   ├── application*.yml
    │   └── db/            H2 / MySQL DDL
    └── test/java/...      ApiIntegrationTest（19 用例）
```

## 4. 关键实现说明

### 身份

- 消费者：演示阶段用 `X-User-Id`（仅 U001/U002），建单后返回 HMAC 签名的 `ticketToken`；后续查询、发消息、撤销只认 Bearer token，且 token 的 `ticketId` 必须与路径一致。
- 坐席：`X-Agent-Token`（演示值 `demo-agent-token`，生产从环境变量注入）。
- 内部工具：`X-Internal-Identity`，HMAC 覆盖 `userId/role/exp/nonce`；nonce 去重键为 `nonce|userId|role|path`，同一 Python 请求多次调用工具不会被误判为重放。

### 状态与生成

- 11 个内部状态；客户响应只输出 6 个 `displayState`（处理中/待补充信息/待人工处理/已回复/已完成/已取消），不泄漏 `state`、`intent`、`confidence`、`policyCheck` 等内部字段。
- 咨询中识别到退款请求：原咨询单保持 `REPLIED`，新建 `parent_consult_ticket_id` 指向原单的售后单，响应通过 `createdTicket` 回传新单号与 token。
- 生成任务带 `generationTaskId/taskEpoch/currentAttempt`；异步结果回写前校验三者与 `AI_RUNNING` 状态，迟到结果丢弃并审计。
- 草稿只由 Java 落库；`needHumanReview`、`policyCheck` 在生成时快照，`send` 不重算。

### 确认发送

`send` 守卫顺序：状态 → `expectedVersion` → 草稿版本 → `policyCheck.allowed` → 金额上限 → 复核说明（≥5 字）→ 正文不含内部码。

- 事务 1：`DRAFT_READY/TRANSFERRED → CONFIRMED`，写坐席消息、待执行任务、审计；
- 事务外：模拟执行；
- 事务 2：`CONFIRMED → EXECUTING → CLOSED`，写结果消息。
- 全部成功返回 200 `SendResult`；执行失败返回 202 且状态停在 `CONFIRMED`，待执行任务已与确认同事务持久化；同一 `requestId` 重放返回首次结果。

### 幂

作用域 `(userId, endpoint, targetId, requestId)` + 请求体 sha256；`requestId` 由客户端生成并复用。

- 同 key 同体：重放首次结果；
- 同 key 异体：409 `IDEMPOTENCY_CONFLICT`；
- 正在处理且租约未过期：409 `IN_PROGRESS`（`Retry-After: 1`），60 秒后可接管；
- 4xx 结果也持久化；5xx 删除记录，允许换 `requestId` 重试。

### 政策

- 7 天无理由自签收**次日**起算；仅退款只在未发货成立。
- 硬限为 `policyCheck.maxRefundableCents`；部分退款、已退过款、非整单请求直接 `TRANSFERRED(POLICY_BLOCKED)`，不给金额。
- 已签收超窗口仍可生成草稿（`allowed=false`），但 `send` 必须 409 `POLICY_REJECTED`。
- 金额 > `app.refund.auto-suggest-limit-cents=5000` 时必须写 `reviewNote`。

### 契约取舍（已在代码注释/本文件记录）

1. **工单号**：数据字典与示例使用 `T + yyyyMMdd + 6 位序号`（如 `T202611110001`）；边界书 §4.3 的“4 位”与之冲突，本实现采用 6 位。
2. 为持“迟到响应”和 202 承诺，增加实现字段/表：`aftersale_ticket.generation_task_id`、`execution_task`、`audit_log`、`ticket_sequence`。这些不改变对外响应字段。
3. 内部 nonce 去重按“身份 + 路径”隔离，避免 Python 一次请求内多次工具调用被误杀；契约只要求 nonce 5 分钟内唯一，这里是更窄的实现。
4. `app.agent.mode=scripted` 是验收桩；`http` 模式会严格解析 Python `/internal/agent/ask` 响应，未知字段直接失败。

## 5. 测试

```powershell
mvn -B test
```

`ApiIntegrationTest` 当前 **19/19 通过**，覆盖：

- 消费者响应白名单（无 `state/intent/confidence` 等）；
- 同 `requestId` 重放、异体冲突；
- 同订单重复售后、咨询转售后 `createdTicket`；
- 无单号两轮转人工、O9999 两轮 `ORDER_NOT_FOUND`；
- 超 7 天窗口草稿但 `send` 409、金额/复核说明校验；
- 已全额退款转 `POLICY_BLOCKED` 且不出草稿；
- `regenerate` 后旧 `draftVersion` → `STALE_DRAFT`；
- 撤销后二次撤销 409；
- ticketToken 作用域/缺失 403/401；
- 未知字段忽略、编辑距离服务端计算；
- `X-Trace-Id` 落入审计；
- 内部工具身份、nonce 重放、越权 404；
- `handoff → reply → close` 与 `send` 幂等后消费者看到 `CLOSED`。

未覆盖/未验证：真实并发竞争（AC03/AC12/AC15 的线程级竞争）、执行失败 202 分支（模拟执行恒成功）、真实 MySQL 8 的生成列/唯一索引、Python 真实模型效果（M-Q）。

## 6. 已知限制

- H2 的 MySQL 兼容模式不等于 MySQL 真机；`schema-mysql.sql` 中 `STORED` 生成列与唯一索引需在 MySQL 8 上再跑一次 DDL 验证。
- 取号使用 `ticket_sequence` 表 + 单实例 `synchronized`；多实例部署需改为数据库原子取号或分布式 ID。
- 未包含前端、Python AI 层、真实 SSO、真实退款通道。
- `X-User-Id` 演示身份仅用于 M-S 验收；`prod` profile 会在启动时拒绝演示配置。
