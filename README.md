# 售后辅助处理 Agent（Java 业务后端 + Python AI 层）

客户说人话提交售后请求 → Agent 给出**建议**（意图、事实、政策依据、回复草稿）→ 坐席**确认**后生效。
**所有真实业务执行（退款、改地址、改状态）一律不实施**；落库的只有会话、草稿、工单状态与审计记录。

| 项 | 值 |
| --- | --- |
| 阶段 | Java M-S 通过 19 个 H2 集成测试；Python AI 层通过 21 个 pytest，已与 Java HTTP 模式联调 |
| 契约版本 | `BOUNDARY_v1` **v1.4.1** ↔ `openapi.yaml` **v1.5.1**（版本独立演进；对应关系与文件指纹见 `docs/contract-snapshot.json`） |
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
│   ├── src/test/java/...     ApiIntegrationTest（19 用例）
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
mvn -B test                 # 19 个 H2 集成测试
mvn -DskipTests package
java -jar target\aftersale-agent-java-0.1.0-SNAPSHOT.jar
# http://localhost:8080 ，Swagger: /swagger-ui.html

# 另开终端：Python AI 层
cd python
pip install -r requirements.txt
python -m pytest -q         # 21 个 pytest
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

联调时 Java 加 `--app.agent.mode=http`，并保证两端 `hmac-secret` 一致。本机 PATH 上是 JDK 8，需显式切 `JAVA_HOME`；中文路径下 `mvn spring-boot:run` 可能 classpath 失败，推荐 `package` + `java -jar`。MySQL80 服务在跑但无 CLI 与账号，dev 先用 H2。完整接口冒烟见 `java/README.md`，Python 规则与联调见 `python/README.md`。

---

## 指标（诚实版）

| 指标 | 状态 |
| --- | --- |
| Java M-S 集成测试 | 19/19 通过（H2）；真实并发竞争、执行失败 202 分支未做线程级验证 |
| Python AI 单元测试 | 21/21 通过（规则式桩，FakeTools）；未接真实 LLM |
| 意图准确率 / 槽位 F1 / 引用精确率 | **未测**（M-Q 需 50 例 holdout 与真实模型，当前为规则式基线） |
| 端到端闭环 | Java + Python HTTP 模式已通：咨询 → 转售后 → 草稿 → 坐席确认 → `CLOSED` |
| MySQL 真机 | DDL 已提供，本机未连 MySQL 验证生成列/唯一索引 |
| 延迟 / 成本 | 未采样 |

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
