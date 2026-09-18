# BeModel Python 后端

按照 `../docs/python-migration-plan.md` 将 Java 后端改写为 FastAPI + SQLAlchemy。前端和 Java 源码保持不变；Python 服务运行时不依赖 JVM。116 个 API 的方法、路径、鉴权规则和 MySQL 表结构与源项目对应。

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

启动依次执行：原始 SQL 迁移 → 数据源密文迁移 → 演示种子及结构化公理 → 指标巡检调度。28 个 SQL 和 SHACL 文件逐字节复用。已有兼容的 Flyway 历史记录不会重复执行。演示数据保留原 Java 的新鲜度判断：不足时重建演示场景，因此验收必须使用独立测试库。

`MYSQL_USERNAME`、`MYSQL_PASSWORD` 也用于原始 SQL 的演示数据源占位符。原始脚本将演示源登记为本机 3306；非默认端口的测试环境由 `scripts/bootstrap_test_db.py` 单独调整登记端口，未修改迁移文件。跨主机部署需在数据源管理中配置相应连接。

`JWT_SECRET`、`APP_SECRET_KEY` 缺省时沿用 Java 的开发默认值；连接已有库时必须与原服务一致。`DEEPSEEK_API_KEY` 为空时使用原有降级路径。`BEMODEL_DISABLE_SCHEDULER=1` 可关闭定时巡检；`BEMODEL_INSPECT_CRON` 使用含秒的六字段表达式。

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

| 脚本                        | 核对内容                                             |
| --------------------------- | ---------------------------------------------------- |
| `check_route_coverage.py` | 从 Java Controller 提取方法、路径，对比 FastAPI 路由 |
| `check_seed_parity.py`    | 13316 / 13317 两个独立 MySQL 的全部演示表逐行比较    |
| `check_flow_parity.py`    | 住院、门诊闭环和人员下钻的 71 项原始响应比较         |
| `replay_diff.py`          | Java 18080 / Python 18081 的 API 场景深比较          |
| `check_rca_cs_parity.py`  | 根因分析七步证据、报告和 JWT 双向验证                |
| `crypto_interop_check.py` | 调用原 Java 编译类，与 Python 双向 AES-GCM 解密      |

Java 基线必须连接 13316 的独立测试库，Python 连接 13317；两端均关闭外部 LLM，保持相同起始数据。回放报告列出归一化字段，时间和运行耗时不能作为业务差异；SHACL 违例应按集合比较。加密核验脚本依赖本工作区 Java 构建产物和测试 Maven 缓存，仅用于开发验收。

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
