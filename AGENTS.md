# BeModel 开发指引

本文件适用于整个仓库；子目录如有更具体的 `AGENTS.md`，在该目录内补充适用。默认使用中文沟通，交付时说明修改内容、验证结果和未验证部分。

## 项目与权威来源

BeModel 是医疗本体与语义映射平台。平台元数据库保存概念、映射、规则、版本和审计信息，业务查询通过映射访问 HIS、LIS、收费、药房、EMR、门诊、PACS、护士站和物资等独立 MySQL 库。

| 位置                                | 职责                                                                                    |
| ----------------------------------- | --------------------------------------------------------------------------------------- |
| `bemodel-server/`                 | Java 21、Spring Boot、MyBatis-Plus、Flyway、Jena 原后端；对等迁移的行为基线             |
| `bemodel-server-py/`              | Python 3.12+、FastAPI、SQLAlchemy、PyMySQL、rdflib/pySHACL 的对等后端，运行时不依赖 JVM |
| `bemodel-web/`                    | Vue 3、Vite、Element Plus、Pinia、ECharts 共用前端                                      |
| `docs/python-migration-plan.md`   | 迁移方案、模块清单和验收要求                                                            |
| `bemodel-server-py/README.md`     | Python 安装、启动、测试和兼容细节                                                       |
| `bemodel-server-py/ACCEPTANCE.md` | 功能验收口径、专项证据及已知例外                                                        |
| `bemodel-server-py/artifacts/`    | 回放、数据对账、测试报告和打包产物；属于运行记录，不是行为实现                          |

根目录 README 主要描述 Java 版本。判断当前 Python 能力时同时阅读 Python README、实际源码和验收记录。迁移方案与 Java 实际行为冲突时，用源码及双端实测确认，记录偏差，不照抄方案中的错误公式。

开始修改前查看 `git status --short` 和目标文件；工作区可能已有用户改动及未提交的迁移成果，不覆盖、不回滚无关内容。迁移类任务默认保持 Java 基线与前端契约，优先修改 Python；用户明确要求 Java 或前端功能时按其指定范围处理。

## 代码导航与实现约定

- Java 主代码：`bemodel-server/src/main/java/com/bemodel/`，测试：`src/test/java/com/bemodel/`。
- Python 主代码：`bemodel-server-py/src/bemodel/`，测试：`bemodel-server-py/tests/`。采用 src layout，应使用项目虚拟环境并安装包。
- Python `core/` 集中处理 DAO、数据库会话、事务、迁移、异常、权限、CORS、加密和调度；`main.py` 负责路由与启动/关闭。
- 按现有业务模块组织实现：`ontology`、`modeling`、`datasource`、`instance`、`flow`、`clinical`、`governance`、`link`、`rca`、`cs`、`search`、`notice`、`rdf`、`llm`、`architecture`、`impact`、`value`、`seed`。
- Python 路由保持薄层，业务逻辑放入服务；阻塞数据库操作沿用同步路由和 SQLAlchemy `Session`，不要把阻塞查询直接移到事件循环。
- 前端请求集中在 `bemodel-web/src/api/`，公共处理在 `api/request.js`；鉴权见 `router/index.js`、`store/user.js`；页面在 `views/`，公共样式在 `styles/`。沿用现有 API 封装和样式，不在页面另建重复请求客户端。
- `scripts/generate_models.py`、`extract_cs_prompts.py`、`extract_value_presentations.py` 等属于开发期生成工具。运行前检查输出目标，避免覆盖手工修复；服务运行时不能依赖读取 Java 源码。

## 必须保持的兼容契约

1. 成功响应为 `{code: 0, msg: "ok", data: ...}`。业务及框架异常沿用 HTTP 200、业务码 500；框架异常有 `系统异常: ` 前缀。鉴权失败使用 HTTP 401/403。不要换成 FastAPI 默认 422，也不要把 `msg` 改为 `message`。
2. 实体对外使用 camelCase，空字段输出 `null`；SQL 结果字典保留 SQL 返回列名。统一使用 `core/result.py`，不要全局递归改写业务 SQL 列名。
3. DAO 更新只写非 `None` 字段，插入返回输入字段及自增 ID，不自动把数据库默认值全部填进响应。加载后的实体被赋 `None` 时也要保留此语义。
4. 保留 `ReleaseService.publish`、OWL 导入、客服退款和 schema 扫描的事务边界。退款中的演示收费库写入独立提交，不与平台库合并为一个事务。
5. 鉴权规则采用 first-match：登录放行；客服问答、搜索和反馈提交允许三角色；反馈列表只允许 ADMIN/EDITOR；其余 GET API 允许三角色，写操作只允许 ADMIN/EDITOR。普通 OPTIONS 不能当作 CORS 预检直接放行。
6. CORS 按原 Java 对 `/api/**` 配置；保留精确来源回显、非 API 预检拒绝和异常响应的跨域头。`main.py` 将 CORS 包装在全局异常处理中间件之外，不随意改回默认中间件顺序。
7. JWT TTL、claims、HMAC 密钥长度限制和 AES-GCM `ENC:` 密文格式必须互通；使用现有服务，不能另写不兼容算法。密钥与口令通过环境变量配置，不写入提交内容或日志。
8. 现有 V1–V28 SQL 和 `clinical-shapes.ttl` 是双端基线，保持逐字节一致。新增数据库需求使用增量迁移并检查两端兼容，不修改已执行迁移的历史内容或校验和。
9. Flyway 校验和、Java UTF-16 字符串哈希、日期序列化以已有实现和互通测试为准。方案里的滚动 CRC 公式及 `"abc"=126145` 不正确，实际哈希为 `96354`。不要将 JDBC `serverTimezone` 简单等同于修改 MySQL 会话时区。
10. SHACL 必须启用 `advanced=True`，否则会遗漏 SPARQL 约束。Python 引擎标识如实返回 `pySHACL`，不伪装为 Jena；业务违例必须单独核验。TTL 导出沿用当前字符级兼容实现。
11. LLM 查询必须经过现有 SQL 白名单校验；保留 15 秒查询超时、100 行结果上限和前 20 行展示。无 Key 和调用失败的降级、审计及概念缺口记录不能被省略。
12. 保持启动顺序：迁移 → 数据源密文迁移 → 种子 → 调度；关闭时释放调度器和数据库引擎。

## 开发命令

以下以 Windows PowerShell 为例。其他系统使用对应的 `.venv/bin/python`；不要硬编码某台机器的 JDK/Python 安装路径。

### Python（在 `bemodel-server-py/` 执行）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
# 仅首次缺少 .env 时复制，再配置独立数据库；不要覆盖已有配置
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn bemodel.main:app --host 127.0.0.1 --port 18080
```

`.env` 相对启动目录读取。启动会自动迁移并可能重建演示数据，执行前确认数据库目标。Java/Python 默认都使用 18080，不能同时占用；启动前核对端口和进程归属，不盲目终止现有服务。

### Java（在仓库根目录执行）

```powershell
# 先设置 JAVA_HOME（JDK 21）、MYSQL_USERNAME、MYSQL_PASSWORD 和隔离的 SPRING_DATASOURCE_URL
mvn -f bemodel-server/pom.xml spring-boot:run
mvn -f bemodel-server/pom.xml test
```

Java 测试可能启动 Spring 上下文并写库，不能带着默认业务数据库配置运行。`.m2-test` 是本地测试缓存，需要时通过 `-Dmaven.repo.local=...` 指定，不作为可移植依赖写死。

### 前端（在 `bemodel-web/` 执行）

```powershell
npm install
npm run dev
npm run build
```

Vite 默认监听 `127.0.0.1:5173`，将 `/api` 代理到 `127.0.0.1:18080`。当前 `package.json` 没有 test/lint 脚本，不报告未配置的检查为已通过。UI 修改按需构建并做浏览器验证。

## 数据库与测试

- 集成测试和写入回放只使用隔离临时 MySQL；不连接业务库。种子不是无副作用操作，会按新鲜度判断重建演示数据。
- `compose.test.yml` 的 MySQL 数据存于 tmpfs，销毁容器会丢失数据。仅操作本任务所属项目；不要清理用户或其他任务的容器、数据库和浏览器会话。
- 无 MySQL 时，在 Python 目录执行 `python -m pytest tests -q`：依赖 `mysql_session` 的用例会跳过。不能将这种结果报告为“全部集成测试通过”；也不要仅凭 `integration` marker 假定所有数据库用例均已排除。
- 完整 Python 集成环境固定为本机 **13317 / `bemodel_py_test`**，由 fixture 校验；设置 `BEMODEL_MYSQL_TESTS=1`、`BEMODEL_DISABLE_SCHEDULER=1`、空 `DEEPSEEK_API_KEY`。使用 Python README 的 Docker 和 `bootstrap_test_db.py` 命令，不放宽保护条件来适配业务库。
- 独立双端完整验收使用 **Java 18083 → MySQL 13319**、**Python 18084 → MySQL 13320**，库名均为 `bemodel_acceptance`。初始化和复验顺序见 `ACCEPTANCE.md`，不要把旧脚本默认的 18080/18081 当成当前实际部署。

从仓库根目录可执行：

```powershell
# 不启动数据库的 API 路由核对
.\bemodel-server-py\.venv\Scripts\python.exe bemodel-server-py/scripts/check_route_coverage.py

# 以下仅在双端隔离环境已就绪、起始数据一致时执行
.\bemodel-server-py\.venv\Scripts\python.exe bemodel-server-py/scripts/full_acceptance.py
.\bemodel-server-py\.venv\Scripts\python.exe bemodel-server-py/scripts/check_acceptance_state.py
```

`full_acceptance.py` 会发布版本、创建工单和退款；执行后不能直接把库当作新鲜基线重复运行。`--recompare` 只重算已保存响应，不是重新验证当前服务。调用其他回放脚本前阅读端口、库名及环境变量限制。

## 验证与交付

- 先运行与改动相关的测试；涉及公共 DAO、鉴权、中间件、序列化、迁移或跨模块服务时，扩大到完整 Python 回归及相应 Java/Python 专项对比。
- 接口存在或两端同时返回错误不能证明功能成功。新增或修改接口需验证实际业务结果；写路径还需核对持久化状态及失败时的事务边界。
- 归一化只能排除已说明的非业务差异（如时间戳、耗时、随机密文）。不能为了报告变绿忽略金额、状态、关联或业务主键差异。
- `artifacts/` 中的通过数和覆盖率是某次运行的证据，不保证当前代码通过；交付前确认相关报告与本次改动相符。真实 DeepSeek 未调用时明确说明，不以 HTTP 替身测试宣称外部服务验收成功。
- 只改文档时检查路径、命令及内容即可；业务修复增加有意义的回归测试。不要为凑数量编写只重复实现的断言。
- 如需交付 wheel，重新构建并确认包含当前源码、SQL、SHACL 和种子资源：`python -m pip wheel ./bemodel-server-py --no-deps --wheel-dir bemodel-server-py/artifacts/dist`（仓库根目录）。
- 不提交虚拟环境、`node_modules`、Maven 缓存、真实 `.env` 或秘密信息。保留与任务无关的已有修改，不将本地端口占用、临时进程 ID 或历史测试通过数写成永久项目约定。

中文回复

后台所有扩展、新增功能或接口等只在bemodel-server-py目录下完成，bemodel-server目录不用增加。即后台只维护python版本。
