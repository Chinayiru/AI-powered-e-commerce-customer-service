# Hvue · 售后助手前端

Vue 3 + Vite 6 + Vue Router 4 的演示前端，对接仓库根目录下的 Java 后端（默认 `http://127.0.0.1:8080`）。

## 启动

```bash
# 1. 先启动 Java（仓库根目录）
cd ../java
mvn package
java -jar target/aftersale-agent-java-0.1.0-SNAPSHOT.jar

# 2. 可选：启动 Python AI 层，并让 Java 使用 HTTP 模式
cd ../python
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Java 启动参数追加：--app.agent.mode=http

# 3. 启动前端
cd ../Hvue
pnpm install
pnpm dev
```

打开 `http://localhost:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8080`，无需处理跨域。

> 本环境 `pnpm` 默认阻止依赖构建脚本。仓库已通过 `pnpm-workspace.yaml` 放行 `esbuild`；
> 若仍提示 `ERR_PNPM_IGNORED_BUILDS`，执行一次 `pnpm approve-builds --all`。

## 页面

| 路由 | 说明 |
| --- | --- |
| `/` | 客户首页：选订单、发起咨询/售后、查看最近工单 |
| `/tickets/:ticketId` | 客户会话：发消息、查看回复、撤销工单 |
| `/agent` | 坐席检索：输入工单号与坐席令牌，查看最近访问 |
| `/agent/tickets/:ticketId` | 坐席三栏工作台：对话 / 依据 / 草稿裁决 |
| `/about` | 演示说明、订单夹具、启动命令、边界 |

## 身份与凭证

- 客户建单：`X-User-Id: U001`（或 `U002`），仅演示白名单可用。
- 建单响应返回 `ticketId` 与 `ticketToken`；之后客户接口只认
  `Authorization: Bearer <ticketToken>`。
- `ticketToken` 只保存在当前浏览器的 `localStorage`，用于“最近工单”恢复；
  它不是长期登录态，也不会出现在页面文案里。
- 坐席接口只认 `X-Agent-Token`，默认演示值 `demo-agent-token`，可在检索页修改。

## 演示路径

1. 首页选择 `O1001`，输入“我买的订单 O1001 想退款，怎么办？”。
2. 咨询会先回复政策；继续发送“那就帮我退了吧”，会新建关联售后单并回传 `createdTicket`。
3. 到坐席工作台打开该售后单：查看意图、置信度、政策校验、工具调用与引用。
4. 修改草稿、填写复核说明（金额超过 5000 分时必须填），点击“确认发送”。
5. 工单经 `CONFIRMED → EXECUTING → CLOSED`，客户侧状态变为“已完成”。

其他夹具：`O1002` 物流、`O1003` 已签收 30 天（发送时被政策拦截）、
`O1006` 25000 分（必须复核）、`O1010` 已全额退款（转人工、无金额）、`O9999` 不存在。

## 交互约定

- 草稿未修改时“确认发送”置灰；需要复核时必须填写至少 5 个字的说明。
- 所有写操作使用 `crypto.randomUUID()` 生成 `requestId`；页面不自行重试写请求。
- 状态守卫、金额上限、幂等冲突都由 Java 裁决；前端只展示服务端错误码对应的中文提示。
- 客户页面不展示 `intent`、`confidence`、`TRANSFERRED` 等内部字段，只展示 `displayState`。
- 页面固定显示“演示环境 · 未真实退款”，避免把模拟执行误解为真实退款。

## 构建

```bash
pnpm build      # 产物在 dist/
pnpm preview    # 本地预览构建产物
```

## 已知限制

- 没有工单列表接口，坐席只能按工单号进入；最近工单来自当前浏览器缓存。
- 没有登录页；演示身份与令牌按契约通过请求头传递。
- 未接真实支付/退款，执行模式固定为 `SIMULATED`。
- 未做移动端专门适配，窄屏下三栏会折叠为单栏。
