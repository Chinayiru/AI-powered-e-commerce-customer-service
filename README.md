# 售后辅助处理 Agent（Java 业务后端 + Python AI 层）

客户说人话提交售后请求 → Agent 给出**建议**（意图、事实、政策依据、回复草稿）→ 坐席**确认**后生效。
**所有真实业务执行（退款、改地址、改状态）一律不实施**；落库的只有会话、草稿、工单状态与审计记录。

| 项 | 值 |
| --- | --- |
| 阶段 | Java 26 项、Python 21 项、HTTP 冒烟 26 项通过；工程通过、指标未闭合、整体未验收 |
| 契约版本 | `BOUNDARY_v1` **v1.4.1** ↔ `openapi.yaml` **v1.5.2**（版本独立演进；对应关系与文件指纹见 `docs/contract-snapshot.json`） |
| 执行模式 | `SIMULATED`（演示不碰真实资金） |
| 技术栈 | Java 17 + Spring Boot 3.3.5 + MyBatis + H2/MySQL；Python 3.12 + FastAPI + Pydantic v2（规则式 Agent，未接 LangGraph/LLM） |

---

## 现在仓库里有什么

```
.
├── docs/
│   ├── BOUNDARY_v1.md        边界确认书（范围、状态机、幂等、AC01–AC26）
│   ├── DATA_DICTIONARY.md    状态机迁移表、字段字典、可见性、DDL
│   ├── TOOLS.md              工具清单与调用契约（只读工具 + Java 内部写）
│   ├── AGENT_RAG_SPEC.md     意图/槽位/检索/草稿/转人工规范
│   ├── TEST_PLAN.md          AC/QC 用例、夹具、反向注入、通过判定
│   ├── DEMO.md               5 分钟演示脚本与问答预演
│   ├── contract-snapshot.json 契约快照：BOUNDARY 与 OpenAPI 的版本对应 + SHA-256
│   └── api/openapi.yaml      接口契约（14 个端点，三组）
├── java/                     Spring Boot 业务后端
│   ├── src/main/java/...     身份、状态机、幂等、政策、生成、确认执行、审计
│   ├── src/main/resources/   application*.yml、H2/MySQL DDL
│   ├── src/test/java/...     集成与回归测试（26 用例）
│   └── README.md             启动、接口冒烟、实现取舍、测试映射
├── python/                   FastAPI 只读 AI 层
│   ├── app/                  契约、意图/槽位、检索、工具客户端、草稿
│   ├── tests/                pytest（21 用例）
│   └── README.md             启动、环境变量、与 Java 联调、规则说明
└── README.md
```

本仓库包含 Java 与 Python 两层。Java 默认可用内置 `scripted` Agent 桩完成 M-S 验收；设置 `--app.agent.mode=http` 后调用 Python 的 `/internal/agent/ask`。

---

## 三层职责（一句话版）

| 层 | 职责 | 不允许 |
| --- | --- | --- |
| Java | 身份、状态机、幂等、审批、落库、审计 | 让 Python 决定能否退款 |
| Python | 意图、槽位、检索、草稿、置信度 | 连数据库、执行写操作、接收 userId 入参 |
| 人（坐席） | 确认、改写、转交 | 被前端置灰"代为"校验 |

---

## 关键契约速查

| 对象 | 值 |
| --- | --- |
| 工单状态 | 咨询 7 态 / 售后 **10 态**（含与咨询共享的 `REPLIED`，见数据字典 §1–3） |
| 客户可见状态 | 处理中 / 待补充信息 / 待人工处理 / 已回复 / 已完成 / 已取消 |
| 转人工原因 | 9 个封闭枚举 |
| 错误码 | 17 个封闭枚举 |
| 置信度阈值 | 运行时 `intent.confidence_threshold = 0.60`；`0.85` 是 M-Q 意图准确率目标，不是阈值 |
| 金额单位 | **分**（整数） |
| 幂等键 | 前端生成 `requestId`，作用域 `(userId, endpoint, targetId, requestId)` + 请求摘要 sha256 |
| 客户响应 | 状态**只用** `displayState`；其余字段按各响应白名单；`state`/`intent`/`confidence` 一律不外露 |

---

## 快速开始

```powershell
$env:JAVA_HOME="$env:USERPROFILE\.jdks\corretto-17.0.9"
$env:Path="$env:JAVA_HOME\bin;$env:Path"

cd java
mvn -B test                 # 26 个 H2 集成与回归测试
mvn -DskipTests package
java -jar target\aftersale-agent-java-0.1.0-SNAPSHOT.jar
# http://localhost:8080 ，Swagger: /swagger-ui.html

# 另开终端：Python AI 层
cd python
pip install -r requirements.txt
python -m pytest -q         # 21 个 pytest
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

联调时 Java 加 `--app.agent.mode=http`，并保证两端 `hmac-secret` 一致。本机 PATH 上是 JDK 8，需显式切 `JAVA_HOME`；中文路径下 `mvn spring-boot:run` 可能 classpath 失败，推荐 `package` + `java -jar`。MySQL 8.0.30 已在本机验证：库 `aftersale`、应用账号 `aftersale`，`schema-mysql.sql` 可直接初始化；dev 默认仍用 H2。完整接口冒烟见 `java/README.md`，Python 规则与联调见 `python/README.md`。

MySQL 8 初始化与启动（可选）：

```sql
CREATE DATABASE IF NOT EXISTS aftersale
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'aftersale'@'localhost' IDENTIFIED BY 'aftersale';
GRANT ALL PRIVILEGES ON aftersale.* TO 'aftersale'@'localhost';
```

```powershell
java -jar target\aftersale-agent-java-0.1.0-SNAPSHOT.jar --spring.profiles.active=mysql
```

---

## 指标（诚实版）

| 指标 | 状态 |
| --- | --- |
| Java M-S 集成测试 | 26/26 通过（H2），含执行失败重试与咨询转售后回归；未做线程级并发压测 |
| Python AI 单元测试 | 21/21 通过（规则式桩，FakeTools）；未接真实 LLM |
| 意图准确率 / 槽位 F1 / 引用精确率 | 2026-11-17 holdout：意图准确率 75%（门槛 85%，未达标）、订单号召回 100%；草稿可用率待双评 |
| 端到端闭环 | Java + Python HTTP 模式已通：咨询 → 转售后 → 草稿 → 坐席确认 → `CLOSED` |
| MySQL 真机 | 已在本机 MySQL 8.0.30 验证生成列、唯一索引与 `ON DUPLICATE KEY UPDATE`；未做多实例并发压测 |
| 延迟 / 成本 | 进程内 P50/P95 0.02/0.05 ms，不含 HTTP/序列化，不可作为系统延迟对外报；规则式成本 0 元 |

不写"准确率 95%"这种没有出处的数字。

---

## 非目标（一期明确不做）

- 自动退款 / 自动补发 / 自动改地址
- 多轮开放域聊天（只做售后流程内的追问）
- 真实电商 API 对接（数据为夹具，且故意脏）
- 大促并发与容量承诺
- `REAL` 执行模式（调用即拒）

---

## 阅读顺序

1. `docs/BOUNDARY_v1.md` —— 看范围与不做什么
2. `docs/api/openapi.yaml` —— 再看接口长什么样
3. `docs/DATA_DICTIONARY.md` —— 状态怎么流转、字段谁能看
4. `docs/TOOLS.md` + `docs/AGENT_RAG_SPEC.md` —— 谁提供事实、谁说人话
5. `docs/TEST_PLAN.md` + `docs/DEMO.md` —— 怎么证明、怎么讲
6. `java/README.md` —— Java 实现、启动方式、取舍与测试映射
7. `python/README.md` —— Python 规则、启动方式、与 Java 联调

## 独立端口复跑与合入门

2026-11-17 归档结论：**工程通过、指标未闭合、整体未验收**。见 [整改报告](整改与验收报告_2026-11-17.md)、[独立复跑报告](测试复跑报告_2026-11-17.md)。QC12 仅验证同日、同进程、同实例一致；跨日与跨进程未验证。业务仍读 date.today()，归档指标仅在 2026-11-17 有效。

依赖安装会自动使用 `python/constraints.txt`，锁定本次 Python 3.12.14 复跑环境；原测 Python 3.12.10 / FastAPI 0.162.0 与此不同。

默认端口冲突时，两端地址和冒烟参数必须一起改。例如在仓库根目录打包后，分终端执行：

```powershell
# Python 终端（先激活已安装依赖的 Python 环境）
cd python
$env:AFTERSALE_JAVA_BASE_URL = 'http://127.0.0.1:18080'
python -m uvicorn app.main:app --host 127.0.0.1 --port 18000

# Java 终端，位于仓库根目录，使用 JDK17
& "$env:JAVA_HOME\bin\java.exe" -jar java\target\aftersale-agent-java-0.1.0-SNAPSHOT.jar `
    --spring.profiles.active=dev --server.address=127.0.0.1 --server.port=18080 `
    --app.execution.mode=SIMULATED --app.agent.mode=http --app.agent.base-url=http://127.0.0.1:18000

# 冒烟终端，位于仓库根目录；两端 HMAC 必须一致
python scripts\e2e_smoke.py --java http://127.0.0.1:18080 --python http://127.0.0.1:18000
```

评测与质量门分开执行（仓库根目录）：

```powershell
python python\eval\run_eval.py
python scripts\check_eval_gate.py python\eval\eval_result.json
```

QC02 < 85% 时质量门退出 1；当前 75% 会使 CI 的 `QC02 quality gate` 红灯。评测脚本退出 0 只表示产出成功。分支保护应将该检查设为必需项，QC05 人工验收仍需另行完成。

`测试复跑证据_2026-11-17_111501/` 随仓库长期保留；含依赖的大体积工作区副本仅保留至 2026-11-24，之后可人工清理。
