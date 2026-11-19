# 凭证与服务地址

运行密钥、数据库密码和部署地址通过环境变量注入；`.env.example` 仅是模板，`.invalid` 域名不能用于运行。Java/Python 不自动读取 `.env`，不要将密钥放入 `VITE_*`（它们会被编译进浏览器包）。

| 变量 | 用途 |
| --- | --- |
| `APP_HMAC_SECRET` | Java 签名密钥，至少 32 字符 |
| `APP_AGENT_TOKEN` | 坐席令牌，至少 32 字符，必须与 HMAC 不同 |
| `AFTERSALE_HMAC_SECRET` | Python 验签密钥，与 Java HMAC 一致 |
| `APP_AGENT_BASE_URL` | Java HTTP 模式调用 Python 的服务地址 |
| `AFTERSALE_JAVA_BASE_URL` | Python 调用 Java 工具的服务地址 |
| `JAVA_PROXY_TARGET` | Vite 开发服务器代理 Java 的目标；不会注入浏览器包 |
| `VITE_API_BASE` | 浏览器可见的 API 前缀，默认 `/api`，不能包含密码/令牌 |
| `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` | MySQL 连接配置；用户名/密码没有默认值 |

## 本机开发

在仓库根目录的每个 PowerShell 终端先执行：

```powershell
. ./scripts/dev-env.ps1
```

首次执行生成两把独立的随机凭证到 Git 忽略的根 `.env`，后续终端加载同一份配置，脚本不会输出值。默认地址只绑定本机回环，属于开发示例；按需在私有 `.env` 内改端口。不要把该文件、终端环境或明文令牌截图上传。

然后分别启动 Java（默认 dev）、Python 和 Vite。坐席令牌从本机私有配置获取，在坐席页面密码框输入；前端不再包含默认令牌，旧版本 localStorage 中的坐席令牌会被清除，新令牌仅存当前标签页 sessionStorage。

`test` profile 的固定合成凭证仅用于无网络 H2 测试；dev/mysql/prod 不接受这些测试值。`mvn test` 与 Python pytest 不需要部署密钥。

## 部署

用运行环境或机密管理服务注入实际值；地址须为 HTTP(S)，不能在 userinfo、query 或 fragment 中携带凭证。Java 以 `app.agent.mode=http` 启动时必须配置 Agent 地址，Python 启动时必须配置 Java 地址。错误消息不会回显提供的地址。

Git 忽略 `.env`、`.env.*`（保留 `.env.example`）、私有 `*.local.yml` / `*.local.yaml` / `*.local.properties` 及常见私钥文件。公共 Maven/XML 命名空间、依赖镜像和 localhost 文档示例不属于部署秘密。

## 历史归档与历史提交

2026-11-20 对归档输出中的旧演示凭证与服务 URL 做了脱敏，见证据目录 `redaction-manifest.json`。它们现在是脱敏副本；原统计值及 source-hashes 中的历史源码指纹不变。

此次修改清理当前 Git 文件树，不重写旧提交历史，也不删除 GitHub 既有 Actions artifact。若旧提交曾存放真实有效的密钥，仍需在签发方撤销/轮换；旧提交历史和外部制品需单独清理。
