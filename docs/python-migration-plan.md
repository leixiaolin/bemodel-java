# BeModel 后端 Java → Python 全量对等改写方案

> 版本：v1.0（2026-09-16）
> 源项目：`d:\cc_workspace\bemodel-java-main\bemodel-server`
> 目标项目：`d:\cc_workspace\bemodel-python-main`（新建）

## 1. 目标与约束

- **源**：Java 21 + Spring Boot 3.3.4，147 个主源码文件 / 11,359 行，30 个 Controller，11 个测试类
- **目标**：新建 `d:\cc_workspace\bemodel-python-main`，FastAPI + SQLAlchemy 2.0 全量对等改写
- **前端 bemodel-web（Vue 3）不动**，要求 API 与 MySQL 表结构 **100% 兼容**（前端零改动）
- **Flyway 28 个 SQL 直接复用**（拷贝禁改）；`shacl/clinical-shapes.ttl` 原样拷贝禁改

## 2. 技术栈映射

| Java | Python | 备注 |
|---|---|---|
| Spring Boot Web | FastAPI ~0.115 + uvicorn | 端点用同步 `def`（对位阻塞 JDBC） |
| MyBatis-Plus BaseMapper/ServiceImpl | SQLAlchemy 2.0 + 自研泛型 `BaseDAO` | 见 §6 难点对策 |
| Flyway | 自研迁移执行器 ~150 行 | 复用 V1~V28，兼容 flyway_schema_history（精确复刻 Flyway LineChecksum） |
| Spring Security + JJWT | PyJWT 2.9 + bcrypt + ASGI 中间件 | HS256/TTL 12h/claims 逐字对齐 |
| Apache Jena ARQ/SHACL | rdflib 7.1 + pyshacl 0.28 | pyshacl 必须 `advanced=True` |
| AES-GCM CryptoService | cryptography 43.0 | 密文互通，见 §4 契约 |
| @Scheduled | APScheduler 3.10（3.x，不用 4.x） | 六字段 cron 解析 |
| ApplicationRunner | FastAPI lifespan 启动钩子 | 顺序：迁移→密钥迁移→种子→调度器 |
| @Transactional | `transactional()` 上下文管理器 | 全项目仅 4 处，边界精确对位 |
| DeepSeekClient（http） | httpx | 无 Key 全链路降级语义保留 |

依赖（pyproject.toml）：python≥3.12、fastapi、uvicorn[standard]、sqlalchemy~2.0.36、pymysql、cryptography、PyJWT、bcrypt（不用 passlib）、pydantic-settings、rdflib、pyshacl、httpx、APScheduler<4、python-multipart、pytest。

## 3. 目录结构（src layout，Python 包 = Java 包同名）

```
d:\cc_workspace\bemodel-python-main\
├── pyproject.toml / .env.example / README.md
├── scripts\{replay_diff.py, crypto_interop_check.py}
├── src\bemodel\
│   ├── main.py（=BeModelApplication，lifespan）
│   ├── config.py（=application.yml，pydantic-settings）
│   ├── core\  # =common 包 + 基础设施
│   │   ├── result.py（Result）/ page_result.py / exceptions.py / handlers.py
│   │   ├── crypto_service.py / state_machine.py / java_compat.py
│   │   ├── database.py / base_dao.py / dynamic_ds.py
│   │   ├── migration.py（Flyway 执行器）/ security.py / cors.py / scheduler.py
│   ├── db\migration\V1~V28.sql（原样拷贝）
│   ├── resources\shacl\clinical-shapes.ttl（原样拷贝）
│   ├── auth\ ontology\ modeling\ rdf\ datasource\ instance\ value\
│   ├── governance\ clinical\ rca\ link\ flow\ cs\ search\ notice\
│   ├── llm\ architecture\ impact\ seed\
│   └── （各包内：entities.py / daos.py / services\ / router.py）
└── tests\  # 11 个测试模块与 Java 11 测试类一一对应 + conftest.py
```

Java 包 → Python 包对应：common→core（Result/PageResult/BizException/GlobalExceptionHandler/CryptoService/StateMachine 五件套 + 新增基础设施）；config→core.cors；auth 包中 SecurityConfig+JwtAuthFilter 合并为 core.security，其余照搬；其余 20 个业务包同名保留。实体模型属性 snake_case 但显式声明 MySQL 列名，对外 JSON 统一 `to_camel_dict()` 转 camelCase。

## 4. 关键兼容性契约（已核实源码，必须逐条对齐）

- **统一响应**：字段名是 **`msg`**（非 message）；成功 `{code:0,msg:"ok",data}`；BizException → **HTTP 200 + {code:500,msg}**；401/403 → HTTP 401/403 + `{"code":401/403,"msg":"未登录或已过期"/"权限不足"}`
- **全局异常**（已核实 GlobalExceptionHandler.java 仅 2 个 handler）：BizException → 200+code500；**Exception 兜底捕获一切（含请求体解析/校验失败）→ 200 + {"code":500,"msg":"系统异常: ..."}**。Python 的 RequestValidationError 同样映射为 HTTP 200 + code 500（完全对等）
- **JSON 序列化**：键 camelCase（`to_camel_dict()` 单点收口）；**None 字段输出 null**；`LocalDateTime` → `yyyy-MM-ddTHH:mm:ss` ISO 格式（application.yml 的 `jackson.date-format` 只作用于 java.util.Date，不影响 JSR310）——移植时逐实体确认字段类型，若混有 Date 类型字段则该字段输出 `yyyy-MM-dd HH:mm:ss`（带空格）
- **AES-GCM 互通**（已核实 CryptoService.java）：`ENC: + Base64(iv[12] ‖ ciphertext‖tag[16])`；密钥 = `SHA-256(口令)` 32B；dev key 常量 `"bemodel-dev-app-secret-do-not-use-in-prod"`；Python `AESGCM.encrypt` 输出布局天然一致；无前缀明文原样返回
- **JWT**（已核实 JwtService.java）：HS256、TTL 12h、claims `{sub, role, displayName(null→""), iat, exp}`；**dev secret 常量 `"bemodel-dev-jwt-secret-do-not-use-in-prod"`**（双端互验 token 依赖同一 secret）；secret 配置时校验 ≥32 字节（对位 hmacShaKeyFor WeakKeyException）；种子口令哈希 `$2b$` BCrypt（bcrypt 库原生可验）
- **自动建库**：Java 连接串 `createDatabaseIfNotExist=true` → Python 迁移执行器先以无库方式连接 CREATE DATABASE IF NOT EXISTS，再进库跑迁移；连接参数补 `charset=utf8mb4` + 会话时区 `SET time_zone='+08:00'`（对位 serverTimezone=Asia/Shanghai；DATETIME+LocalDateTime 无时区语义，默认行为一致）
- **安全规则链（first-match，顺序不可调换，已核实 SecurityConfig.java）**：
  1. `/api/auth/login` 放行
  2. OPTIONS 预检放行
  3. `POST /api/cs/ask、/api/search、/api/cs/feedback` → 三角色皆可
  4. `GET /api/cs/feedback/list` → 仅 ADMIN/EDITOR
  5. `GET /api/**` → 三角色皆可
  6. 其余 `/api/**`（写操作）→ ADMIN/EDITOR
  7. 非 `/api/**` → 放行
- **`String.hashCode()` 精确复刻**（`h=(31*h+ord)&0xFFFFFFFF` 后按 int32 处理再 `format(h,'08X')`）：OwlImportService 的 `OWL_%08X`/`AX-IMP-%08X` 兜底码依赖它
- **事务边界**：仅 4 处 @Transactional（ReleaseService.publish、OwlImport.execute、CsService.refundAction、SchemaScanService）；**refundAction 中 demo 库写入不在事务内**（只有平台库回滚）——勿把两个 engine 包进一个事务
- **MyBatis-Plus 隐性行为**：updateById 只更新非 null 字段；selectOne 隐含 LIMIT 1；插入回填自增 id
- **upsert**：MissMapper 的 `ON DUPLICATE KEY UPDATE` → `sqlalchemy.dialects.mysql.insert().on_duplicate_key_update()`
- **DataSeeder**：无随机数、确定性、幂等（40 患者、预埋 LIS v5.2 撤销码 X→C 故障 5 笔未退费）
- **404 对齐**：Java 未知 `/api/*` 路径返回 HTTP 404 + Spring 默认 error JSON（`{timestamp,status,error,path}`）；FastAPI 默认 `{"detail":"Not Found"}` → 自定义 404 handler 对齐 Spring 形态
- **multipart 上传限制 10MB**（已核实 application.yml）→ OWL 导入端点显式检查
- **多数据源**：`dict[str,Engine]`+Lock 双检锁；**NullPool**（对位 DriverManagerDataSource 无池）；密码 AES 解密后建连

## 5. 分阶段实施步骤（每阶段含验证）

- [ ] **S-pre 方案文档落盘**：本方案保存为项目文档，作为实施依据与团队评审材料
- [ ] **S0 脚手架**（~12 文件）：pyproject、config、main 骨架、CORS、Flyway 迁移执行器、拷贝 28 SQL + shapes.ttl。验证：空库跑迁移，与 Java 初始化库 mysqldump 结构 diff 一致
- [ ] **S1 core**（~12 文件）：result/page_result/exceptions/handlers/crypto/state_machine/java_compat/base_dao/dynamic_ds。验证：AES 互通向量单测、java_string_hash 已知值（"abc"=126145）、camel 转换、状态机全路径
- [ ] **S2 auth**（~7 文件）：models/dao/jwt_service/service/router + security 中间件。验证：与 Java 并启 diff login/me/无 token/伪 token/越权（401/403 正文+状态码）
- [ ] **S3 ontology**（~26 文件）：8 entity、11 dao、9 service、11 router。验证：端点 diff；移植 ConceptServiceTest/MetricMonitorTest
- [ ] **S4 modeling**（~12 文件）：Rule/Axiom/Action/Release + publish 事务 + BFS 闭包（MAX_DEPTH=12）。验证：BLOCKER 拒绝/force、closure diff；移植 ModelingElementsTest
- [ ] **S5 rdf**（~6 文件）：OwlImport（rdflib）、RdfService（**手拼 TTL 字符串**，不用 rdflib 序列化器）、ShaclService（pyshacl advanced=True）。验证：黄金文件双端 diff、SHACL 6 Shape 对预埋故障患者违例数一致
- [ ] **S6 datasource/instance/value**（~14 文件）：Datasource/SchemaScan/Mapping（aiSuggest 降级链）/Instance/Value。验证：CRUD diff、schema scan 对账、instance 反查 diff
- [ ] **S7 seed**（~4 文件）：DataSeeder 逐段移植 + DatasourceSecretMigrator + lifespan 装配。验证：40 患者、5 笔未退费、幂等二次启动跳过、双端逐表 COUNT 对账
- [ ] **S8 治理/临床/RCA/链路/闭环**（~26 文件）：governance/clinical/rca(P1-P7)/link(BFS)/flow。验证：scan 质量分 diff、QC 违例 diff、RCA 结论 diff；移植 GovServiceTest/RcaEngineTest 等
- [ ] **S9 cs/search/llm**（~12 文件）：CsService（意图路由+7 类处置+refundAction）、SemanticQaService（SQL 白名单+timeout 15s+maxRows 100）、SearchService（n-gram）、DeepSeekClient。验证：无 Key 降级路径 diff；移植 CsServiceTest/SemanticQaServiceTest
- [ ] **S10 notice**（~9 文件）：InspectScheduler(APScheduler)/InspectService/NoticeService（幂等告警）。验证：手动 /api/inspect/run diff、cron 触发
- [ ] **S11 architecture/impact**（~4 文件）：收尾。验证：端点 diff
- [ ] **S12 验收**（~6 文件）：replay_diff.py 全量回放（~150 条请求清单、双端 18080/18081、JSON 深比较、时间戳/token/耗时归一化）、11 测试类全绿、README/.env.example

合计 Python 源码/测试约 150 文件，与 Java 版 1:1。

## 6. 关键技术难点对策

- **BaseDAO**（core/base_dao.py）：泛型基类对等 BaseMapper+ServiceImpl——select_by_id/insert(回填id)/update_by_id(**只更新非 None 字段**：取出实体 setattr 后 flush，勿用 update() 全量 set)/select_list/select_one(limit 1)/select_count/page
- **LambdaQueryWrapper → SQLAlchemy 翻译约定**：`.eq→==`、`.ne→!=`、`.like→like(f"%{v}%")`、`.likeRight→like(f"{v}%")`、`.in→in_()`、`.isNull→is_(None)`、`.last("LIMIT 1")→.limit(1)`、`.orderByAsc/Desc→order_by(asc()/desc())`；查询条件在 DAO 内组装为 `list[ColumnElement]` 再 `where(*conds)`，保持 Java 版条件组合顺序
- **Jena→rdflib 三条管线**：
  - OWL 导入：`Graph().parse(format="turtle"/"xml")`；遍历 `OWL.Class∪RDFS.Class` 按 URI 排序（对位 TreeSet）；`isinstance(BNode)` 对位 `isAnon()`；upperSnake 四段正则逐条翻译（`$1_$2`→`\1_\2`）；rdfs:label 语言偏好、XSD 类型映射表逐行对齐
  - TTL 导出：**手拼字符串逐字符对齐**（Java 版是 StringBuilder 手拼，含注释头/时间戳/前缀块），不用 rdflib 序列化器；maskName 脱敏三分支照抄
  - SHACL：shapes 图模块级懒加载+`threading.Lock`（对位 volatile+synchronized）；`pyshacl.validate(..., advanced=True)`——**advanced 未开会静默跳过 5/6 个 SPARQL Shape**（防回归测试必须覆盖）；结果映射 sh:focusNode/resultPath/resultMessage，severity 固定 "Violation"；降级预案：手工提取 sh:sparql 的 SELECT，`$this`→initBindings 逐实例执行
- **迁移执行器**：兼容 Flyway 历史表结构（installed_rank/version/description/type/script/checksum/...）；**精确复刻 Flyway LineChecksum 算法**（CRLF→LF 归一后逐行 trim 取 CRC-32，再 `(31*result+lineCrc)|0` int32 滚动合并——不是整文件 CRC-32）；门禁测试：Java 初始化的库上 Python 启动应识别全部 28 条历史记录 0 执行，反向亦然；引号感知语句拆分（已核实 28 脚本无 DELIMITER/存储过程）；`${demo_db_username/password}` 占位符替换；先自动建平台库再进库执行
- **APScheduler**：六字段 cron `"0 0/30 * * * *"` → `CronTrigger(second=0, minute="0/30")`（自写六字段解析：秒 分 时 日 月 周）；任务体 try/except 吞异常打日志；`BEMODEL_DISABLE_SCHEDULER=1` 供测试
- **启动钩子顺序**（main.py lifespan）：1. run_migrations → 2. DatasourceSecretMigrator（对位 @Order(0)）→ 3. DataSeeder（幂等）→ 4. scheduler.start()
- **编码规范**（Java→Python 惯用法）：record→`@dataclass(frozen=True)`、Optional→`| None`+is None、Stream→推导式/sum()/sorted、groupingBy→defaultdict(list)、BigDecimal→Decimal（金额）、Map.of/LinkedHashMap→dict 字面量（保序）、switch→match/dict 分派、LocalDateTime.now()→datetime.now()（naive）、computeIfAbsent→双检锁或 setdefault

## 7. 测试方案

- Java 11 个 `@SpringBootTest` → pytest 11 个同名模块（test_concept_service / test_metric_monitor / test_modeling_elements / test_clinical_semantic / test_gov_service / test_rca_engine / test_rdf_service / test_flow_service / test_opd_flow / test_cs_service / test_semantic_qa_service），断言逐条移植（同一期望值）
- conftest 设计：session 级 `app_client`（TestClient with 进入触发 lifespan：迁移→密钥迁移→种子→禁用调度器，等价 @SpringBootTest 完整上下文）；测试直连 service 层（同构 Java @Autowired）；强制测试库 `BEMODEL_TEST_DB`、DEEPSEEK_API_KEY 置空走降级路径
- pytest.ini `markers = integration`，无 MySQL 环境可 `-m "not integration"` 跳过

## 8. 风险与规避

| # | 风险 | 规避 |
|---|---|---|
| 1 | AES 密文互通（布局/密钥派生不一致） | 布局已核实一致；S1 即跑 crypto_interop_check.py（Python 解 Java 存量密文行 + 反向）作为门禁 |
| 2 | pyshacl 静默跳过 SPARQL 约束 | `advanced=True` + 预埋患者违例数防回归测试 + 手工 SPARQL 降级路径 |
| 3 | Jena/rdflib 解析差异（localName/匿名节点/RDF/XML 容错） | 黄金文件测试锁定（双端对同一 .owl/.ttl preview diff）；异种 IRI 记录为已知偏差 |
| 4 | 响应壳漂移导致前端隐性故障 | to_camel_dict 单点收口 + 每阶段双端 diff 验收 |
| 5 | MyBatis-Plus 隐性行为（updateById 忽略 null 等） | BaseDAO 集中实现 + 专项单测 |
| 6 | 事务边界错位（demo 库写入裹进平台库事务） | refundAction 专项测试：charge 写入失败→平台库回滚但 charge 已写入 |
| 7 | 安全链顺序错误 | 规则链固化为数据驱动列表 + 参数化测试每条正反用例 |
| 8 | `String.hashCode` 未复刻致 OWL 导入码不一致 | java_compat 单测已知向量（"abc"=126145） |
| 9 | 金额浮点误差 | 强制 Decimal；diff 覆盖 refund/flow 金额字段 |
| 10 | LLM 输出不确定无法 diff | 无 Key 降级路径全量 diff（确定性）；有 Key 路径仅验契约，提示词逐字对齐 |
| 11 | Flyway checksum 不兼容致双栈互认失败 | 精确复刻 LineChecksum；门禁测试双向 0 执行 |
| 12 | 错误文案差异（Spring 异常 message vs Python） | diff 归一化：错误类响应只比对 code+HTTP 状态码，msg 宽松匹配（前缀对齐"系统异常: "） |

## 9. 验收标准

1. **双端 diff 全绿**：`scripts/replay_diff.py` 回放 ~150 条请求（30 Controller 全 GET happy path + 代表性写路径 + 错误路径：不存在 code、非法流转、越权、无 token），Java(:18080) 与 Python(:18081) 的 HTTP 状态码 + JSON 深比较全等（归一化：token/时间戳/耗时毫秒/LLM 自由文本；violations 集合化）
2. **数据对账**：双端各自种子后，`bm_*` 平台表与 9 个 demo 库逐表 `COUNT(*)` + 主键抽样比对一致
3. **测试全绿**：pytest 11 个集成测试模块通过
4. **前端零改动**：bemodel-web 直连 Python 后端全功能可用

## 10. 关键参照文件（Java 侧权威基准）

- `bemodel-server\src\main\java\com\bemodel\auth\SecurityConfig.java` — 安全规则链顺序与 401/403 JSON 形态（已验证）
- `bemodel-server\src\main\java\com\bemodel\auth\JwtService.java` — JWT claims/TTL/dev secret（已验证）
- `bemodel-server\src\main\java\com\bemodel\common\CryptoService.java` — AES-GCM 密文契约（已验证）
- `bemodel-server\src\main\java\com\bemodel\common\Result.java` — 响应壳 `msg` 键名（已验证）
- `bemodel-server\src\main\java\com\bemodel\common\GlobalExceptionHandler.java` — 兜底异常→200+code500（已验证）
- `bemodel-server\src\main\java\com\bemodel\common\PageResult.java` — 分页归一化 [1,200]（已验证）
- `bemodel-server\src\main\java\com\bemodel\modeling\service\ReleaseService.java` — 事务+闭包 BFS 算法基准
- `bemodel-server\src\main\java\com\bemodel\ontology\service\OwlImportService.java` — hashCode 兜底码/命名转换/disposition 全细节
- `bemodel-server\src\main\java\com\bemodel\seed\DataSeeder.java` — 确定性种子数据（1025 行）
- `bemodel-server\src\main\resources\application.yml` — 配置基线（已验证：端口 18080/multipart 10MB/cron）
- `bemodel-server\src\main\resources\db\migration\V1~V28` — 原样拷贝禁改
- `bemodel-server\src\main\resources\shacl\clinical-shapes.ttl` — 原样拷贝禁改
