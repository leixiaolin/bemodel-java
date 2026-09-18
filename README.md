# BeModel 本体建模平台

> 一句话定位：把医院九套业务系统（HIS / LIS / PACS / EMR / 药房 / 收费 / 门诊 / 护士站 / 物资）的数据**不搬家、不复制**，通过「本体 + 映射」建成统一的语义层，让规则引擎和 AI 都能直接基于业务语义工作。

BeModel 是一个语义层（Semantic Layer）平台：数据留在各业务库里，平台只维护「概念 → 属性 → 物理表列」的映射与值字典，在此之上提供本体建模、版本化发布、规则/指标口径管理、链路追溯、病案质控、根因分析、AI 客服与智能问数等能力，并内置认证授权与密钥加密。

设计哲学：**物理自治、逻辑统一**——避开数据搬迁和图数据库的成本，语义层随使用持续生长。

## V0.1.2 更新亮点

相对 [release-V0.1.1](../../tree/release-V0.1.1) 的主要变化：

- **认证授权落地**：Spring Security + JWT 登录（ADMIN / EDITOR / VIEWER 三角色），关闭匿名写操作，前端路由守卫与登录页；只读角色也可使用问答与搜索
- **密钥治理**：数据源密码 AES-GCM 加密落库（`ENC:` 前缀密文），RDF 导出自动脱敏，JWT / 加密密钥走环境变量
- **SHACL 双引擎真互证**：引入 Apache Jena SHACL，发布前规则引擎与 SHACL 引擎对同一本体真跑校验；传递闭包发布物化、多父继承（is_primary）、影响分析多跳
- **AI 客服 × 智能问数场景分叉**：同一语义引擎按 `scene=CS|ANALYTICS` 分流路由，显式 REFERRAL 互转，解析过程可解释
- **智能问数口径卡**：指标名直命中时结构化展示口径定义 / 计算公式 / 探针 SQL / 巡检实测值
- **指标定时巡检 + 平台内告警中心**：巡检结果落库、异常生成通知，客服路由反馈回路（错例回流 prompt）
- **概念缺口 / 语义漂移独立页**：本体未覆盖说法按热度生长、术语分叉与口径演进检测
- **前端 v2**：设计令牌层 + 导航分组布局、架构全貌双视图（实体全景 / 分层架构）、规则双模态（可视化 / JSON 互转）、版本变更图谱

## 核心能力

- **架构全貌（双视图）**：「实体全景」铺出全部概念与映射关系；「分层架构」渲染业务应用 → 推理引擎 → 数据映射 → 本体四层，节点点击直达对应模块；顶部统计卡实时显示规模与**映射覆盖度**
- **本体建模**：业务域 → 概念 → 关系，公理（对称 / 传递 / 互逆 / 互斥）结构化存储，概念支持多父继承；OWL 导入（预览与落库同一计划）、Turtle ABox 导出（Apache Jena，含脱敏）
- **发布门禁（双引擎互证）**：一键打整体不可变快照；发布前自动跑本体自检（对称且反对称、互逆不成对、互斥自身等 7 类缺陷，BLOCKER 拒绝发布），并以 Apache Jena SHACL 真跑约束校验——矛盾的本体出不了门
- **数据源绑定与映射**：注册业务库连接（密码 AES-GCM 加密存储），扫描 information_schema 建物理快照；物理列 ↔ 概念属性逐列绑定（AI 推荐、人工确认），值字典归一
- **AI 客服（scene=CS）**：投诉 / 工单自动诊断与一键处置，缴费发药跨库核对，政策类问题模型作答；结构类「能不能」问题从本体结构推理作答 + 数据探针实证
- **智能问数（scene=ANALYTICS）**：事实问题走 **Ontology2SQL**——LLM 基于本体映射生成 SQL，白名单安全校验后真实执行，证据栏展示 SQL 与数据源；指标名直命中时返回**口径卡**（口径 / 公式 / 探针 SQL / 巡检实测值）
- **本体增长回路**：搜索未命中、映射失败、客服 / 问数答不了的说法自动汇入**概念缺口**，按热度排序，AI 归类建议 → 人工采纳 → 草稿 → 发布；**语义漂移**检测术语分叉与口径演进
- **指标巡检与告警**：指标定时巡检（cron 可配），实测值落库，异常进入平台内告警中心；客服错例反馈回流路由 prompt
- **治理与追溯**：病案内涵质控八类规则跨库执法；链路追溯双向 BFS 还原每笔异常的来龙去脉；影响分析支持多跳传播
- **LLM 合规链路**：统一 LLM 网关（DeepSeek），每次调用落审计表并绑定本体版本号；AI 不可用时自动降级为规则 / 模板，演示不断链

## 技术栈

| 端   | 技术                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------ |
| 后端 | Java 21 · Spring Boot 3.3 · Spring Security + JJWT · MyBatis-Plus · Flyway · Apache Jena（ARQ + SHACL） |
| 前端 | Vue 3 · Vite · Element Plus · ECharts · Pinia（设计令牌层 + 深色导航布局）                               |
| 存储 | MySQL（平台元数据库 + 各业务演示库）                                                                         |
| 安全 | JWT 认证（三角色）· 数据源密码 AES-GCM 加密 · SQL 白名单校验 · RDF 导出脱敏                               |
| AI   | DeepSeek（API Key 走环境变量，无 Key 全链路可降级演示）                                                      |

## 目录结构

```
bemodel-java
├── bemodel-server              # 后端（Spring Boot）
│   ├── pom.xml
│   └── src
│       ├── main
│       │   ├── java/com/bemodel
│       │   │   ├── BeModelApplication.java
│       │   │   ├── architecture/   # 架构全貌（实体全景 / 分层架构双视图、覆盖度统计）
│       │   │   ├── auth/           # 认证授权：登录、JWT 签发校验、Spring Security 三角色
│       │   │   ├── ontology/       # 本体层：业务域 / 概念 / 多父继承 / 指标 / 术语 / OWL 导入
│       │   │   ├── modeling/       # 规范层：规则 / 动作 / 公理结构化 / 版本发布与门禁
│       │   │   ├── datasource/     # 数据源注册（密码加密）、连接管理与 information_schema 扫描
│       │   │   ├── instance/       # 语义映射：概念属性 ↔ 物理表列、值字典
│       │   │   ├── link/           # 链路追溯（双向 BFS 还原异常链路）
│       │   │   ├── impact/         # 变更影响分析（多跳传播）
│       │   │   ├── governance/     # 数据治理扫描（GovRule / GovScan / GovIssue）
│       │   │   ├── clinical/       # 临床决策：病案内涵质控 + 危重症预警
│       │   │   ├── rca/            # 根因分析（RCA）与处置
│       │   │   ├── cs/             # AI 客服 + 智能问数：场景分叉路由 + 语义问答（Ontology2SQL）+ 口径卡
│       │   │   ├── search/         # 语义搜索
│       │   │   ├── notice/         # 平台内告警中心（巡检异常通知）
│       │   │   ├── value/          # 价值实证
│       │   │   ├── flow/           # 医嘱闭环演示（业务闭环）
│       │   │   ├── rdf/            # OWL / Turtle 导出（Apache Jena，导出脱敏）
│       │   │   ├── llm/            # LLM 网关：DeepSeek 客户端、审计日志
│       │   │   ├── common/         # 统一返回 / 异常 / 状态机 / AES-GCM 加密
│       │   │   ├── config/         # CORS 等配置
│       │   │   └── seed/           # 演示数据生成器（启动自动播种，幂等）
│       │   └── resources
│       │       ├── application.yml # 配置（账号密码与密钥全部走环境变量）
│       │       └── db/migration/   # Flyway 迁移（V1~V28，含本体种子数据与演示账号）
│       └── test/java/com/bemodel   # 单元测试（ontology / modeling / clinical / cs / rdf 等）
├── bemodel-web                 # 前端（Vue 3 + Vite）
│   ├── index.html
│   ├── vite.config.js          # dev 代理 /api → 127.0.0.1:18080
│   ├── package.json
│   └── src
│       ├── api/                # axios 接口封装（自动附 JWT）
│       ├── router/ store/ layout/ components/ utils/
│       ├── styles/             # 设计令牌层（tokens.css）+ Element 主题覆盖
│       └── views/              # 页面：login / architecture / ontology / datasource / glossary
│                               #       link / flow / clinical / gov / ask / cs
│                               #       evolve（概念缺口）/ drift（语义漂移）/ value
└── docs/screenshots/intro/     # README 界面截图
```

## 界面截图

### 登录（JWT 三角色）

Spring Security + JWT 认证，内置 ADMIN / EDITOR / VIEWER 三种角色，路由守卫拦截未登录访问。

![登录页](docs/screenshots/intro/00-login.png)

### 架构全貌（分层架构视图）

业务应用 → 推理引擎 → 数据映射 → 本体四层语义架构，节点点击直达对应模块；推理引擎层为规则引擎、本体自检发布门禁与 SHACL 校验双引擎互证。

![架构全貌](docs/screenshots/intro/01-architecture.png)

### 本体管理

业务域 → 概念 → 关系，公理结构化存储，支持多父继承；发布版本与 LLM 能力在同一工作台管理。

![本体管理](docs/screenshots/intro/02-ontology.png)

### 概念邻域图

概念「诊断」的邻域图：支撑检验报告、可能触发感染上报，与「患者」的互斥约束以红色虚线标出。

![概念邻域图](docs/screenshots/intro/03-concept-graph.png)

### 概念缺口（本体增长回路）

提问与搜索中本体未覆盖的说法自动记入缺口：来源（AI 客服 / 智能问数 / 概念搜索 / AI 映射）、热度计数、AI 归类建议、一键去本体处置——平台被问得越多，本体长得越全。

![概念缺口](docs/screenshots/intro/04-concept-gap.png)

### AI 客服语义问答

问「多个患者的处方可以一起结算吗？」——结构依据来自本体（结算记录按住院号维系），探针 SQL 实时验证（22 条结算记录对应 22 个住院号，一比一），证据与跳转一体呈现。

![AI 客服语义问答](docs/screenshots/intro/05-cs-semantic.png)

### 数据源绑定

注册九个业务库连接（密码 AES-GCM 加密落库），一键扫描 information_schema 建物理快照。

![数据源绑定](docs/screenshots/intro/06-datasource.png)

### 链路追溯

双向 BFS 还原每笔异常的来龙去脉：医嘱 → 计费 → 缴费 → 发药 / 检验全链路可视，变更影响多跳可查。

![链路追溯](docs/screenshots/intro/07-link.png)

### 病案内涵质控

八类规则跨库执法（如「男性患者诊断卵巢囊肿」命中性别互斥公理 AX-003），每条发现标注跨了哪几个库、引用了哪条规则与公理。

![病案内涵质控](docs/screenshots/intro/08-clinical.png)

### 医嘱闭环

住院 / 门诊医嘱到结算全链路追踪，数据来自业务库实测，支持导出患者 ABox（Turtle）。

![医嘱闭环](docs/screenshots/intro/09-flow.png)

### 智能问数（口径卡）

指标名直命中时返回结构化口径卡：口径定义、计算公式、探针 SQL 与最近一次巡检实测值同源呈现，数字只来自业务库。

![智能问数口径卡](docs/screenshots/intro/10-analytics.png)

### 语义漂移

术语分叉与口径演进检测，全部来自真实数据，无推断占比。

![语义漂移](docs/screenshots/intro/11-semantic-drift.png)

## 快速开始

环境要求：JDK 21+、Maven 3.9+、MySQL 8、Node 18+（推荐 pnpm）。

```bash
# 1. 配置环境变量（数据库账号密码必填；账号需有建库权限，首次启动会自动建库建表）
export MYSQL_USERNAME=your_mysql_user
export MYSQL_PASSWORD=your_mysql_password
export JWT_SECRET=your_jwt_secret          # 可选；不配置使用内置开发密钥（仅限演示）
export APP_SECRET_KEY=your_encrypt_key     # 可选；同上，用于数据源密码加密
export DEEPSEEK_API_KEY=sk-xxxx            # 可选；不配置则 LLM 能力自动降级为规则/模板

# 2. 启动后端（Flyway 自动建表 + DataSeeder 自动生成演示数据与演示账号）
cd bemodel-server
mvn spring-boot:run                    # http://127.0.0.1:18080

# 3. 启动前端
cd bemodel-web
pnpm install
pnpm dev                               # http://127.0.0.1:5173（打开后进入登录页）
```

内置演示账号（仅限演示环境，定义于 [V26__auth_and_security.sql](bemodel-server/src/main/resources/db/migration/V26__auth_and_security.sql)）：

| 账号        | 密码          | 角色   | 权限                       |
| ----------- | ------------- | ------ | -------------------------- |
| `admin`   | `admin123`  | ADMIN  | 全部能力                   |
| `modeler` | `model123`  | EDITOR | 建模与写操作（无用户管理） |
| `viewer`  | `viewer123` | VIEWER | 只读 + 问答 / 搜索         |

首次启动说明：

- Flyway 自动执行 V1~V28 迁移，创建平台元数据库表结构、本体种子数据与演示账号
- `DataSeeder` 自动生成九个演示业务库（demo_charge / demo_emr / demo_his / demo_lis / demo_material / demo_nurse / demo_opd / demo_pacs / demo_pharmacy），含 40 名**虚构**患者的住院医嘱全闭环数据，并预埋若干「取消未退费」类数据裂缝供质控与追溯演示；数据确定性可重复，幂等跳过
- 未配置 `DEEPSEEK_API_KEY` 时，AI 相关能力自动降级（关键词路由 / 模板作答），平台功能不中断

## 环境变量

| 变量                 | 必填     | 默认值               | 说明                                                     |
| -------------------- | -------- | -------------------- | -------------------------------------------------------- |
| `MYSQL_USERNAME`   | 是       | —                   | 平台库用户名（需有建库权限），同时用作九个演示库连接账号 |
| `MYSQL_PASSWORD`   | 是       | —                   | 平台库密码                                               |
| `MYSQL_HOST`       | 否       | `127.0.0.1`        | MySQL 主机                                               |
| `MYSQL_PORT`       | 否       | `3306`             | MySQL 端口                                               |
| `MYSQL_DATABASE`   | 否       | `bemodel_platform` | 平台元数据库名                                           |
| `JWT_SECRET`       | 生产必填 | 内置开发密钥         | JWT 签名密钥（HS256）；未配置时启动会告警                |
| `APP_SECRET_KEY`   | 生产必填 | 内置开发密钥         | 数据源密码 AES-GCM 加密密钥；更换后需重新保存数据源密码  |
| `DEEPSEEK_API_KEY` | 否       | —                   | DeepSeek API Key；不配置则自动降级                       |

> 安全约定：API Key、数据库账号密码、JWT / 加密密钥只走环境变量，不落入仓库（`.gitignore` 已排除 `.env*`）；代码中的内置开发密钥（`bemodel-dev-*-do-not-use-in-prod`）仅用于零配置演示，启动日志会明确告警。

## 当前边界

- 演示数据为平台自建的九套 demo 库，尚未接入真实产品线；接上真实库的只读连接后，同样的映射、探针与问答即可工作
- 认证授权已落地（JWT 三角色、写操作需 EDITOR+），但生产化仍需补齐：HTTPS 传输、口令策略与定期轮换、审计日志完善、患者敏感字段的出口脱敏收口
- 数据源密码加密与本机部署默认配置面向演示环境；公网部署前必须替换 `JWT_SECRET` / `APP_SECRET_KEY` 并启用传输加密
- LLM 依赖 DeepSeek API，需自行配置 Key；每次调用已落 `llm_log` 审计表并绑定本体版本号

## License

[Apache License 2.0](LICENSE)
