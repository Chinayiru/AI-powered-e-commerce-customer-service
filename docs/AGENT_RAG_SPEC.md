# Agent / RAG 规范

| 项 | 内容 |
| --- | --- |
| 依据 | `docs/BOUNDARY_v1.md` v1.4.0 §6、§8；`docs/api/openapi.yaml` v1.5.0 |
| 范围 | 意图识别、槽位抽取、知识检索、草稿生成、转人工判定 |
| 不包含 | 模型选型细节、训练、微调（一期不做） |
| 诚实声明 | 本文阈值多为**待标定**目标，未在真实模型上测过；`scripted` 模式下"置信度"是脚本常量，不具统计意义 |

---

## 1. 意图分类

### 1.1 运行时 6 类（封闭）

| 意图 | 含义 | 例子 |
| --- | --- | --- |
| `REFUND_ELIGIBILITY` | 问"能不能退/该不该退" | "我这个还能退吗"、"拆封了还能退不" |
| `REFUND_REQUEST` | 明确要退款 | "帮我退款"、"我不想要了" |
| `LOGISTICS` | 查物流/催发货 | "怎么还没到"、"发到哪了" |
| `POLICY` | 问规则本身（运费、时效、流程） | "退货运费谁出"、"七天从哪天算" |
| `OTHER` | 与售后无关 | "你们老板是谁" |
| `HANDOFF` | 明确要人工 | "转人工"、"找个人跟我说" |

> 运行时意图统一为 `REFUND_ELIGIBILITY`；改名要同步 openapi 枚举、回归集标注与断言。

### 1.2 判定顺序（先安全，后意图）

```
1) 安全闸：投诉/威胁/律师/监管/人身安全关键词 → HANDOFF(`OUT_OF_SCOPE`)（不再判意图）
2) HANDOFF：客户明确要人工 → `USER_REQUESTED`（投诉关键词本身不等于要人工）
3) REFUND_REQUEST：出现明确处置动词（退掉/帮我退/申请退款）
4) LOGISTICS / POLICY / REFUND_ELIGIBILITY / OTHER
```

**条件式诉求**（"能退的话就退了吧"）按 `REFUND_REQUEST` 处理，并在 `slots.conditional=true`；它仍必须经过确认，不允许自动执行。

理由：客户说"退不了就转人工"时，必须按"要退款"处理，不能只回一句"已转人工"。

**边界**：`REFUND_ELIGIBILITY` 与 `REFUND_REQUEST` 的差别是"问"还是"要"，靠回归集盯住。

### 1.3 与评测 5 类的映射

| 评测类（`qa-200` 标注） | 运行时意图 |
| --- | --- |
| 退款资格 | `REFUND_ELIGIBILITY` |
| 退款请求 | `REFUND_REQUEST` |
| 物流 | `LOGISTICS` |
| 政策 | `POLICY` |
| 无关/越界 | `OTHER` |

`HANDOFF` **不计入意图准确率的分母**，单独报"人工请求识别率"与"安全闸触发数"。否则"转人工"会同时被算对和算错。

---

## 2. 槽位

| 槽位 | 类型 | 缺失时 |
| --- | --- | --- |
| `orderNo` | string | 追问一次 → `WAITING_INPUT`；**连续 2 轮**仍缺 → `INSUFFICIENT_INFO` 转人工 |
| `issueType` | enum（退款/物流/咨询） | 由意图推导 |
| `desiredOutcome` | string | 可空 |
| `conditional` | boolean | 条件式诉求标记，默认 false |

槽位抽取只做**显式**匹配：文本里没有订单号就不许猜。历史消息里出现过的订单号可复用，但必须在上下文 **6 轮（≤12 条）**以内；超出部分由 Java 压成 `summary`（≤300 字）一起传入，Python 不自行截断或摘要。

---

## 3. 置信度

| 来源 | 计算 |
| --- | --- |
| 真实模型 | 模型自报（0–1）或多次采样一致率；**必须记录来源** |
| `scripted` | 命中的脚本常量（如 0.42 / 0.92） |

- 运行时阈值 `intent.confidence_threshold = 0.60`（配置项，可改）。
- `< 0.60` → `needHumanReview=true`，坐席看到黄色标记并可覆盖。
- **`0.85` 不是运行时阈值**：它是 `M-Q` 阶段意图准确率的 go/no-go 目标（QC02），两回事，不要混用同一个配置键。
- 置信度不当真概率：只用于排序"先看哪条"，不做自动化决策；**政策类判断 Python 不参与**——`policyCheck` 由 Java 规则引擎计算，既不进 `ask` 请求也不进响应。

---

## 4. 回复类型

| 类型 | 定义 | 处理 |
| --- | --- | --- |
| `INFORMATIONAL` | 陈述事实/规则，不产生业务动作 | 咨询单可直接回复 |
| `DECISIONAL` | **作出处置决定或承诺**（退款/赔付/改址/时效承诺/既成事实） | 一律转交，不允许自动回复 |

判定线索（命中即 `DECISIONAL`）：

- 承诺动作或结果："帮您退"、"给您补"、"马上处理"、"今天一定发出"
- 承诺时效："3 天内退到"、"送达"
- `suggestedAction.action != NONE`
- 草稿里出现"已为您/会为您/将为您 + 处置动词"

（Python **不接收** `policyCheck`，所以不能用 `needHumanConfirm` 作为线索；政策后果由 Java 在收到建议后补判。）

**不算** `DECISIONAL`（常见误判）：

- 只是**陈述**订单事实与金额："订单实付 ¥58.00"、"金额是 58 元"
- 只是引用政策条款："七天无理由，自签收次日起算"

即：判"是否在替客户做决定"，不判"句子里有没有数字"。金额只作为复核线索，不是判定依据。

---

## 5. 知识库（RAG）

### 5.1 语料

| 文档 | 内容 | 粒度 |
| --- | --- | --- |
| 退款政策 | 七天无理由、例外商品、时效 | 每条规则一个 chunk |
| 退货运费 | 谁担、什么情况免 | 同上 |
| 物流时效 | 发货/到达承诺 | 同上 |
| 售后流程 | 步骤、所需材料 | 同上 |

chunk 规则：300–500 字，必须带 `docId`、`clauseId`、`version`、`effectiveFrom`；一条 chunk 只讲一条规则，禁止跨规则合并。

### 5.2 检索

- top-k = 5，相似度阈值 0.35（**待标定**）。
- 检索不到 → `NO_EVIDENCE` → 转人工，不允许"凭印象回答"。
- 引用格式：`[docId#clauseId]`，正文中每个结论都要对得上一条引用。

### 5.3 生成约束（硬性）

1. 金额只能来自工具返回值，不得由模型计算或编造。
2. 不得承诺赔付、不得保证时效（`赔付/赔偿/补偿/保证/一定/百分百` 为禁用词）。
3. 不得声称"已退款/已改地址/已处理"。
4. 草稿 ≤ 200 字，客户可读，不含内部码。
5. 引用必须来自本次检索结果。

---

## 6. 转人工触发矩阵

| 条件 | 原因 | 谁判定 |
| --- | --- | --- |
| 安全闸命中（投诉/威胁/监管/人身安全） | `OUT_OF_SCOPE` | Python |
| 客户明确要求人工 | `USER_REQUESTED` | Python |
| `confidence < 0.60` | `LOW_CONFIDENCE` | Python |
| 检索无结果 | `NO_EVIDENCE` | Python |
| `policyCheck.allowed == false` | `POLICY_BLOCKED` | Java |
| 工具可重试失败 ≥ 2 次尝试（**含 AI 服务故障**） | `TOOL_FAILED` | Python |
| 一单多包裹且状态冲突 | `AMBIGUOUS_ORDER` | Python |
| 订单归属不符 | `ORDER_NOT_FOUND` | Java |
| 超出范围（换货/价保/投诉） | `OUT_OF_SCOPE` | Python |
| 连续 2 轮缺槽位 | `INSUFFICIENT_INFO` | Java |

**原因保持粗粒度**（9 个够了）：不把"模型超时/检索超时/HTTP 5xx"拆成新枚举——这些由 `AGENT_UNAVAILABLE`、`tool_call.error_code` 与组件日志区分。枚举越细，越容易在实现里各写一套。

---

## 7. 输出契约

`POST /internal/agent/ask`（Python 8000；Java 经内网转发，路径同名）的响应必须严格符合 `AskResponse`：

```json
{
  "intent": "REFUND_REQUEST",
  "slots": { "orderNo": "O1001", "missing": [], "conditional": false },
  "confidence": 0.92,
  "replyType": "DECISIONAL",
  "needHumanReview": true,
  "transferReason": null,
  "suggestedAction": { "action": "REFUND", "amountCents": 5800, "needHumanConfirm": true },
  "replyDraft": "查到了：订单 O1001，待发货，金额 ¥58.00……",
  "citations": [{ "docId": "refund-policy", "title": "七天无理由", "clauseId": "3.2", "policyVersion": "2026-11" }],
  "degraded": false,
  "model": { "provider": "scripted", "promptVersion": "p1.0.0" }
}
```

校验规则（Java 侧 fail-fast）：**未知字段拒绝**（`additionalProperties: false`）、缺失必填拒绝、枚举越界拒绝、`transferReason` 允许 `null`。

---

## 8. 版本管理

| 对象 | 规则 |
| --- | --- |
| `promptVersion` | 语义化 `p<major>.<minor>.<patch>`；改提示词必须升版本并跑回归集 |
| 知识库 | `policyVersion` 随语料发布递增，草稿引用中必须回填 |
| 契约 | `openapi.yaml` 与 BOUNDARY **版本独立演进**（各自语义化递增，不要求号段相同）；两者的对应关系由 `docs/contract-snapshot.json` 记录，快照同时登记两份文件的 SHA-256 |

---

## 9. 评测（M-Q）

### 9.1 数据集

| 集合 | 条数 | 用途 | 使用次数 |
| --- | --- | --- | --- |
| 开发集 `dev` | 30 | 调参、看混矩阵 | 不限 |
| 验收集 `holdout` | 50 | 唯一 go/no-go 判定 | **2 次**（报两次差值） |
| 回归集 `regression` | 120 | 防退化，不作 go/no-go | 每次改动 |

合起来 200 条。**评测语料与检索语料分离**：`qa-200` 是人工编写的问答样本，`policies-v1` 是政策原文，二者不得重叠（同题泄漏会让 QC04 的 Recall@3 虚高）。

### 9.2 指标

| 指标 | 定义 | 性质 |
| --- | --- | --- |
| 意图准确率 | 5 类混淆矩阵对角线；`HANDOFF` 单列 | **go/no-go ≥ 0.85** |
| 幻觉率 | 无依据事实断言 / 总断言 | **go/no-go ≤ 5%** |
| 草稿可用率 | 双人独立评分"可直接发"或"小改可发" | **go/no-go ≥ 0.80** |
| 槽位 F1（`orderNo`） | 精确率/召回 | 开发目标 ≥ 0.90，报告项 |
| 引用精确率 | 引用条款确实支持结论 | 开发目标 ≥ 0.85，报告项 |
| 转人工精确率 | 转交的单子确实不该自动处理 | ≥ 0.90，报告项 |
| 越权泄露 | 客户视图出现内部字段次数 | **必须 0**（缺陷，不是指标） |
| 成本 / 延迟 | 每例 token、P50/P95 | 报告项，设线 |

三个 go/no-go 指标**只来自边界书**，其余一律标"报告项/开发目标"，不得静默升格为验收门槛。双人评分需报 Cohen's κ。

---

## 10. 降级

| 故障 | 行为 |
| --- | --- |
| Python 不可用 | Java 直接 `TRANSFERRED(TOOL_FAILED)`（该原因**包含 AI 服务故障**），客户看到"已转人工"；审计以 `AGENT_UNAVAILABLE` 与组件字段 `agent` 区分于工具失败 |
| 模型超时（>8s） | **不重试**；`AGENT_UNAVAILABLE`，转人工（原因码同为 `TOOL_FAILED`，不新增第十个枚举） |
| 检索服务不可用 | `NO_EVIDENCE` → 转人工 |
| 工具不可用 | 工具层最多 2 次尝试后转人工，不编造事实 |

注意：**模型超时不重试，工具超时可重试 1 次**。两条策略分开，避免"AI 挂了还在等第二次超时"。

降级路径必须比正常路径**更保守**：宁可多转人工，不可多说一句。
