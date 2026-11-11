# 状态机 + 数据字典

| 项 | 内容 |
| --- | --- |
| 依据 | `docs/BOUNDARY_v1.md` v1.4.0（2026-11-11） |
| 冻结 | 状态名、枚举值、字段语义变更需走 §16 变更规则并升版本 |
| 读者 | Java 后端（落库）、前端（渲染）、Python（只读对齐）、测试（用例来源） |
| 一句话 | 状态机是**唯一**允许改状态的入口；字典规定**谁能看见哪个字段** |

---

## 1. 两类工单，两套状态机

同一个 `aftersale_ticket` 表，用 `category` 区分；**咨询不产生草稿与确认**，售后必须人工确认。

| 类别 | 进入方式 | 状态数 | 终点 |
| --- | --- | --- | --- |
| `CONSULT` 咨询 | 消费者直接提问（政策、流程、运费等） | 7 | `CLOSED` / `CANCELLED` |
| `AFTERSALE` 售后 | 咨询中表达退款意图 → 新建关联单；或直接建单 | 10 | `CLOSED` / `CANCELLED` |

（售后 10 态 = 9 个售后专属态 + 与咨询共享的 `REPLIED`；`REPLIED` 出现在"转人工后坐席直接答复"这一步，不能漏。）

状态全集（两套的并集，共 11 个）：

```
OPEN  PENDING_ACCEPT  AI_RUNNING  WAITING_INPUT  DRAFT_READY
CONFIRMED  EXECUTING  REPLIED  TRANSFERRED  CLOSED  CANCELLED
```

---

## 2. 咨询（CONSULT）迁移表

| From | To | 触发 | 守卫 | 副作用 |
| --- | --- | --- | --- | --- |
| — | `OPEN` | 建单 | `X-User-Id` 在白名单 | 签发 ticketToken；`version=1` |
| `OPEN` | `AI_RUNNING` | 立即（同请求内） | — | 分配 `generationTaskId`，`currentAttempt=1` |
| `AI_RUNNING` | `REPLIED` | `/internal/agent/ask` 返回 `INFORMATIONAL` 且未转交 | `confidence ≥ intent.confidence_threshold`（默认 0.60） | 落 `messages(role=AGENT)`；`stalledRounds=0` |
| `AI_RUNNING` | `WAITING_INPUT` | 槽位缺失 | — | `stalledRounds+1` |
| `AI_RUNNING` | `TRANSFERRED` | 决策类 / 低置信 / 工具失败 | 见 §7 原因表 | 记 `transfer_reason` |
| `WAITING_INPUT` | `AI_RUNNING` | 客户补消息 | 消息长度 1–500 | 新任务：`currentAttempt=1` |
| `REPLIED` | `AI_RUNNING` | 客户追问 | 同上 | 新任务：`currentAttempt=1` |
| `REPLIED` | `TRANSFERRED` | 客户明确要人工 / 决策类 | — | — |
| `TRANSFERRED` | `REPLIED` | 坐席 `reply` | 状态=TRANSFERRED | 落人工消息 |
| `REPLIED`/`TRANSFERRED` | `CLOSED` | 坐席 `close` | — | `closed_at=now()` |
| 6 态（见 §5） | `CANCELLED` | 客户 `cancel` | `expectedVersion` 匹配 | 终态，不可逆 |

## 3. 售后（AFTERSALE）迁移表

| From | To | 触发 | 守卫 | 副作用 |
| --- | --- | --- | --- | --- |
| — | `PENDING_ACCEPT` | 建单 | 可无 `orderNo` | 签发 ticketToken；`activeOrderKey` 生效 |
| `PENDING_ACCEPT` | `AI_RUNNING` | 立即 | `orderNo` 存在 | 分配 `generationTaskId`，`currentAttempt=1` |
| `PENDING_ACCEPT` | `WAITING_INPUT` | 立即 | `orderNo` 缺失 | 生成"请提供订单号"提示（走工具不造事实） |
| `WAITING_INPUT` | `AI_RUNNING` | 客户补 `orderNo` 或追加消息 | 订单归属校验通过 | — |
| `AI_RUNNING` | `DRAFT_READY` | 草稿落库 | `draftVersion≥1`；字段完整 | 旧草稿置 `superseded=1` |
| `AI_RUNNING` | `TRANSFERRED` | 策略拦截 / 无证据 / 工具失败 | 见 §7 | 记 `transfer_reason` |
| `AI_RUNNING` | `WAITING_INPUT` | 槽位缺失（如未说清诉求） | — | `stalledRounds+1` |
| `DRAFT_READY` | `AI_RUNNING` | `regenerate` | — | `taskEpoch+1`；旧草稿 superseded |
| `DRAFT_READY` | `CONFIRMED` | `send` | §5 全部守卫 | 落 `messages(role=AGENT)`；`edited/edit_distance` |
| `TRANSFERRED` | `CONFIRMED` | `send`（坐席仍决定用已有草稿） | 草稿存在且未被 superseded + §5 其余守卫 | 同上；`transfer_reason` 保留供审计 |
| `DRAFT_READY` | `TRANSFERRED` | 坐席 `handoff` | 原因必填且合法 | 记 `transfer_reason` |
| `DRAFT_READY` | `CANCELLED` | 客户 `cancel` | — | — |
| `CONFIRMED` | `EXECUTING` | 执行开始（模拟） | `executionMode=SIMULATED` 时不调真实写接口 | 记 `tool_calls` |
| `EXECUTING` | `CLOSED` | 执行回写成功 | — | `closed_at`；结果消息落库 |
| `EXECUTING` | `TRANSFERRED` | 执行失败且不可重试 | — | `transfer_reason=TOOL_FAILED` |
| `TRANSFERRED` | `REPLIED` | 坐席 `reply` | — | — |
| `TRANSFERRED`/`REPLIED` | `CLOSED` | 坐席 `close` | — | — |
| `TRANSFERRED` | `TRANSFERRED`（自环） | 客户追加消息 | 消息 1–500 | 消息入库并标记"待坐席"；**不**回 `AI_RUNNING`，不清空 `transfer_reason`；`task_epoch+1` 以作废在途任务 |

**`send` 与模拟执行的事务边界**：`send` 一次请求内完成"确认 → 执行 → 回执"，但对客户只体现为一次操作。①事务 1：`→CONFIRMED` + 人工消息 + 审计提交；②事务外：调用 T5 `executeAftersale`（`SIMULATED`，幂等键 `generationTaskId`）；③事务 2：`CONFIRMED→EXECUTING→CLOSED` + 结果消息。第②步失败时第①步不回滚，响应返回 `CONFIRMED` 与非 5xx 错误码，坐席看到"已确认、执行未完成"并可重试；后台按任务记录补偿。

**不允许的直觉操作**（写进测试）：

- 跳过 `DRAFT_READY` 直接 `CONFIRMED`
- 在 `CONFIRMED`/`EXECUTING` 上 `cancel`（钱已在路上，只能转人工）
- 用旧 `draftVersion` 发送（`STALE_DRAFT`）
- 用旧 `expectedVersion` 做任何迁移（`STALE_STATE`）

## 4. 客户可见状态映射

客户永远只看到 6 个词，永远看不到 `AI_RUNNING`/`DRAFT_READY`/`EXECUTING` 这类工序词。

| 内部状态 | 客户显示 | 文案要点 |
| --- | --- | --- |
| `OPEN` / `PENDING_ACCEPT` / `AI_RUNNING` | 处理中 | "正在为您处理" |
| `WAITING_INPUT` | 待补充信息 | "还需要您提供订单号" |
| `DRAFT_READY` / `CONFIRMED` / `EXECUTING` | 处理中 | 草稿未确认前，客户不该看到"已答复" |
| `REPLIED` | 已回复 | 展示回复正文 |
| `TRANSFERRED` | 待人工处理 | "已转交人工客服" |
| `CLOSED` | 已完成 | — |
| `CANCELLED` | 已取消 | — |

"处理中"是**兜底态**：映射表没有命中就落到这里，不允许出现空白或原始枚举。

---

## 5. 守卫矩阵（`send` 的与条件）

| # | 条件 | 失败码 |
| --- | --- | --- |
| 1 | 状态 ∈ {`DRAFT_READY`, `TRANSFERRED`}；`TRANSFERRED` 还要求存在未 superseded 的草稿 | `STATE_NOT_ALLOWED` |
| 2 | 请求 `expectedVersion` == 库 `version` | `STALE_STATE` |
| 3 | 请求 `draftVersion` == 最新草稿版本 | `STALE_DRAFT` |
| 4 | `policyCheck.allowed == true` | `POLICY_REJECTED` |
| 5 | 金额 ≤ `policyCheck.maxRefundableCents`（若 `suggestedAction.amountCents` 非空） | `POLICY_REJECTED` |
| 6 | `needHumanReview==true` 时 `reviewNote` 长度 ≥ 5 | `REVIEW_NOTE_REQUIRED` |
| 7 | 正文不含内部原因码/内部字段名 | `INVALID_ARGS` |

写库用 `UPDATE aftersale_ticket SET state='CONFIRMED', version=version+1 WHERE ticket_id=? AND state IN ('DRAFT_READY','TRANSFERRED') AND version=?`，受影响行数 0 → `STALE_STATE`（避免先查后写）。

> 为什么允许 `TRANSFERRED` 发送：转人工是"加一条人看"的动作，不是"锁死草稿"。坐席在人工队列里仍可能决定直接用已有稿回复，此时不应强迫他重走一遍生成。

---

## 6. 字段字典

### 6.1 `aftersale_ticket`

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `ticket_id` | VARCHAR(32) PK | `T` + yyyyMMdd + 6 位序号 | 对外主键 |
| `category` | ENUM | `CONSULT`/`AFTERSALE` | 决定状态机 |
| `parent_consult_ticket_id` | VARCHAR(32) NULL | 引用本表 | 咨询转售后时指向原咨询单 |
| `user_id` | VARCHAR(32) | 来自签名身份 | 归属；**不接受请求体传值** |
| `order_no` | VARCHAR(32) NULL | — | 售后必填（草稿前）；咨询可空 |
| `state` | VARCHAR(24) | §2/§3 | — |
| `version` | INT | 每次迁移 +1 | 乐观锁；消费者响应里必须返回，否则撤销无法构造 `expectedVersion` |
| `task_epoch` | INT | 以下任一发生即 +1：客户追加消息、`regenerate`、`handoff`、`cancel`、`close` | 作废所有在途异步任务；回写时 epoch 落后一律丢弃 |
| `current_attempt` | INT | 每个新 `generation_task_id` 从 1 开始，同一任务内重试 +1 | **同一任务**上限 2（即 1 次重试），超限 `TOOL_FAILED`；不是整单上限，客户第 N 轮会重置 |
| `stalled_rounds` | INT | 连续未获得必要槽位的追问次数 | ≥ 2 转人工（`INSUFFICIENT_INFO`） |
| `execution_mode` | ENUM | `SIMULATED`/`REAL` | 演示恒 `SIMULATED` |
| `transfer_reason` | VARCHAR(32) NULL | §7 | 转人工原因 |
| `active_order_key` | 生成列 | 唯一索引 | 同用户同订单仅一条未结束单 |
| `created_at`/`updated_at`/`closed_at` | DATETIME(3) | — | — |

### 6.2 `ticket_message`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `message_id` | BIGINT PK | — |
| `ticket_id` | VARCHAR(32) | — |
| `role` | ENUM `CUSTOMER`/`AGENT`/`SYSTEM` | 对外只暴露前两者 |
| `text` | VARCHAR(1000) | 客户侧输入 ≤ 500 |
| `created_at` | DATETIME(3) | — |

### 6.3 `draft`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `draft_id` | VARCHAR(32) PK | — |
| `ticket_id` | VARCHAR(32) | — |
| `draft_version` | INT | 同单内递增 |
| `generation_task_id` | VARCHAR(64) | **唯一**（防重复生成） |
| `intent` / `confidence` / `reply_type` | — | 只给坐席与审计 |
| `reply_draft` | TEXT | 坐席编辑的起点 |
| `suggested_action` | JSON | `{action, amountCents, needHumanConfirm}` |
| `citations` | JSON | 政策条款引用 |
| `policy_check` | JSON | `{allowed, code, maxRefundableCents, ...}` |
| `policy_version` | VARCHAR(32) | 生成时政策版本；与 `policy_check` 同一快照 |
| `need_human_review` | TINYINT | **生成时**判定并落库；`send` 读此值，不按当前配置重算 |
| `superseded` | TINYINT |不删 |

### 6.4 `tool_call`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `step` | INT | 顺序，从 1 开始 |
| `name` | VARCHAR(64) | `queryOrder`/`getLogistics`/… |
| `ok` | TINYINT | — |
| `latency_ms` | INT | — |
| `error_code` | VARCHAR(32) NULL | 封闭枚举 |
| `request_hash` / `response_hash` | CHAR(64) | 证据链，可复核 |

### 6.5 `idempotency_record`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `user_id` / `endpoint` / `request_id` | — | 见边界书 §7.1 |
| `target_id` | VARCHAR(64) | **请求作用的资源**：建单为 `orderNo`（无单号用字面量 `NOORDER`）；工单类写接口为 `ticketId`。缺失或空 → `INVALID_ARGS` |
| `request_hash` | CHAR(64) | 规范化请求体 sha256；不一致 → `IDEMPOTENCY_CONFLICT` |
| `state` | ENUM | `IN_PROGRESS` / `DONE` / `FAILED` |
| `updated_at` | DATETIME(3) | 60 秒租约的基准 |

---

## 7. 枚举字典

### 7.1 转人工原因（9 个，封闭）

| 值 | 何时 | 客户可见文案 |
| --- | --- | --- |
| `LOW_CONFIDENCE` | 意图置信度 < 阈值 | "已转交人工客服" |
| `NO_EVIDENCE` | RAG 检索不到条款 | 同上 |
| `POLICY_BLOCKED` | 政策判定不允许（如已发货退款） | 同上 |
| `TOOL_FAILED` | 工具重试后仍失败 | 同上 |
| `AMBIGUOUS_ORDER` | 一单多包裹/信息冲突 | 同上 |
| `ORDER_NOT_FOUND` | 归属校验不通过 | 同上 |
| `OUT_OF_SCOPE` | 超出售后范围（换货、价保等） | 同上 |
| `USER_REQUESTED` | 客户明确要人工 | 同上 |
| `INSUFFICIENT_INFO` | 连续 2 轮未补齐槽位 | 同上 |

**客户看到的永远是同一句**：原因码只进坐席面板与审计表。

### 7.2 错误码（17 个）

| 码 | HTTP | 可重试 | 典型场景 |
| --- | --- | --- | --- |
| `INVALID_ARGS` | 422 | 否 | 文本空/超长、枚举非法、含内部码 |
| `UNAUTHENTICATED` | 401 | 否 | 无 token / 签名过期 |
| `FORBIDDEN_SCOPE` | 403 | 否 | ticketToken 与 ticketId 不匹配（订单级越权一律 404，防枚举） |
| `ORDER_NOT_FOUND` | 404 | 否 | 订单不存在或不属于本人 |
| `TICKET_NOT_FOUND` | 404 | 否 | 工单不存在 |
| `STATE_NOT_ALLOWED` | 409 | 否 | 状态不允许该操作 |
| `DUPLICATE_REQUEST` | 200/409 | 否 | 同 requestId 已完成，返回首次结果 |
| `IDEMPOTENCY_CONFLICT` | 409 | 否 | 同 key 不同载荷 |
| `IN_PROGRESS` | 409 | 是（稍后） | 同 key 正在处理 |
| `STALE_DRAFT` | 409 | 否 | 草稿已被重新生成 |
| `STALE_STATE` | 409 | 否 | 版本号落后 |
| `POLICY_REJECTED` | 409 | 否 | 政策守卫不通过 |
| `REVIEW_NOTE_REQUIRED` | 422 | 否 | 低置信发送未写复核说明 |
| `TOOL_UNAVAILABLE` | 503 | 是 | 下游不可用 |
| `TOOL_TIMEOUT` | 504 | 是 | 下游超时 |
| `AGENT_UNAVAILABLE` | 503 | 是 | Python 不可用 → 转人工兜底 |
| `PERSISTENCE_FAILED` | 500 | 是 | 写库失败，**不得**返回成功 |

---

## 8. 不变量（测试要逐条断言）

1. `version` 单调递增，同一工单不存在两个相同 `version` 的已提交状态。
2. `activeOrderKey` 唯一：同 `(user_id, order_no)` 最多一条**售后**未结束单；`CONSULT` 单、`CLOSED`/`CANCELLED`、`order_no IS NULL` 一律置 NULL。
3. `draft.generation_task_id` 唯一：重复投递不产生第二份草稿。
4. 每次 `regenerate` 后，旧 `draftVersion` 必 `STALE_DRAFT`。
5. `task_epoch` 落后的异步回写一律丢弃。
6. 客户视图永远不含 `intent`/`confidence`/`tool_calls`/`policy_check`/`transfer_reason`，也不含 `SYSTEM` 消息。（`stalled_rounds` 不在上述禁返列表内——不变量 6 从未禁止它——但它同样不回消费者，只进坐席面板。）
7. 金额单位一律**分**（整数），任何 `double` 都是缺陷。
8. 同 `(user_id, endpoint, target_id, request_id)` 的 `request_hash` 必须一致；不一致即 `IDEMPOTENCY_CONFLICT`，不允许"按新载荷重放"。
9. `IN_PROGRESS` 带租约：`updated_at` 超过 60 秒未推进即视为失效，可被新请求接管；接管用 `UPDATE ... WHERE state='IN_PROGRESS' AND updated_at < ?`，0 行则返回 `IN_PROGRESS`。

---

## 9. DDL 草案（MySQL 8）

```sql
CREATE TABLE aftersale_ticket (
  ticket_id    VARCHAR(32)  NOT NULL,
  category     ENUM('CONSULT','AFTERSALE') NOT NULL,
  parent_consult_ticket_id VARCHAR(32) NULL,
  user_id      VARCHAR(32)  NOT NULL,
  order_no     VARCHAR(32)  NULL,
  state        VARCHAR(24)  NOT NULL,
  version      INT          NOT NULL DEFAULT 1,
  task_epoch   INT          NOT NULL DEFAULT 0,
  current_attempt INT       NOT NULL DEFAULT 0,
  stalled_rounds  INT       NOT NULL DEFAULT 0,
  execution_mode  ENUM('SIMULATED','REAL') NOT NULL DEFAULT 'SIMULATED',
  transfer_reason VARCHAR(32) NULL,
  active_order_key VARCHAR(80) GENERATED ALWAYS AS (
    CASE WHEN category = 'CONSULT' OR state IN ('CLOSED','CANCELLED') OR order_no IS NULL THEN NULL
         ELSE CONCAT(user_id, ':', order_no) END) STORED,
  created_at   DATETIME(3) NOT NULL,
  updated_at   DATETIME(3) NOT NULL,
  closed_at    DATETIME(3) NULL,
  PRIMARY KEY (ticket_id),
  UNIQUE KEY uk_active_order (active_order_key),
  KEY idx_user_state (user_id, state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ticket_message (
  message_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  ticket_id  VARCHAR(32) NOT NULL,
  role       ENUM('CUSTOMER','AGENT','SYSTEM') NOT NULL,
  text       VARCHAR(1000) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  KEY idx_ticket (ticket_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE draft (
  draft_id VARCHAR(32) PRIMARY KEY,
  ticket_id VARCHAR(32) NOT NULL,
  draft_version INT NOT NULL,
  generation_task_id VARCHAR(64) NOT NULL,
  intent VARCHAR(32) NULL,
  confidence DECIMAL(4,3) NULL,
  reply_type ENUM('INFORMATIONAL','DECISIONAL') NULL,
  reply_draft TEXT NOT NULL,
  suggested_action JSON NULL,
  citations JSON NULL,
  policy_check JSON NULL,
  policy_version VARCHAR(32) NULL,
  need_human_review TINYINT NOT NULL DEFAULT 0,
  superseded TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME(3) NOT NULL,
  UNIQUE KEY uk_task (generation_task_id),
  UNIQUE KEY uk_ver (ticket_id, draft_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE tool_call (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  ticket_id VARCHAR(32) NOT NULL,
  step INT NOT NULL,
  name VARCHAR(64) NOT NULL,
  ok TINYINT NOT NULL,
  latency_ms INT NOT NULL,
  error_code VARCHAR(32) NULL,
  request_hash CHAR(64) NULL,
  response_hash CHAR(64) NULL,
  created_at DATETIME(3) NOT NULL,
  KEY idx_ticket_step (ticket_id, step)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE idempotency_record (
  user_id      VARCHAR(32) NOT NULL,
  endpoint     VARCHAR(64) NOT NULL,
  target_id    VARCHAR(64) NOT NULL,
  request_id   CHAR(36)    NOT NULL,
  request_hash CHAR(64)    NOT NULL,           -- 规范化请求体 sha256；不一致 → IDEMPOTENCY_CONFLICT
  state        ENUM('IN_PROGRESS','DONE','FAILED') NOT NULL,
  response     JSON NULL,
  error_code   VARCHAR(32) NULL,               -- FAILED 时记录，重放返回同一错误
  updated_at   DATETIME(3) NOT NULL,           -- 租约：IN_PROGRESS 超 60s 未更新视为失效
  created_at   DATETIME(3) NOT NULL,
  PRIMARY KEY (user_id, endpoint, target_id, request_id),
  KEY idx_recover (state, updated_at)          -- 扫描僵死记录
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**MySQL 行为必须在真机验证**：生成列 + 唯一索引、`INSERT ... ON DUPLICATE KEY`、`ENUM` 与 `utf8mb4` 排序规则。H2（MySQL 模式）只用于本地开发，**不能**作为"唯一索引生效"的证据（H2 对生成列与唯一约束的实现与 MySQL 有差异）。

H2（`dev` profile）可用同结构，生成列语法差异：H2 需 `AS (...)` 不带 `STORED`。

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.3 | 2026-11-10 | 首版，对齐 BOUNDARY_v1 v1.3-final |
| v1.4 | 2026-11-10 | 契约评审修订：`send` 允许 `TRANSFERRED`；`task_epoch` 增补触发场景；`stalled_rounds` 阈值为 2；`current_attempt` 上限 2；消费者响应补 `version`；幂等表加 `request_hash` 与 60s 租约；`active_order_key` 排除咨询单；标注 MySQL 真机验证要求 |
| v1.5 | 2026-11-11 | 一致性修订：售后改 10 态（含 `REPLIED`）；`current_attempt` 改为按生成任务计数；新增 `TRANSFERRED` 收消息自环与 `send` 事务边界；`draft.policy_version` / `draft.need_human_review` 落库；补 `stalled_rounds` 不进客户响应的说明 |
