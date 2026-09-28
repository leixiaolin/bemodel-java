# 功能验收（2026-09-18）

范围为原 Java 后端及迁移方案中的 116 个 API。目标目录按用户要求为 `bemodel-server-py`，Java/Vue 源码保持不变。

## 计量方式与结论

路由存在、两端同时报错或单元测试数量均不算功能成功。`scripts/full_acceptance.py` 在隔离 Java/Python 实例执行 **146 次业务请求**，要求 HTTP 200、业务 `code=0` 并深比较结果。每个接口至少有一次成功且一致的请求才计入覆盖；静态路径优先匹配，避免 `/release/current` 被误计为 `/release/{id}`。

- **116/116 接口成功覆盖（100%），未覆盖 0，失败场景 0。** SHACL 引擎标识有下述例外；若将整项接口从严格响应对等数中扣除，仍为 **115/116（99.14%）**，超过 98% 门槛。
- **Python 131 项测试通过，0 失败、0 跳过**（2026-09-19 更新）；包含原 11 个 Java 测试类对应模块。原 Java 测试为 11 类、47 项通过。
- **操作后的 75 张表数据及结构一致**：比较全部行、主键、状态、金额和关联，以及 `SHOW CREATE TABLE`；仅归一化明确的运行时差异。
- **71 项住院/门诊/人员闭环、84 项 RDF/SHACL/OWL 复验通过**，均使用本轮独立双端环境。
- 退款流程实际生成 **5 笔、合计 205 元**的申请及处置节点，两端落库相同。另有故障注入测试，验证平台事务回滚、演示收费库独立提交的原 Java 行为。

这是既定功能清单的验收结论，不表示穷尽任意输入组合或真实外部服务故障。

## 方案逐项证据

| 方案项 | 验证内容 | 证据 |
| --- | --- | --- |
| S0 脚手架/迁移 | 服务启动、28 SQL 和 SHACL 原样、75 表结构 | `tests/test_core.py`、`artifacts/acceptance-state.json` |
| S1 基础能力 | 非空更新、事务、状态机、序列化、UTF-16 hash、AES 互通 | `tests/test_core.py`、`artifacts/crypto-interop.json` |
| S2 鉴权 | 登录、三角色、401/403、预检、9 种 HMAC 密钥/算法组合 | `tests/test_auth.py`、`artifacts/jwt-key-parity.json` |
| S3 本体 | 概念/属性/关系/继承/术语/指标/公理/互斥，缺口采纳与撤销 | `artifacts/full-acceptance.json`、本体测试模块 |
| S4 建模/发布 | 规则/动作生命周期、发布/快照、阻断/强制发布、闭包 | `artifacts/full-acceptance.json`、`tests/test_modeling_elements.py` |
| S5 RDF/OWL | 全住院患者 TTL/SHACL、两种 OWL 格式及导入执行 | `artifacts/rdf-owl-parity.json`、RDF/OWL 测试模块 |
| S6 数据源/实例/价值 | 实际连接成功、扫描、映射、实例投影、价值实证 | `artifacts/full-acceptance.json`、`artifacts/acceptance-state.json` |
| S7 种子/密钥迁移 | 42 演示表 2268 行、二次启动幂等、Flyway 互认 | `artifacts/seed-parity.json`、`artifacts/flyway-interop.json` |
| S8 治理/临床/RCA/链路/闭环 | 治理扫描/工单/解决、临床规则、七步 RCA、链路追溯、全部患者闭环 | `artifacts/full-acceptance.json`、`artifacts/flow-parity.json`、对应测试模块 |
| S9 客服/搜索/LLM | 七类问答、反馈、诊断、退费；真实 MySQL 执行规划 SQL、100 行限制/20 行展示、非法 SQL 拦截 | `artifacts/full-acceptance.json`、客服/语义/网关测试模块 |
| S10 通知/巡检 | 手动巡检、已读、幂等告警；真实 cron 首次失败后再次执行 | `artifacts/full-acceptance.json`、`tests/test_scheduler.py` |
| S11 架构/影响 | 总览、变更影响 BFS | `artifacts/full-acceptance.json` |
| S12 交付/前端 | wheel 含运行资源、Vue 构建、登录/架构/住院闭环/客服浏览器冒烟 | `artifacts/dist/`、`artifacts/validation-summary.json`、`../output/playwright/python-cs.png` |

## 已知例外与归一化

2026-09-19 跨域补充验收：新增 `core/cors.py`，按原 Java 仅对 `/api/**` 配置跨域；精确回显请求来源、方法和请求头，同源预检不附加跨域许可头，非 API 跨域预检返回 403。跨域包装置于全局异常处理中间件之外，保证未知异常响应可被浏览器读取。`scripts/check_cors_parity.py` 实测原 Java 与当前 Python ASGI 的 12 组请求，状态、正文和 CORS 头全部一致；另有 11 项 CORS 回归测试。报告：`artifacts/cors-parity.json`。

1. SHACL `engine` 据实为 `pySHACL`，Java 为 `Apache Jena SHACL 5.2.0`；违例数量、路径、消息、严重性和集合单独严格比较。
2. 框架内部诊断后缀不同；错误按 HTTP 状态、业务码及 `系统异常: ` 前缀比较。业务异常文案保持对等。
3. 排除运行时间戳、耗时、JWT 字节、RCA 编号中的生成时间、隔离端口和随机密文；JWT/AES 另有互通验证。生成工单的完整列表按业务编号比较集合，普通分页仍比较顺序。
4. 数据库 JSON 的 `80.0` 和 `80` 按相同数值比较，字段顺序不影响结果。实际金额、业务主键和数量未忽略。
5. **未调用真实 DeepSeek 服务**：网关 HTTP 契约/错误使用受控替身，模型规划分支连接真实临时 MySQL。前端执行关键流程冒烟，未穷尽每一种界面交互。

## 复验

专用 Docker Compose 项目为 `bemodel-accept-13319`、`bemodel-accept-13320`，端口分别 13319/13320，平台库均为 `bemodel_acceptance`。Java 18083 / Python 18084。此前 13316/13317/13318 环境保留，没有读取或改写业务库。

先用 `compose.test.yml` 创建两个全新容器，设置对应 `MYSQL_PORT`、`MYSQL_HOST=127.0.0.1`、`MYSQL_DATABASE=bemodel_acceptance` 和临时账号，执行 `scripts/bootstrap_acceptance.py`。它只初始化迁移并调整演示源端口；随后分别启动 Java/Python，由各自执行种子。Java 的 `SPRING_DATASOURCE_URL` 必须指向 13319，Python 指向 13320；关闭巡检、清空 `DEEPSEEK_API_KEY`。

在全新、起点一致的双端执行：

```powershell
./bemodel-server-py/.venv/Scripts/python.exe bemodel-server-py/scripts/full_acceptance.py
./bemodel-server-py/.venv/Scripts/python.exe bemodel-server-py/scripts/check_acceptance_state.py
```

该流程会创建发布、映射、工单及退款，不能用于业务库，也不能把执行后的库当作初始状态再次回放。`full_acceptance.py --recompare` 只根据保留的原始响应重算差异；本轮用它规范化关系备注中的 RCA 生成时间，原始响应完整保留。

设置 `BEMODEL_JAVA_URL=http://127.0.0.1:18083`、`BEMODEL_PYTHON_URL=http://127.0.0.1:18084` 可执行 RDF 专项。闭环脚本还需将 Python 数据库设为 13320 的 `bemodel_acceptance`。
