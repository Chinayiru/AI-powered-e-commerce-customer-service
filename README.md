
---

## 并入的 W1 垂直切片（`app/` + `web/` + `src/`）

除上面这套 `java/`（JDK 17 / Spring Boot 3.3.5）+ `python/`（FastAPI 规则式 Agent）之外，仓库另含一条用 Python 重写的垂直切片，以及配套 React 控制台与 Java 托管壳。三者互不依赖，可分别启动：

| 路径 | 内容 | 启动 |
| --- | --- | --- |
| `app/` | 读单 → 提案 → 策略 → 出口闸门 → 落单的可审计流水线，测试全离线 | `python -m app.cli run --fixture tb_1001` |
| `app/api/server.py` | 上述唯一业务实现之上的 HTTP 薄封装（`X-Operator-*` 鉴权、`client_token` 幂等、`/api/replay` 回放） | `python -m app.api.server` → 127.0.0.1:8000 |
| `web/` | Vite 5 + React 18 + TypeScript 控制台：工单处理 / 运行记录 / 评测与基线 | `cd web; npm install; npm run dev` → 5173（`/api` 代理到 8000）；或 `npm run build` 交给 8000 托管 |
| `src/` + `pom.xml` | Spring Boot 2.7（**JDK 8**）壳：托管 `web/dist` 并把 `/api/**` 反代到 Python，不复制任何业务规则 | `mvn -DskipTests package; java -jar target/aftersale-console-0.1.0.jar` → 8080 |

注意两套 Java 不是同一个东西：`java/` 是原业务后端（JDK 17 / Boot 3），`src/` + 根 `pom.xml` 是本切片的托管壳（JDK 8 / Boot 2.7），**不要用同一个 JAVA_HOME 构建两者**。本切片的边界与验收口径见 `docs/CONTRACT.md`、`docs/ACCEPTANCE.md`（与根目录 `docs/BOUNDARY_v1.md` 是两套文档）。

测试：`python -m pytest -q`（切片自身）；`cd web && npm run build`（类型检查 + 打包）。