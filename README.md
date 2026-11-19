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

## Web 控制台

```powershell
# 终端 A：后端（127.0.0.1:8000，同时托管构建好的前端）
python -m app.api.server

# 终端 B：前端开发模式（127.0.0.1:5173，/api 代理到 8000）
cd web
npm install
npm run dev
```

演示模式只需构建一次，之后直接开 http://127.0.0.1:8000：

```powershell
cd web; npm run build; cd ..; python -m app.api.server
```

三个页签：**工单处理**（快照 + 原文改写 + 草案/人工确认 + 结果证据链 + 回放校验）、
**运行记录**（`reports/runs.jsonl` 审计表与详情弹窗）、**评测与基线**（AC01–AC26、
recall@5 对比、复现命令）。API 文档在 http://127.0.0.1:8000/api/docs。

控制台只调用 `/api/*`；策略、闸门、状态机仍只有 `app/` 里一份实现（ADR-011）。
`RUNS_PATH` 可覆盖记录文件，`PORT` 可改端口。前端技术栈：Vite 5 + React 18 + TypeScript。

写接口要操作人身份（ADR-013）。先在 `.env` 配一张操作人表，再在控制台右上角登录：

```powershell
# .env   格式 "id:token,id:token"；未配置时 POST /api/runs 一律 503
AFTERSALE_OPERATORS=demo1:tok-demo1
```

控制台把身份放进 `X-Operator-Id` / `X-Operator-Token` 请求头（只存 `sessionStorage`，退出即失效）。
审批人由服务端按身份写成 `confirm=human:<id>`：前端输入框已改为只读，替别人签会被 403 拒绝。
`curl` 手测同理：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/runs ^
  -H "Content-Type: application/json" ^
  -H "X-Operator-Id: demo1" -H "X-Operator-Token: tok-demo1" ^
  -d '{"fixture":"tb_1001","confirm":"human:demo1"}'
```

### Java 入口（静态页托管 + `/api` 反代）

演示时可以只对外暴露一个 Java 进程：它托管 `web/dist`，并把 `/api/**` 原样转给 Python 服务。
业务规则仍然只在 Python，Java 侧没有第二套判断（CONTRACT NG-6 / ADR-011）。

前提：JDK 8（本机 1.8.0_251）+ Maven 3.x，且前端已构建（`web/dist` 存在，打包时才打得进去）：

```powershell
cd web; npm run build; cd ..
mvn -DskipTests package
java -jar target/aftersale-console-0.1.0.jar      # http://127.0.0.1:8080
```

另开一个终端跑 `python -m app.api.server`（127.0.0.1:8000）。改端口用
`--server.port=8081` 与 `--aftersale.api-base=http://127.0.0.1:8001`。

`X-Operator-Id` / `X-Operator-Token` 原样透传，鉴权、状态码、错误体都由 Python 决定；
只有 Python 确实连不上时才返回 `502 {"code":"E_API_UNREACHABLE",...}`。
SPA 路由（`/runs`、`/eval` 直接刷新）回退 `index.html`，缺失的 `.js/.css` 仍是 404。

## 接入真实模型（OpenAI 兼容）

默认走 `ScriptedProvider`（确定性回放，不联网）。接真实模型不需要改代码，只改配置：

```powershell
# 1) 复制模板，填三项；.env 已被 git 忽略
Copy-Item .env.example .env

# 2) 三项配置（也可以只设进程环境变量，优先级：显式参数 > 环境 > .env）
#    AFTERSALE_LLM_PROVIDER=openai_compat      # scripted | openai_compat | auto
#    AFTERSALE_LLM_BASE_URL=https://your-gateway/v1
#    AFTERSALE_LLM_MODEL=<model-id>
#    AFTERSALE_LLM_API_KEY=<key>

# 3) CLI 直接跑真实模型；也可以只用 --provider 临时切换
python -m app.cli run --fixture tb_1001 --provider openai_compat
python -m app.cli run --fixture tb_1001 --provider auto   # 同 openai_compat：配置不齐直接报错，不静默回退
```

`auto` 与 `openai_compat` 同标准——缺 `AFTERSALE_LLM_API_KEY` 等任一项就抛配置错误，
不再"悄悄改用 scripted"（那会让线上事故无法归因）。本地想离线跑请显式 `--provider scripted`
或把 `AFTERSALE_LLM_PROVIDER=scripted` 写进 `.env`。

`/api/meta` 会返回 `provider`/`model`/`configured`，控制台右上角与运行记录都以此为准；
每条 run 记录里的 `llm` 字段保存五元组，`replay` 会按记录里的 provider/model 重建，
因此真实模型回放出现 `drift` 是正常的（模型非确定性），脚本 provider 才要求零漂移。

两点约束：

- **测试永远用 scripted**：`tests/conftest.py` 的 autouse fixture 强制
  `AFTERSALE_LLM_PROVIDER=scripted`。真实模型输出不确定，AC16（回放）、AC20（两次一致）
  要求确定性，测试不能联网、不能计费。
- **换模型必须另存基线**：`python -m app.eval.seal --provider openai_compat` 会写
  `reports/baseline_v0_openai_compat_<prompt_version>.json`，拒绝覆盖 `baseline_v0.json`。

## 测试

```powershell
python -m pytest -q                      # 契约 + 验收 + API + provider + 意图，共 112 条（全离线）
python -m pytest tests/acceptance -q     # AC01–AC26
python -m pytest tests/test_api.py -q    # 前端依赖的 HTTP 契约
python -m pytest tests/test_llm_openai_compat.py -q   # 真实 provider 的离线契约（假 transport）
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

## 意图开发集与规则评测

意图判断（`refund` / `address_change` / `shipping_urge` / `other`，以及退款的
`refund_only` / `return_refund` 子类型）有一套**独立于检索集**的标注数据，用来回答
"只看文本能到多少分"，而不是靠手感。

```powershell
python -m app.eval.intent            # 开发集门禁 + 两个留出集，写 reports/intent_dev_v0.json
python -m app.eval.intent --quiet    # 只打错误清单
```

数据（三份，文本互不重复，也与 `queries_60.jsonl`、`fixtures/` 工单文本不重复）：

| 文件 | 条数 | 用途 |
| --- | --- | --- |
| `data/eval/intent_dev.jsonl` | 94 | 唯一允许调参的集合（`ID001`–`ID094`） |
| `data/eval/intent_holdout.jsonl` | 50 | 第一留出集；它的 8 个错误被拿来补同义词 → **已污染**，0.86 不能再当泛化数字 |
| `data/eval/intent_holdout2.jsonl` | 30 | 冻结留出集，v2 规则只在它上面测过一次 |

v2 实测（`app/intent/rules.py`，纯函数、离线、不联网）：

| 集合 | accuracy | macroF1 | 子类型准确率 |
| --- | --- | --- | --- |
| 单关键词基线（naive） | 0.596 | 0.646 | 0.882 |
| 规则 v1 · 开发集 | **1.000** | 1.000 | 1.000 |
| 规则 v1 · holdout2（冻结） | **0.967** | **0.953** | 0.929 |

开发集 1.000 是**过拟合的诚实写法**，不是成绩。4 分类的泛化数字看 holdout2：
30 条里错 2 条——`HT07`"尺码选错了，退款吧，东西没寄"（应 `refund_only`，"尺码"
带了退货语义）、`HT20`"两天了还没发，催一下"（"催一下"权重 3 分，低于成案阈值 4）。
这两条留在数据里不修，等下一轮用**新**开发样本处理，以保住 holdout2 的冻结性。

边界（重要）：规则层是**离线先验**，`app.core.pipeline` 不 import 它，它也不下退款
结论、不替代模型——线上仍以模型输出为准（CONTRACT P0 / §6.4）。测试
`tests/test_intent_rules.py` 会读源码断言这条依赖方向没被打破。

## 封存基线

```powershell
python -m app.eval.seal    # 全绿才写 reports/baseline_v0.json；任一 AC 红则退出码 1
python -m app.eval.seal --provider openai_compat   # 另存 baseline_v0_openai_compat_<prompt_version>.json
```

封存内容：git sha、fixture 清单 hash、`policy_version`、`prompt_version`、模型五元组、
数据集 hash、逐条 AC 结果。任一 AC 转红，该基线作废。换模型/换提示词只新增文件，
不允许覆盖 `baseline_v0.json`。

## 目录

```
app/contracts/   领域模型、错误码、金额/时间类型
app/adapters/    淘宝/抖店脏数据归一化（平台字段只在这一层）
app/domain/      售后单状态机（唯一迁移入口）
app/policy/      退款策略（纯函数）+ 出口话术整形
app/llm/         Provider 协议、prompt、scripted 台词
app/retrieval/   BM25 关键词检索 + 混合（向量通道默认关）
app/intent/      意图规则（离线文本先验，不接主链路）
app/core/        pipeline（预算/超时/重试/引用校验）、脱敏
app/eval/        检索评测、意图开发集评测、基线封存
app/api/         HTTP 包装（薄封装 pipeline，不新增业务规则）
web/             React + Vite 控制台；构建产物在 web/dist
fixtures/        10 个故意脏的快照
tests/           契约测试 + AC 验收测试 + API 契约测试
reports/         runs.jsonl、retrieval_v0.json、baseline_v0.json
```

## 明确不做（一期）

真实平台 API、自动打款（NG-1）、退货退款全链路（NG-2）、多轮会话（NG-5）、
队列/外部中间件（NG-8）、独立向量库。`Mock` 打款只在 `FixtureAdapter` 里返回一个假单号。
NG-6「前端工程化」已按 ADR-011 破例：控制台只做展示与触发，不复制业务规则。

## 已知边界

- 一切金额是**整数分**；一切时间是 **UTC**；平台分/元换算只发生在 adapter。
- 默认模型是台词化的 `ScriptedProvider`：它证明编排，不证明智能；它按 `order_ref` 取剧本，
  因此控制台里改写文本不会改变意图。配好 `.env` 走 `openai_compat` 后才由文本驱动，
  但真实模型非确定性，不适合当回归基线。
- 检索数据集是合成的：0.95 不能对外当作效果指标。
- 意图开发集也是**手写**的：holdout2 的 0.967 说明"规则能覆盖常见说法"，不等于
  线上分布。开发集 94 条全对是过拟合；真值要靠人工扩样与线上抽样复核。
- 没有并发与队列：`pipeline.run` 同步执行，靠 `timeout_ms` + `token_budget` 兜底。
