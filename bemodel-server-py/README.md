# BeModel Python 后端

按照 `../docs/python-migration-plan.md` 将 Java 后端改写为 FastAPI + SQLAlchemy。Python 服务运行时不依赖 JVM。116 个 Java 基线 API 的方法、路径、鉴权规则和 MySQL 表结构保持对等；另有 8 个 Python 专属扩展接口（数据源失效/删除及 AI 本体治理），Java 后端保持冻结。

最新完整验收见 [ACCEPTANCE.md](ACCEPTANCE.md)：116/116 接口成功覆盖，131 项 Python 测试通过，75 张表操作后数据和结构一致。

## 启动

需要 Python 3.12+、MySQL 8.x。在本目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
Copy-Item .env.example .env
# 在 .env 中填写 MySQL 连接信息，然后启动：
.\.venv\Scripts\python.exe -m uvicorn bemodel.main:app --host 127.0.0.1 --port 18080
```

Linux/macOS 使用 `python3.12` 和 `.venv/bin/python`。必须从包含 `.env` 的目录启动，也可以直接设置同名环境变量。默认端口与原 Java 服务相同，切换时先停止占用 18080 的 Java 服务。

启动依次执行：SQL 迁移 → 数据源密文迁移 → 演示种子及结构化公理 → 指标巡检与数据源本体治理任务调度。V1–V28 和 SHACL 文件继续保持双端基线不变；Python 专属增量迁移从 V29 起追加。已有兼容的 Flyway 历史记录不会重复执行。演示数据保留原 Java 的新鲜度判断：不足时重建演示场景，因此验收必须使用独立测试库。

`MYSQL_USERNAME`、`MYSQL_PASSWORD` 也用于原始 SQL 的演示数据源占位符。原始脚本将演示源登记为本机 3306；非默认端口的测试环境由 `scripts/bootstrap_test_db.py` 单独调整登记端口，未修改迁移文件。跨主机部署需在数据源管理中配置相应连接。

`JWT_SECRET`、`APP_SECRET_KEY` 缺省时沿用 Java 的开发默认值；连接已有库时必须与原服务一致。`DEEPSEEK_API_KEY` 为空时使用原有降级路径。`BEMODEL_DISABLE_SCHEDULER=1` 可关闭定时巡检；`BEMODEL_INSPECT_CRON` 使用含秒的六字段表达式。

数据源扫描成功后会持久化一个异步本体治理任务。任务先执行确定性覆盖分析与脱敏聚合统计，再按表分片调用模型；无 Key 时保留确定性结果并标记为 `PARTIAL`。任务轮询、锁超时、重试、分片和统计预算分别通过 `BEMODEL_ONTOLOGY_ANALYSIS_*`、`BEMODEL_ONTOLOGY_STATS_*` 配置。候选映射默认 `confirmed=0`，不会进入正式问数白名单；所有建议均需 ADMIN/EDITOR 审核。

治理模型请求独立使用 `BEMODEL_ONTOLOGY_ANALYSIS_TIMEOUT_SECONDS`，默认 120 秒（允许 1–240 秒），不改变普通模型调用的超时。任务锁超时应大于单次模型请求超时。可在 Python 目录执行 `.venv\Scripts\python.exe scripts/probe_ontology_ai.py --tables 8`，使用当前模型配置和临时内存数据库验证真实调用；附加 `--workflow` 验证任务执行和变更集保存（跳过物理数据库统计）。该命令会产生模型调用费用，不访问业务数据库。

## 验证

不依赖 MySQL 的测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

独立 Docker 测试环境（从仓库根目录执行）：

```powershell
$env:BEMODEL_TEST_MYSQL_PORT='13317'
docker compose -p bemodel-python-candidate -f bemodel-server-py/compose.test.yml up -d --wait
$env:MYSQL_HOST='127.0.0.1'
$env:MYSQL_PORT='13317'
$env:MYSQL_USERNAME='root'
$env:MYSQL_PASSWORD='bemodel-isolated-test-only'
$env:MYSQL_DATABASE='bemodel_py_test'
$env:DEEPSEEK_API_KEY=''
$env:BEMODEL_DISABLE_SCHEDULER='1'
.\bemodel-server-py\.venv\Scripts\python.exe bemodel-server-py/scripts/bootstrap_test_db.py
$env:BEMODEL_MYSQL_TESTS='1'
.\bemodel-server-py\.venv\Scripts\python.exe -m pytest bemodel-server-py/tests -q
```

测试端口被脚本和 fixture 显式限制，避免写入业务库。MySQL 使用 tmpfs，容器销毁后测试数据不保留。集成测试会更新诊断、质控、治理、指标和通知等测试记录；合成退费工单与退款申请在用例结束清理。

`artifacts/` 保存验收报告：

| 脚本                        | 核对内容                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `check_route_coverage.py` | 从 Java Controller 提取方法、路径，对比 FastAPI 路由                                                          |
| `check_seed_parity.py`    | 独立 Java / Python MySQL 的全部演示表逐行比较；新鲜 Java 基线可通过`BEMODEL_BASELINE_MYSQL_PORT=13318` 指定 |
| `check_flow_parity.py`    | 住院、门诊闭环和人员下钻的 71 项原始响应比较                                                                  |
| `replay_diff.py`          | Java 18080 / Python 18081 的 API 场景深比较                                                                   |
| `check_rca_cs_parity.py`  | 根因分析七步证据、报告和 JWT 双向验证                                                                         |
| `crypto_interop_check.py` | 调用原 Java 编译类，与 Python 双向 AES-GCM 解密                                                               |
| `replay_writes.py`        | 代表性创建、更新、删除、非法参数和鉴权错误路径                                                                |
| `check_rdf_owl_parity.py` | 全部住院患者 TTL、SHACL 和 Turtle/RDFXML 导入预览                                                             |
| `check_initial_state.py`  | 新鲜 Java / Python 初始化后的平台、演示和 Flyway 表全量对账                                                   |
| `check_flyway_interop.py` | 在全新 13318 测试库中由原生 Java Flyway 初始化，Python 接管，再由 Java 校验                                   |

Java 基线必须连接 13316 的独立测试库，Python 连接 13317；两端均关闭外部 LLM，保持相同起始数据。回放报告列出归一化字段，时间和运行耗时不能作为业务差异；SHACL 违例应按集合比较。加密核验脚本依赖本工作区 Java 构建产物和测试 Maven 缓存，仅用于开发验收。

### 本次验收结果

验收使用 Docker 临时 MySQL，没有使用业务库。报告是对应隔离基线运行时的记录；执行会写入数据的测试后，不能直接假定两端仍处于相同初始状态。

| 项目                   | 结果                                                                 | 报告                                                                          |
| ---------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| API 方法和路径         | Java / Python 各 116，缺失 0、额外 0                                 | `artifacts/routes.json`                                                     |
| Python 测试            | 131 通过，0 失败、0 跳过                                             | `artifacts/pytest.xml`                                                      |
| 原 Java 测试           | 11 类、47 通过，0 失败、0 跳过                                       | `artifacts/validation-summary.json`、`artifacts/java-tests.log`           |
| API 读取及业务场景回放 | 180 场景，归一化后 0 差异                                            | `artifacts/replay-diff.json`                                                |
| 写入及错误路径回放     | 41 场景，归一化后 0 差异                                             | `artifacts/write-replay.json`                                               |
| 住院、门诊及人员闭环   | 71 场景，0 差异                                                      | `artifacts/flow-parity.json`                                                |
| RDF / SHACL / OWL      | 84 场景，按下述引擎标识例外核对后 0 差异                             | `artifacts/rdf-owl-parity.json`                                             |
| 初始数据               | 75 张表对账通过；其中 42 张演示表共 2268 行                          | `artifacts/initial-state-parity.json`、`artifacts/seed-parity.json`       |
| Flyway 互认            | Java 初始化 28，Python 接管执行 0，Java 再执行 0                     | `artifacts/flyway-interop.json`                                             |
| AES-GCM / JWT / RCA    | 18 次双向解密通过；JWT 双向验证、RCA 七步证据比对通过                | `artifacts/crypto-interop.json`、`artifacts/rca-cs-parity.json`           |
| 原 Vue 前端            | `npm run build` 通过；登录、架构、住院闭环、客服问答浏览器冒烟通过 | `artifacts/validation-summary.json`、`../output/playwright/python-cs.png` |

已构建 wheel：`artifacts/dist/bemodel_server-1.0.0-py3-none-any.whl`，包含 28 个 SQL、种子 JSON 和 SHACL 资源。浏览器验收期间控制台无错误，存在原前端 Element Plus 弃用提示；冒烟测试不等同于穷尽所有界面交互。本次未调用真实 DeepSeek 服务，双端回放验证的是无 Key 降级路径。

补充验证覆盖网关请求体、超时、HTTP 错误、无效 JSON、Jackson `asText(null)` 响应转换和无 Key 禁止发送请求；HTTP 采用受控替身，不代表真实 DeepSeek 服务验收。调度测试验证 Spring 星期编号和默认半小时表达式，并实际启动每秒 cron，确认首次巡检异常后下一周期继续执行且关闭数据库会话。

鉴权复查修正普通 OPTIONS 请求误放行、`/api` 根路径规则、异常角色类型导致的错误响应，以及 HMAC 验签密钥长度限制。正常 CORS 预检继续放行。`scripts/check_jwt_key_parity.py` 调用原 Java `JwtService`，验证 32/48/64 字节密钥与 HS256/384/512 的 9 种组合，全部与 Python 一致；报告为 `artifacts/jwt-key-parity.json`。在 Windows 执行此脚本需配置 Java 21 的 `JAVA_HOME`，并保留 Java 编译产物及 `.m2-test`。

## 兼容细节

- MyBatis 非空更新语义、自动生成 ID、响应中的空字段和分页 `[1, 200]` 均保留。
- 退费处置只将平台表纳入事务；演示收费库每条写入独立提交，与 Java 一致。已有测试注入平台写入失败，核对两侧不同的回滚结果。
- 固定演示场景以 JSON 资源保存，由 Python 原生加载。数据资源来自隔离 Java 基线，不包含平台账号、连接口令或审计日志；脚本记录源 `DataSeeder.java` 的 SHA-256。
- 迁移方案中 Flyway 校验和描述有误：实际 Flyway 10.10 按去除换行符后的各行累计 CRC32，保留空格、去除起始 BOM。本实现按实际 Java 行为验证，而非方案中的滚动哈希公式。
- Java 字符串哈希按 UTF-16 单元计算，`"abc".hashCode()` 为 `96354`。
- SQL 查询结果直接作为 JSON 返回与转为业务说明字符串是不同路径；Java `LocalDateTime.toString()` 省略零秒的规则已对齐。
- SHACL 实际运行引擎为 pySHACL，响应 `engine` 据实返回 `pySHACL`；Java 返回 `Apache Jena SHACL 5.2.0`。该实现标识是明确的元数据差异，违例内容、路径、严重性和数量另行核对。
- 框架异常消息保留 `系统异常: ` 前缀，内部诊断文本随 Spring/FastAPI 改变；业务异常文案按源代码实现。

`scripts/generate_models.py`、`extract_cs_prompts.py`、`extract_value_presentations.py` 为开发期迁移工具；运行服务时不读取 Java 源码。
