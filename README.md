# 电商售后工单 AI（W1 垂直切片）

把一条中文售后工单变成**可审计的处置建议**：读单 → 归一化 → 模型出提案 → 策略定结论 →
草稿过出口闸门 → 落售后单（或只读意图直接给人工话术）。

一期只做**仅退款**闭环；**退货退款**做到"审核通过 → 待买家寄回"即截断。
详见 [边界确认书](docs/CONTRACT.md) 与 [验收清单](docs/ACCEPTANCE.md)。

## 快速开始

```powershell
$env:PYTHONIOENCODING='utf-8'
pip install -r requirements.txt

# 跑一单（fixture 短名）
python -m app.cli run --fixture tb_1001
python -m app.cli run --fixture tb_1001 --confirm human:demo1   # 人工确认后打款
python -m app.cli run --fixture dy_2001                          # 超额 → 转人工
python -m app.cli run --fixture tb_1003                          # 超窗 → 拒绝口径

# 回放：用记录里的 policy/prompt 版本重算，看是否漂移
python -m app.cli replay --run-id <run_id>
```

退出码：`0` 已定稿、`2` 降级（预算/超时/坏输出）、`3` 领域错误（如状态非法）。

## 测试

```powershell
python -m pytest -q                      # 契约 + 验收，共 52 条
python -m pytest tests/acceptance -q     # AC01–AC26
```

## 检索评测

```powershell
python scripts/gen_retrieval_data.py             # 合成 40 条 QA + 60 条标注查询
python -m app.eval.retrieval --retriever keyword # recall@5
python -m app.eval.retrieval --compare           # keyword vs hybrid，写 reports/retrieval_v0.json
```

v0 实测（合成集，`provider=scripted`）：keyword recall@5 = **0.950**，hybrid = **0.950**，
delta = 0.000 < 3pt → **向量通道关闭**。三条漏检（"P 图"、"起诉"、"没货"）是词面缺口，
正好说明这套数字只证明管线通、不证明语义能力；真实结论要等 200 条人工打标 QA。

## 封存基线

```powershell
python -m app.eval.seal    # 全绿才写 reports/baseline_v0.json；任一 AC 红则退出码 1
```

封存内容：git sha、fixture 清单 hash、`policy_version`、`prompt_version`、模型五元组、
数据集 hash、逐条 AC 结果。任一 AC 转红，该基线作废。

## 目录

```
app/contracts/   领域模型、错误码、金额/时间类型
app/adapters/    淘宝/抖店脏数据归一化（平台字段只在这一层）
app/domain/      售后单状态机（唯一迁移入口）
app/policy/      退款策略（纯函数）+ 出口话术整形
app/llm/         Provider 协议、prompt、scripted 台词
app/retrieval/   BM25 关键词检索 + 混合（向量通道默认关）
app/core/        pipeline（预算/超时/重试/引用校验）、脱敏
app/eval/        检索评测、基线封存
fixtures/        10 个故意脏的快照
tests/           契约测试 + AC 验收测试
reports/         runs.jsonl、retrieval_v0.json、baseline_v0.json
```

## 明确不做（一期）

真实平台 API、自动打款（NG-1）、退货退款全链路（NG-2）、多轮会话（NG-5）、
队列/外部中间件（NG-8）、独立向量库。`Mock` 打款只在 `FixtureAdapter` 里返回一个假单号。

## 已知边界

- 一切金额是**整数分**；一切时间是 **UTC**；平台分/元换算只发生在 adapter。
- 模型是台词化的 `ScriptedProvider`：它证明编排，不证明智能。
- 检索数据集是合成的：0.95 不能对外当作效果指标。
- 没有并发与队列：`pipeline.run` 同步执行，靠 `timeout_ms` + `token_budget` 兜底。
