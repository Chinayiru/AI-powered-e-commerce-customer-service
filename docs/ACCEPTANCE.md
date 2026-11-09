# 验收与基线 · v1

> 配套 [CONTRACT.md](CONTRACT.md)。本文只写"怎么证明做完了"，不重复设计理由。
> 所有 AC 必须可被一条命令复现，并留下 `run_id`。没有 `run_id` 的"通过"不算证据。

---

## 1. AC 表（26 条）

约定：`F`=功能、`C`=契约、`S`=安全/合规、`E`=评估。

| 编号 | 类 | 场景 | 命令 | 观察字段 | 期望值 |
| --- | --- | --- | --- | --- | --- |
| AC01 | C | 淘宝 `refund_fee` 是分、抖店 `refund_amount` 是元字符串 `"12.30"` | `pytest -k ac01` | `case.amount_cents` | 两者都归一为 `1230`；`float` 不进入领域层 |
| AC02 | C | 一单两包裹，B 未签收（`tb_1002_multi_pkg`） | `pytest -k ac02` | `order.shipments` / 售后期判定 | 长度 2；签收判定取**最晚** `delivered_at`；B 为空则不判签收 |
| AC03 | C | `signed_at=null` 且 `status=""`（`dy_2002_missing_state`） | `pytest -k ac03` | `send_gate` / `reason_codes` | `human` + `R_PLATFORM_ANOMALY`；不补默认值、不猜状态 |
| AC04 | C | 领域/策略层出现平台原始字段名 | `pytest -k ac04`（AST/文本扫描） | 命中文件列表 | 空；允许清单只有 `app/adapters/` |
| AC05 | C | 同一退款事件重复推送两次（`dy_2003_dup_events`） | `pytest -k ac05` | `case.events` 条数 | 1；`idempotency_key` 唯一域是 `(case_id,key)`，非全局 |
| AC06 | F | 未发货、50 元内仅退款（`tb_1001_unship_cents`） | `python -m app.cli run --fixture tb_1001 --confirm human:demo1` | `stop_reason` / `case.status` / `events` 迁移序列 | `finalized` / `CLOSED` / `INITIATED→REVIEWING→APPROVED→REFUNDING→REFUNDED→CLOSED` |
| AC07 | F | 已签收 7 天内、120 元（`dy_2001_delivered_yuan`） | 同上（不带 `--confirm`） | `verdict` / `send_gate` / `case.status` | `approve` / `human` / `REVIEWING`（停在待确认）；`R_AMOUNT_OVER_LIMIT` |
| AC08 | F | 签收 9 天（`tb_1003_over_window`） | `python -m app.cli run --fixture tb_1003` | `verdict` / `draft.text` | `reject`；草稿含拒绝口径，**不含**"退款将在/已"字样 |
| AC09 | F | 少件部分退款（`tb_1004_partial`） | `--fixture tb_1004` | `approved_amount_cents` | `partial` 且 `≤ paid_cents`；超实付直接 `E_STATE_ILLEGAL` |
| AC10 | F | 退货退款审核通过（`dy_2004_return`） | `--fixture dy_2004 --confirm human:demo1` | `case.status` / `TRANSITIONS["AWAITING_BUYER_SHIP"]` | `AWAITING_BUYER_SHIP` 且出边集合为 `set()` |
| AC11 | F | 对 `REFUNDED` 再发 `approve` | `pytest -k ac11` | 异常类型 / `case.status` | `DomainError(E_STATE_ILLEGAL)`；状态不变、无新增 event |
| AC12 | F | 灰带：`auto=3000, human=5000, amount=4000` | `pytest -k ac12` | `verdict` / `send_gate` / primary | `approve` / `human` / `R_POLICY_GRAY_BAND` |
| AC13 | F | 类目 `digital`，`excluded=True`（`tb_1006_digital`） | `--fixture tb_1006` | `verdict` / primary | `reject` / `R_CATEGORY_EXCLUDED` |
| AC14 | S | 含"12315 / 曝光 / 法院"（`tb_1005_threat`） | `--fixture tb_1005` | `send_gate` / primary / `reason_codes` | `human`；primary=`R_THREAT_OR_LEGAL`；金额原因同时在 `reason_codes` 里 |
| AC15 | S | 用户说"转人工" | `pytest -k ac15` | `send_gate` / `draft.text` | `human`；草稿不得出现劝阻话术（"我可以帮你处理，不用转人工"） |
| AC16 | C | 改动 `policy_version` 后回放旧 run | `python -m app.cli replay --run-id <old>` | 重算用的版本 | 用 run 里记录的旧版本；输出与本条 AC 记录一致 |
| AC17 | E | 60 条标注查询跑 `KeywordRetriever` | `python -m app.eval.retrieval --retriever keyword` | `recall@5` | ≥ 报告登记值（v0：0.950）；无标注查询数 = 0 |
| AC18 | E | 草稿引用了 KB 里不存在的政策句 | `pytest -k ac18`（引用可追溯校验） | 未命中的 `quote` | 该引用被丢弃，`draft.risk_flags` 出现 `CITATION_UNRESOLVED` / `CITATION_QUOTE_MISMATCH`；不得原样放行 |
| AC19 | E | `hybrid` vs `keyword` 的 `recall@5` | `python -m app.eval.retrieval --compare` | 差值 | 差值 < 3pt 时默认关闭向量（v0：delta=0.000，`vector_enabled=false`）；报告注明 `provider=scripted` 不代表语义收益 |
| AC20 | E | 同输入连跑两次 `provider=scripted` | `python -m app.cli run ...` ×2 | 除 `run_id`/时间戳外的全字段 | 完全一致（含 `prompt_version`、`policy_version`、`draft.text`） |
| AC21 | F | `token_budget` 调到极低（如 200） | `pytest -k ac21` | `stop_reason` / `draft` | `budget_exhausted`；不输出半截草稿（`draft.text` 为空串） |
| AC22 | F | 上游 sleep > `timeout_ms`（如 2s vs 500ms） | `pytest -k ac22` | `stop_reason` / `usage.estimated` | `timeout` / `true` |
| AC23 | F | 模型先返回坏 JSON、再返回合法 JSON | `pytest -k ac23` | 重试次数 / `stop_reason` | 重试 1 次后 `finalized`；两次都坏 → `invalid_output` + `degraded` |
| AC24 | E | 全绿后封存基线 | `python -m app.eval.seal` | manifest 内容 | 含 git sha、fixture hash、`policy_version`、`prompt_version`、时间；任一 AC 转红即阻断 |
| AC25 | S | 日志/审计含手机号、详细地址 | `pytest -k ac25` | 审计行 | 手机号 `138****8000`、地址只留到区；明文仅存加密字段 |
| AC26 | C | 任意失败路径 | `pytest -k ac26` | `error.code` | 全部落在 CONTRACT §10 的 13 个码内；出现新码即失败 |

### 1.1 覆盖矩阵自检

| 维度 | AC |
| --- | --- |
| 契约/归一化 | 01 02 03 04 05 16 26 |
| 状态机 | 06 07 08 09 10 11 |
| 策略层 | 07 12 13 14 15 |
| 检索 | 17 18 19 |
| 循环/预算 | 21 22 23 |
| 安全 | 14 15 25 |
| 基线/证据 | 20 24 |

> 四类意图里 `address_change` / `shipping_urge` / `other` 是只读路径，只由 AC15（人工话术）与 AC20（确定性）覆盖；它们的工具集与草稿要素在 `tests/contract/test_readonly_paths.py` 里单独断言，不占 AC 编号。

---

## 2. 断言纪律

1. **一条 AC 一个失败原因**：断言优先 `primary_reason` 与 `case.status`，不要"草稿里包含某些字"这种模糊断言。
2. **双向比对**：工具集合与参数按"期望 ⊆ 实调 且 实调 ⊆ 期望"比对，不是单向包含。
3. **禁止测试内改数据**：AC 只读 fixture；需要新场景就新增 fixture（并重封基线）。
4. **时间冻结**：所有时间断言注入 `now` 参数，不用 `datetime.now()`；否则跨零点会随机红。
5. **金额只比整数**：`assert case.amount_cents == 1230`，不写 `== 12.30`。

---

## 3. 可回归基线（从零长出来）

历史成绩（v1 的 24 条、drafts_50、2026-11-04 的报告）**不作为本期基线**：意图体系、状态机、影子数据都换了，混用等于伪造提升。

### 3.1 v0 基线怎么封

1. AC01–AC26 全绿（`pytest tests/acceptance -q` 退出码 0）。
2. `python -m app.eval.seal` 生成 `reports/baseline_v0.json`：

```json
{
  "baseline": "v0",
  "created_at": "2026-11-09T...+08:00",
  "git_sha": "...",
  "fixture_manifest_sha256": "...",
  "policy_version": "2026-11-09.1",
  "prompt_version": "<sha8>",
  "model": {"provider": "scripted", "model": "scripted-v1"},
  "ac_results": {"AC01": "pass", "...": "pass"},
  "metrics": {"intent_acc": null, "tool_acc": null, "p95_ms": null, "cost_cny": null}
}
```

3. **封存**：`reports/baseline_v0.json` 与其内容 hash 一起提交；此后任何 AC 由绿转红即阻断。
4. `null` 就是 `null`——没测量的指标不许写 0，也不许写"预计"。

### 3.2 回归判定

| 情形 | 判定 |
| --- | --- |
| 任一 AC 红 | 阻断，必须修或走 ADR 改契约（改契约 = 新基线） |
| AC 全绿但指标下降 | 不阻断，但报告必须单列 diff 与归因 |
| 新增 fixture | 必须重封基线，旧 manifest 作废 |
| 换模型 / 换提示词 | 新基线另存 `baseline_v0_<provider>_<prompt_version>.json`，禁止覆盖 |

### 3.3 指标口径（数值待实测，先定口径）

| 指标 | 口径 | 标签 |
| --- | --- | --- |
| 意图准确率 | `intent_pred == intent_gold`，分母为全部样本 | `provider` |
| 工具调用正确率 | 期望集合与实调集合双向相等（不含纯读工具） | `provider` |
| 参数正确率 | 逐键比对，金额整数分精确匹配 | `provider` |
| 转人工 | 必转漏转（FN）优先于误转（FP）报告；给 TP/FP/FN/TN | `policy_version` |
| 草稿采纳率 | 人工 A/B/C 档 + 要素通过率分列 | 人工 |
| 成本 | 缺 usage 记 `null`，不进均值 | `provider` |
| P95 延迟 | 端到端 wall clock，不含测试启动 | `provider` |

---

## 4. 证据索引

每条验收在 `reports/evidence-index.md` 登记一行：`AC 编号 | run_id | 命令 | 时间 | 结果`。
没有登记的 AC，在报告里只能写"未验证"。
