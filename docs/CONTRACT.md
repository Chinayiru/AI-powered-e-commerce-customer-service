# 边界确认书 v1 · 电商售后工单处理

> **状态**：待确认。确认后本文件冻结为契约；第 3–10 章的任何字段、枚举值、状态迁移、reason code 变更，都必须走 ADR + 版本号 + 迁移说明，并在 `tests/contract` 增加对应断言。
> **前身**：`H:\deep工作区\项目搭建\_archive\aftermarket-agent-code-20261104.zip`（2026-11-04）。该备份只提供**契约形状**（envelope / ToolResult / trace 字段 / 错误码风格），**不提供**本期领域模型——它的 4 个意图里没有"仅退款 / 退货退款"之分，也没有平台适配层。本期领域模型从零定义。

---

## 0. 这份文档解决什么

它不解释"为什么做这个项目"，只回答三个问题：**做什么、不许做什么、怎样算做完**。代码与本文冲突时，代码是 bug。

---

## 1. 边界三问（成稿）

| 问题 | 答案 |
| --- | --- |
| 能不能接真实平台？ | **不能**。Adapter 只对 `fixtures/` 下的版本化快照工作；出现 OAuth、AppKey、真实 HTTP 调用即越界。 |
| 能不能自动退款？ | **不能**。模型只能提议；`execute_refund` 必须带 `approver_id`，且由策略层 `send_gate=human` 时强制拦截。 |
| 能不能回答"你们几天发货"？ | **能，但只许引用**：草稿里的政策句必须能追溯到某条 `qa_id` 命中或某次工具返回原文，否则视为幻觉，测试直接失败（AC18）。 |

---

## 2. 范围

### 2.1 做

| # | 范围 | 边界 |
| --- | --- | --- |
| S1 | **仅退款**：发起 → 审核 → 退款 → 关单，状态机全闭环（mock 执行） | 只有这一条链路走到 `CLOSED` |
| S2 | **退货退款**：发起 → 审核 → `AWAITING_BUYER_SHIP`，**到此截断** | 该状态无出边；回寄、质检、二次入库不做 |
| S3 | 意图识别四分类：退款 / 改地址 / 催发货 / 其他 | 非退款三类是**只读路径**：查询 + 草稿 + 转人工判定，无写操作、无状态机 |
| S4 | 策略层：金额 / 时效 / 类目 / 证据 / 情绪 / 异常六类信号 → `verdict` + `send_gate` | 规则确定性、可表驱动、版本化 |
| S5 | 检索层：200 条 QA，关键词基线 + 可选向量，`Retriever` 接口 | 向量是**可关闭的实验开关**，不是默认路径 |
| S6 | 评估：冻结 AC 集 + 回放 + 版本对比 + 基线封存 | 数字必须带 `provider` 标签 |

### 2.2 不做（非目标，出现即越界）

| 编号 | 非目标 | 越界信号 |
| --- | --- | --- |
| NG-1 | 自动退款 / 自动同意 | 无 `approver_id` 的 `execute_refund` |
| NG-2 | 退货退款全链路（回寄、质检、二次入库） | `AWAITING_BUYER_SHIP` 出现任何出边 |
| NG-3 | 多平台同时接入 | 一个 run 内出现两个 adapter 实例 |
| NG-4 | 真实电商 API / OAuth / 签名 | 代码里出现 `requests` 调外网、AppSecret |
| NG-5 | 多轮会话 / 记忆 | 工单按单轮处理；不支持跨工单引用 |
| NG-6 | ~~前端工程化~~（已按 ADR-011 破例） | 仍不允许：`web/` 里复制金额/时效/类目判断或状态迁移；API 出现第二套业务规则；业务 HTML 由 CLI 之外的地方生成 |
| NG-7 | 微调 / 训练 | 出现训练脚本、权重文件 |
| NG-8 | 外部中间件（Redis / MQ / K8s / 托管向量库） | 依赖列表出现这些包 |
| NG-9 | 图片 / OCR 取证 | 只接受"凭证已提供"这个布尔信号，不解析图片 |
| NG-10 | 多 Agent 编排 | 出现 planner/executor 双角色或框架 |

**多轮会话被砍掉是有意的**：工单是单轮的，引入上下文窗口只会多一个失败源。`thread` 字段保留但不驱动逻辑。

---

## 3. 领域模型（中立，不出现平台字段）

### 3.1 实体

| 实体 | 关键字段 | 约束 |
| --- | --- | --- |
| `Ticket` | `ticket_id, user_id, order_ref, intent, aftersales_type?, text, channel, created_at` | `order_ref` 是**中立引用**，不是平台单号 |
| `Order` | `order_ref, status, paid_cents, currency, created_at, signed_at?, items[], shipments[], raw_ref` | 金额一律整数分；时间一律 UTC ISO8601 |
| `OrderItem` | `sku, title, qty, unit_cents, category` | `category` 是阈值分档依据 |
| `Shipment` | `package_id, carrier, tracking_no, shipped_at?, delivered_at?, items[]` | **list，不是单值**；允许部分签收 |
| `AftersalesCase` | `case_id, ticket_id, order_ref, type, reason_code, amount_cents, status, events[]` | `events` 只追加，不修改 |
| `CaseEvent` | `event_id, case_id, from_status, to_status, actor, at, note` | `idempotency_key` 唯一域 = `(case_id, key)`，**不是全局唯一** |
| `Draft` | `draft_id, ticket_id, text, citations[], risk_flags[], verdict, send_gate` | `citations` 必须可解析到源 |
| `QaDoc` | `qa_id, question, answer, category, tags[], source, valid_from, valid_to?, status` | `status=approved` 才可被检索 |
| `PolicyVersion` | `version, params_json, effective_from` | 回放按 run 记录里的版本重算 |

### 3.2 枚举（封闭集）

```text
Intent          = refund | address_change | shipping_urge | other
AftersalesType  = refund_only | return_refund
OrderStatus     = CREATED | PAID | SHIPPED | DELIVERED | CLOSED | CANCELLED
CaseStatus      = INITIATED | REVIEWING | APPROVED | REFUNDING | REFUNDED | CLOSED
                | REJECTED | CANCELLED | AWAITING_BUYER_SHIP
Verdict         = approve | partial | reject | undecided
SendGate        = auto | human
Actor           = system | model | human:<id> | platform
```

### 3.3 金额与时间规约（三条硬规矩）

1. **金额只有一种表示**：整数分，字段名一律 `*_cents`。任何 `float` 金额出现在领域层即缺陷。
2. **单位换算只发生在 Adapter**：淘宝 `refund_fee` 是分，抖店 `refund_amount` 是元字符串 `"12.30"`；换算函数只有 `adapters/normalize.py` 一份。
3. **时间只有 UTC**：`signed_at=None` 就是 `None`，不许补 `0` / `""` / `now()`。售后期按 `signed_at + window_days*24h` 判定，自然日口径写在策略参数里。

## 4. 平台适配层

### 4.1 接口

```python
class PlatformAdapter(Protocol):
    platform: str
    def fetch_order(self, order_ref: str) -> Order: ...
    def fetch_shipments(self, order_ref: str) -> list[Shipment]: ...
    def fetch_cases(self, order_ref: str) -> list[AftersalesCase]: ...
    def map_status(self, raw: str) -> OrderStatus: ...
    def execute_refund(self, case_id: str, amount_cents: int, approver_id: str) -> str: ...
```

### 4.2 归一化义务（7 条，缺一条即有 AC 红）

| # | 义务 | 反例 |
| --- | --- | --- |
| N1 | 金额换分为整数，四舍五入只在最后一次 | `float("12.30")*100 = 1229.9999` |
| N2 | 状态映射穷举，未知值 → `UNKNOWN` 语义 + `platform_anomaly=True` | 猜成 `DELIVERED` |
| N3 | 包裹返回 list，允许 1→N，允许部分签收 | 假定一单一个运单 |
| N4 | 缺失即 `None`，不补默认值 | `signed_at=""` |
| N5 | 重复/乱序事件按 `idempotency_key` 去重，按 `at` 排序 | 同事件入库两次 |
| N6 | 保留原始载荷到 `raw_ref`（不透明字符串），领域层禁止读取 | 策略层写 `order["refund_fee"]` |
| N7 | 时区统一 UTC；平台本地时间在 Adapter 内转换 | 用 `datetime.now()` 补时区 |

### 4.3 脏数据 fixture 清单（故意脏，版本化）

| fixture | 脏在哪 | 用途 |
| --- | --- | --- |
| `tb_1001_unship_cents` | 金额是分；未发货 | AC06 全闭环 |
| `dy_2001_delivered_yuan` | 金额是元字符串；已签收 | AC01 单位归一 |
| `tb_1002_multi_pkg` | 一单两包裹，B 未签收 | AC02 多包裹 |
| `dy_2002_missing_state` | `signed_at=null`，`status=""` | AC03 缺失不猜 |
| `tb_1003_over_window` | 签收 9 天 | AC08 超期 |
| `tb_1004_partial` | 少件，申请部分退 | AC09 部分退款 |
| `dy_2003_dup_events` | 同一退款事件两条 | AC05 幂等 |
| `tb_1005_threat` | 含"12315 / 曝光" | AC14 优先级 |
| `tb_1006_digital` | 类目 `digital`（自动阈值 0） | AC13 类目排除 |
| `dy_2004_return` | 退货退款已审核 | AC10 截断 |

fixture 是**快照文件**，带 `fixture_version` 与内容 hash；改动即视为换基线，必须重封（见 ACCEPTANCE §3）。

---

## 5. 状态机

### 5.1 仅退款（全闭环）

```text
INITIATED ──submit──► REVIEWING ──approve──► APPROVED ──execute──► REFUNDING ──callback──► REFUNDED ──close──► CLOSED
    │                     │
    │                     └──reject──► REJECTED ──close──► CLOSED
    └──cancel──► CANCELLED
```

| 迁移 | 触发者 | 前置条件 | 不可逆 |
| --- | --- | --- | --- |
| `INITIATED→REVIEWING` | model 提议 + system 落库 | 契约校验通过 | 否 |
| `REVIEWING→APPROVED` | `human:<id>` | `send_gate` 允许且金额 ≤ 实付 | 是 |
| `REVIEWING→REJECTED` | `human:<id>` | 结论文案已生成 | 是 |
| `APPROVED→REFUNDING` | `execute_refund` | 带 `approver_id` | 是 |
| `REFUNDING→REFUNDED` | platform 回调（mock） | `platform_refund_id` 非空 | 是 |
| `REFUNDED→CLOSED` | system | 通知草稿已生成 | 是 |

### 5.2 退货退款（截断）

```text
INITIATED ──submit──► REVIEWING ──approve──► AWAITING_BUYER_SHIP   [截断，无出边]
                          └──reject──► REJECTED ──close──► CLOSED
```

`AWAITING_BUYER_SHIP` 是**显式终止态**：`TRANSITIONS` 表里这一项是空集合，测试断言其不可达任何其他状态。后续人工在平台侧处理，系统只负责生成寄回指引草稿。

### 5.3 谁能推进状态

模型**只能提议**（返回 `ProposedAction`），落库前必须过三道门：契约校验 → 策略层 → 人工确认（`send_gate=human` 或迁移标 `irreversible`）。任何 `Actor=model` 直接写 `APPROVED` 的路径都应被 `DomainError` 拒绝。

---

## 6. 策略层

### 6.1 策略对象（不是常量）

```python
class RefundPolicy(BaseModel):
    version: str                     # "2026-11-09.1"
    auto_limit_cents: int = 5000     # ≤ 此值且无其他触发 → send_gate=auto
    human_floor_cents: int = 5000    # > 此值 → send_gate=human；不变量 human_floor ≥ auto_limit
    window_days: int = 7
    window_basis: Literal["signed_at", "created_at"] = "signed_at"
    per_category: dict[str, CategoryRule] = {}   # {auto_limit_cents, human_floor_cents, excluded}
    max_partial_ratio: float = 1.0   # 部分退款上限 = paid * ratio
```

不变量（启动时校验，违反即拒启动）：`human_floor ≥ auto_limit`；`window_days ≥ 0`；`max_partial_ratio ∈ (0, 1]`。
`auto_limit < human_floor` 时，中间区间是**灰带**：可自动起草，但 `send_gate=human`（AC12）。

### 6.2 判定（纯函数）

```python
def evaluate(signals: Signals, policy: RefundPolicy) -> PolicyDecision
# PolicyDecision = {verdict, approved_amount_cents|None, send_gate, reason_codes[], primary_reason, policy_version}
```

- **verdict** 只看业务事实：状态、窗口、类目、金额上限。
- **send_gate** 看风险：金额、灰带、缺凭证、平台异常、用户要人工、模型置信 < 0.6、威胁/监管词。
- 两者正交：`reject` 也可以 `send_gate=human`（拒绝文案同样是对外承诺）。

### 6.3 优先级（先命中先定 primary，全部命中都进 reason_codes）

| 序 | 触发 | reason_code | verdict | send_gate |
| --- | --- | --- | --- | --- |
| P0 | 意图不是退款（改地址 / 催发货 / 其他） | `R_NOT_A_REFUND` | undecided | human |
| P1 | 平台异常 / 关键字段缺失 | `R_PLATFORM_ANOMALY` | undecided | human |
| P2 | 订单状态不允许（未支付/已关闭/已全额退） | `R_ORDER_NOT_ELIGIBLE` | reject | human |
| P3 | 威胁 / 监管 / 媒体曝光 | `R_THREAT_OR_LEGAL` | undecided | human |
| P4 | 类目排除（`excluded=True`） | `R_CATEGORY_EXCLUDED` | reject | human |
| P5 | 超出售后期 | `R_OUT_OF_WINDOW` | reject | human |
| P5b | 金额 > 实付（凭空多退） | `R_AMOUNT_OVER_PAID` | reject | human |
| P6 | 金额 > human_floor | `R_AMOUNT_OVER_LIMIT` | approve | human |
| P7 | 灰带（auto < 金额 ≤ human_floor） | `R_POLICY_GRAY_BAND` | approve | human |
| P8 | 缺凭证（`evidence_provided=False`，**仅"仅退款"**；退货退款在寄回验收环节看，见 AC10） | `R_MISSING_EVIDENCE` | undecided | human |
| P9 | 部分退款超比例（只批到 `paid × max_partial_ratio`） | `R_PARTIAL_OVER_RATIO` | partial | human |
| P10 | 用户明确要求人工 | `R_HUMAN_REQUESTED` | undecided | human |
| P11 | 模型自报置信 < 0.6 | `R_MODEL_LOW_CONFIDENCE` | undecided | human |
| P12 | 模型自报 `needs_human=true` | `R_MODEL_NEEDS_HUMAN` | 保留原 verdict | human |
| — | 无命中 | `R_OK` | approve/partial | auto |

> P11/P12 只是**信号**，不是决定权。策略层永远可以覆写模型结论（ADR-007 沿用）。
> **verdict 与 send_gate 不可互相替代**：P8/P10/P11 命中时 verdict 必须是 `undecided`，
> 只把 `send_gate` 抬成 human 而保留 `approve`，等于"人工确认一下就照批"，属于缺陷（v1.4 修）。
> `R_AMOUNT_OVER_PAID` 与 `R_PARTIAL_OVER_RATIO` 一码一义：前者是"要多于实付"，后者是"比例超上限"。

### 6.4 只读意图

`address_change` / `shipping_urge` / `other` 不适用退款策略：不建售后单、不调打款、
不下 `approve|reject` 结论，一律 `verdict=undecided`、`send_gate=human`、`R_NOT_A_REFUND`。
`needs_human=true` 的含义是"模型自己要求人工"，它只能把 `auto` 降为 `human`，
不能反过来把 `human` 提成 `auto`，也不能替代人工确认去打款。

---

## 7. 检索层

### 7.1 契约

```python
class Retriever(Protocol):
    name: str
    def search(self, query: str, k: int = 5, filters: dict | None = None) -> list[Hit]: ...

# Hit = {qa_id, score, matched_terms|None, source}
```

实现：`KeywordRetriever`（FTS5 / BM25）、`VectorRetriever`（暴力余弦，embedding 存同库 BLOB）、`HybridRetriever`（RRF，k=60）。

### 7.2 为什么不用向量数据库

200 条 × 1024 维 ≈ 800 KB，全量暴力余弦在单机上微秒级。**pgvector 与 MySQL 的冲突根本不需要解决——因为一期不需要向量库**。embedding 存同库 BLOB，检索在进程内做。二期超过 1 万条再谈库，届时换 `VectorRetriever` 实现即可，接口不变。

> 这条同时否掉了"换 Postgres"和"上 Milvus"两个选项：都为一期不存在的规模付运维成本。

### 7.3 收益门槛（防止"上了向量"当成果）

- 基线 = `KeywordRetriever` 在 60 条标注查询上的 `Recall@5`。
- `HybridRetriever` 相对基线提升 **< 3pt** → 默认关闭向量路径，报告里写明"已实现未采用"。
- 离线阶段没有真 embedding 服务，`ScriptedEmbedder` 是字符 n-gram 哈希投影，**只能证明管线通，不能证明语义收益**。该结论必须在报告里标注 `provider=scripted`，不得对外声称"向量检索提升了召回"。

### 7.4 QA 集质量门（200 条先过关）

| 门 | 阈值 |
| --- | --- |
| `status=approved` 占比 | 100%（草稿态不参与检索） |
| 有 `category` + `source` | 100% |
| answer ≤ 200 字 | 100% |
| 60 条检索查询有标注 `qa_ids` | 100% |
| 回答含"保证/一定/立刻到账"等绝对承诺 | 0 条 |

## 7A. 意图规则层（离线先验，不入主链路）

> 编号写成 7A 而不是 8，是为了不动后面已有的 8/9/10 章节引用。

`app/intent/rules.py` 是**纯函数文本先验**：`classify(text) -> RuleResult(intent,
aftersales_type, confidence, cues, ambiguous)`。它存在的唯一目的是让"意图规则改没改好"
有数字可依，因此有三条硬边界：

| 边界 | 规则 |
| --- | --- |
| 不入主链路 | `app.core.pipeline` 不得 import `app.intent`；规则也不得 import pipeline。线上判定仍以模型输出为准（P0 / §6.4） |
| 不下结论 | 只输出意图标签与子类型，不产出 verdict、金额、send_gate；不碰状态机 |
| 调参隔离 | 只允许在 `data/eval/intent_dev.jsonl` 上调参；`data/eval/queries_60.jsonl`（检索评测集）与 `fixtures/` 工单文本禁止复用 |

数据集与门禁：

- `data/eval/intent_dev.jsonl`（开发集，≥80 条，四类各 ≥14，refund 两类各 ≥10，hard ≥15）
  按 `THRESHOLDS` 门禁：accuracy ≥ 0.85、macroF1 ≥ 0.78、refund recall ≥ 0.88、
  refund_only recall ≥ 0.80、return_refund recall ≥ 0.75。
- `data/eval/intent_holdout.jsonl` 与 `data/eval/intent_holdout2.jsonl` 是留出集，只做
  一次性测量，下限 `HOLDOUT_FLOOR`（accuracy ≥ 0.80、macroF1 ≥ 0.75）。
  第一留出集的错误曾被用于补同义词，故它**已污染**，泛化数字只认 holdout2。
- 开发集满分**不构成**效果声明：报告与 README 必须同时给出留出集数字。
- 三份数据的文本必须互不重复（测试强制），避免"背题"。

---

## 8. 模型层

### 8.1 配置五元组（换模型只改配置）

```python
class LLMConfig(BaseModel):
    provider: Literal["scripted", "openai_compat"]
    model: str
    prompt_version: str      # = sha256(模板正文)[:8]，由代码计算，不许手填
    token_budget: int = 6000 # 单 run 上限
    timeout_ms: int = 30000
```

`prompt_version` 由模板内容哈希得出：改了提示词却忘改版本号这件事，在结构上不可能发生。

### 8.2 模型输出契约

```json
{
  "intent": "refund",
  "aftersales_type": "refund_only",
  "slots": {"order_ref": "...", "reason": "...", "evidence_provided": true},
  "proposed_action": {"kind": "submit_case", "amount_cents": 5000},
  "draft": "...",
  "citations": [{"qa_id": "QA0123", "quote": "..."}],
  "confidence": 0.82,
  "needs_human": false
}
```

容错解析沿用 v1 的 `parse_final_answer` 形状：剥围栏 → 取首个 JSON 对象 → 校验；失败重试 1 次，再失败 → `E_INVALID_OUTPUT` + `degraded`。

### 8.3 `scripted` 的语义

`scripted` 不是"假模型"，是**确定性回放器**：按 `(prompt_version, case_id)` 查表返回预置输出，未命中则返回显式 `E_SCRIPT_MISS`。它必须真实产生 token 计数与 `stop_reason`，否则 AC20–AC23 无法验证。

---

## 9. 对外契约（Pydantic 形状）

```python
class TicketIn(BaseModel):        # 入口
    ticket_id: str; user_id: str; text: str
    order_ref: str | None = None; channel: str = "app"
    created_at: datetime

class TicketOut(BaseModel):       # 出口
    run_id: str; ticket_id: str
    intent: Intent; aftersales_type: AftersalesType | None
    case: CaseView | None          # 状态机快照
    draft: DraftView               # 文案 + citations + risk_flags
    verdict: Verdict; send_gate: SendGate
    reason_codes: list[str]
    stop_reason: StopReason        # finalized|budget_exhausted|timeout|invalid_output|rejected|degraded
    usage: Usage; latency_ms: int
    policy_version: str; prompt_version: str; model: str
```

`TicketOut` 是全系统唯一出口；CLI 与 HTTP 都返回它，字段不许各写一套。

### 9.1 调用方身份（HTTP 写接口）

- 配置：`.env` 的 `AFTERSALE_OPERATORS="alice:tok-alice,bob:tok-bob"`（`id:token` 对，逗号分隔）。
  未配置时写接口一律 **503**，不允许"没配就匿名放行"。
- 请求头：`X-Operator-Id` + `X-Operator-Token`；缺失或不匹配 **401**（常量时间比较，不回显 token）。
- **审批人只能是自己**：请求体的 `confirm` 若存在，必须等于 `human:<登录操作人>`，否则 **403**；
  服务端最终写入记录的 `confirm` 由身份推导，不信任请求体自称。
- 读接口（`/api/meta`、`/api/fixtures`、`/api/runs`、静态页）不要求身份：演示与排障优先。
- CLI 保持本地可信：仍是 `--confirm human:<id>`；执行者可自行核对 id，无网络鉴权。

---

## 10. 错误码（封闭集，出现未登记码即测试失败）

| code | 含义 | retryable |
| --- | --- | --- |
| `E_INPUT_INVALID` | 入参不合契约 | 否 |
| `E_ORDER_NOT_FOUND` | fixture/仓储无此单 | 否 |
| `E_PLATFORM_ANOMALY` | 状态/字段无法归一 | 否 |
| `E_STATE_ILLEGAL` | 非法状态迁移 | 否 |
| `E_CONFIRM_REQUIRED` | 缺 `approver_id` | 否 |
| `E_POLICY_BLOCKED` | 策略拒发 | 否 |
| `E_BUDGET_EXHAUSTED` | token 超预算 | 否 |
| `E_TIMEOUT` | 上游超时 | 是 |
| `E_INVALID_OUTPUT` | 模型输出不可解析 | 是（1 次） |
| `E_RETRIEVAL_EMPTY` | 检索无命中 | 否 |
| `E_DB_WRITE` | 落库失败（不吞异常） | 是 |
| `E_IDEMPOTENT_REPLAY` | 重复执行且键冲突 | 否 |
| `E_SCRIPT_MISS` | scripted 无该用例 | 否 |

---

## 11. 可观测

一次 run 必须能回答四个问题，缺一条即无法归因：

1. 用了什么（`tool_calls[]`：name, args_digest, ok, latency）
2. 上下文里有什么（`prompt_version` + 检索命中的 `qa_id`）
3. 模型原样输出是什么（`raw_output`，脱敏后）
4. 谁做的决定（`policy_version` + `reason_codes` + `actor`）

落库：`ticket / run / case + case_event / draft / qa / policy_version` 六张逻辑表。默认 SQLite（单文件、可封存、零运维）；MySQL 作为第二个 `Repository` 实现，**换库只换实现**。

---

## 12. ADR

| 编号 | 决策 | 否掉的方案 | 理由 | 代价 |
| --- | --- | --- | --- | --- |
| ADR-001 | 仅退款闭环、退货退款截断 | 两类都做全 | 一期两类都做全，大概率两类都不完整 | 退货退款演示停在寄回 |
| ADR-002 | 中立领域模型 + Adapter | 按平台字段建表 | 第二平台接入不需要数据迁移 | 多一层映射代码 |
| ADR-003 | 阈值策略对象 + 版本化 | 常量 / 环境变量 | 类目分档不改代码；回放可复现 | 策略文件要维护 |
| ADR-004 | 脏 fixture | 干净 mock | 干净 mock 会养出"一单一运单"这类错误假设 | 调试成本上升 |
| ADR-005 | 五元组 + 提示词哈希 | 只留 provider | 能归因"模型换了还是提示词改了" | 配置文件字段变多 |
| ADR-006 | 无向量库，暴力检索 | pgvector / Milvus | 200 条规模不需要，冲突自然消失 | 上万条时要换实现 |
| ADR-007 | 策略层覆写模型 | 信任模型 `needs_human` | 合规要求不能由模型不确定性决定 | 阈值需人工维护 |
| ADR-008 | 不做队列 | Redis Stream | 一期无真实并发，只增加排障面 | 批量任务需同步跑 |
| ADR-009 | 工单单轮 | 多轮上下文/摘要折叠 | 少一个失败源 | 复杂追问不做 |
| ADR-010 | SQLite 默认 | 直接上 MySQL | 离线可复现、可整库封存 | 需维护第二个实现 |
| ADR-011 | 破例 NG-6：新增 `web/` 控制台 + 只读/跑单 HTTP API | 继续只用 CLI；或先做静态 HTML 报告 | 演示与排障需要可视化证据链；API 只编排 `pipeline.run`，CLI 仍可复现同一结果 | 多一套前端依赖与构建产物；API 需随 CLI 同步 |
| ADR-012 | 模型走配置（`AFTERSALE_LLM_PROVIDER/BASE_URL/MODEL/API_KEY`），提供 `OpenAICompatProvider`；测试强制 scripted | 把真实模型写进代码默认值；或在测试里也调真实模型 | 换模型只改 `.env` 不改代码；真实模型非确定性，会破坏 AC16/AC20，故测试用 autouse fixture 锁死 scripted | 多一层配置解析与脱敏；真实模型回放的 `drift` 属预期 |
| ADR-013 | 写接口要求已验证操作人（`AFTERSALE_OPERATORS` + `X-Operator-*`），`confirm` 必须等于登录身份；`auto` 缺配置直接报错，不再静默回退 scripted | 继续允许匿名 `POST /api/runs`；或让 `auto` 缺 key 时念台词 | 审批与打款必须能归因到"谁确认的"；静默回退会让线上"以为在调模型、其实在回放"，事故不可归因 | 控制台多一步登录；本地演示需在 `.env` 配一个 `id:token` |
| ADR-014 | 意图规则只做**离线先验**，不进主链路：`app/intent/rules.py` 纯函数 + 独立开发集/留出集评测 | 把规则接进 pipeline 当兜底；或用规则替代模型判意图 | 一期卖点是"模型输出 + 策略/闸门兜底"，规则一旦进主链路就出现第二套判定，事故无法归因；且规则可离线、可复现，正好用来给出"意图这步有多难"的诚实数字 | 规则与线上行为可能不一致；开发集满分需靠留出集校正，否则会误导 |

---

## 13. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1 | 2026-11-09 | 首版。取代"不修改已确认 schemas"这条无处落地的约束。 |
| v1.1 | 2026-11-10 | 补 `R_NOT_A_REFUND`（只读意图）与 `R_MODEL_NEEDS_HUMAN`（模型自请人工只能收紧闸门）；P0–P10 顺延为 P0–P12，新增 §6.4；`run_id` 计入模型配置，避免超时跑与正常跑同号。 |
| v1.2 | 2026-11-12 | 破例 NG-6：新增 `app/api/server.py`（薄封装 `pipeline.run` 的 HTTP API）与 `web/` React 控制台（ADR-011）；策略、状态机、闸门仍只有一份实现。 |
| v1.3 | 2026-11-12 | 接入 OpenAI 兼容真实模型（ADR-012）：`app/llm/openai_compat.py` + `settings.resolve()` + `factory.make_provider()`；CLI `--provider`、API `provider/max_tokens` 字段与记录里的 `llm` 五元组；测试 autouse 锁 scripted；`app.eval.seal --provider` 另存新基线。 |
| v1.4 | 2026-11-18 | 评审 M1–M12 修正：P8/P10/P11 命中必须 `undecided`（不能只抬 send_gate）；新增 `R_AMOUNT_OVER_PAID`（P5b）与 P9 只批到比例上限；P8 限定"仅退款"（与 AC10 对齐）；`needs_human` 进 PRIORITY（P12）；`scripted` 未命中抛 `E_SCRIPT_MISS`；模型超时前置到请求；平台脏值统一 `E_PLATFORM_ANOMALY`；trace 脱敏接入生产路径。另：写接口要求操作人身份（§9.1、ADR-013），`auto` 缺配置报错。 |
| v1.5 | 2026-11-19 | 新增 §7A 意图规则层（ADR-014）：`app/intent/rules.py` 离线文本先验 + `data/eval/intent_dev.jsonl`（94 条）与两份留出集；`python -m app.eval.intent` 出门禁与 `reports/intent_dev_v0.json`。规则不接主链路，`pipeline` 与 `app.intent` 互不 import（测试断言）。实测 naive 0.596 → 规则 holdout2 0.967；开发集 1.000 记作过拟合。 |
