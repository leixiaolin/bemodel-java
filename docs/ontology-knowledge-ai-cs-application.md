# 本体知识在智能问数与 AI 客服中的应用梳理

## 1. 文档范围

本文基于当前 Python 后端 `bemodel-server-py/` 和共用前端 `bemodel-web/` 的实际实现，说明本体管理中的概念、属性、关系、术语、指标、规则、动作、公理及物理映射，如何进入以下两类业务流程：

- 智能问数：前端“智能问数”页面，`scene=ANALYTICS`。
- AI 客服：前端“AI 客服”页面，包括自然语言问答、客诉工单诊断和退费处置，`scene=CS`。

本文特别区分三种状态：

- **直接使用**：运行时明确读取该知识表，并参与检索、提示词、推理、查询或执行。
- **间接使用**：通过概念关系、映射、发布快照或固定业务实现体现，但不直接读取对应知识表。
- **尚未接入**：本体管理中可维护，但当前问数或客服运行链路不会消费。

## 2. 总体结论

当前系统的核心模式是“结构化语义层 + 场景路由 + 受控查询/固定业务服务 + LLM 表达”：

1. 概念、属性、关系、术语、指标和物理映射构成可查询的语义层。
2. 智能问数和客服问答共用 `POST /api/cs/ask`，通过 `scene` 区分场景。
3. 开放问数会把已发布概念、属性、关系、确认映射和枚举码值拼成提示词上下文，由 LLM 生成受约束的查询计划。
4. 后端对白名单表、列和只读 SQL 做确定性校验，再查询业务库；LLM 不直接访问数据库。
5. AI 客服中的常见问题优先进入固定意图处理器；客诉工单则进入 RCA 跨库诊断流程。
6. `bm_rule`、`bm_action`、`bm_axiom` 当前**不会自动注入智能问数或客服问答提示词**。
7. 规则和公理已有真实执行链，但目前主要用于临床质控；动作目前主要参与建模、状态流转、发布快照和价值统计，客服退费并非由动作模型动态驱动。

## 3. 知识类型与应用矩阵

| 知识类型 | 管理接口/存储 | 智能问数 | AI 客服问答 | 客服工单诊断/处置 |
| --- | --- | --- | --- | --- |
| 概念 `Concept` | `/api/concept/**`、`bm_concept` | 直接使用：仅已发布概念进入语义上下文、命中识别和结果链接 | 直接/间接使用：语义查询及专用回答中的概念依据 | 直接使用：工单 `conceptCode` 是 RCA 图遍历起点 |
| 属性 `Attribute` | `/api/concept/attribute`、`bm_attribute` | 直接使用：属性名、类型进入提示词，并与物理列映射 | 语义查询分支直接使用 | 主要通过固定 SQL 和映射口径间接体现 |
| 关系 `Relation` | `/api/concept/relation`、`bm_relation` | 直接使用：关系三元组进入提示词；结果页显示关系邻域 | 直接使用：可用于结构类“能不能”判断 | 直接使用：RCA 从工单概念向外遍历最多 4 层 |
| 术语 `Term` | `/api/term/**`、`bm_term` | 直接使用：概念命中展示；口径搜索可由术语命中 | 直接使用：口径问答和人员/业务方言归一 | 临床质控会用于同概念词族扩展；RCA 主链不直接读取 |
| 指标 `Metric` | `/api/metric/**`、`bm_metric` | 直接使用：口径类问题检索定义和公式 | 直接使用：`GLOSSARY` 分支返回指标口径卡片 | RCA 建议会引用指标编码，但诊断探针是固定 SQL |
| 物理映射 `Mapping` | `/api/mapping/**`、`bm_mapping` | 核心直接使用：确认映射决定提示词和 SQL 白名单 | 语义查询与枚举解码直接使用 | 流程展示用于枚举解码；部分 RCA 说明体现映射口径 |
| 规则 `Rule` | `/api/rule/**`、`bm_rule` | 尚未直接接入；结构类回答由 LLM 根据概念/关系生成 | 专用客服处理器含固定规则，但不读取 `bm_rule` | 工单 RCA 不读取；已发布 `engine=QC` 规则由临床质控执行 |
| 动作 `Action` | `/api/action/**`、`bm_action` | 尚未接入 | 尚未直接接入 | 退费使用固定 `refund_action()`，不读取 `bm_action` |
| 公理 `Axiom` | `/api/axiom/**`、`bm_axiom` | 尚未直接接入 | 尚未直接接入 | RCA 不读取；临床质控规则可通过 `exprJson.axiom` 引用公理 |
| 发布快照 `Release` | `/api/release/**`、`bm_release` | 问数读取当前表，不按快照版本读取 | 同左 | RCA 同样不按快照读取；发布会固化已发布规则、动作等 |

## 4. 知识究竟如何进入语义上下文和提示词

这一节直接回答“数据库中的一条知识记录，经过什么代码，最终以什么文字进入 LLM”。智能问数不是把本体表原样转成 JSON，也不是把 OWL 文件直接交给模型，而是由 `SemanticQaService.build_semantic_context()` 临时生成一段纯文本。

### 4.1 一次请求会调用哪几个 Prompt

以问题“已发药记录有多少？”为例，最多会发生三次模型调用：

```text
用户问题
  |
  | 第一次：CS_ROUTE 或 ANALYTICS_ROUTE_PROMPT
  | 只做意图分类，不带本体语义上下文
  v
SEMANTIC_QUERY
  |
  | 第二次：CS_SEMANTIC_PLAN
  | 带 build_semantic_context() 生成的本体上下文
  v
查询计划 JSON -> 白名单校验 -> 执行业务库 SQL
  |
  | 第三次：CS_SEMANTIC_ANSWER
  | 不再带完整本体，只带问题、查询语义、SQL 和结果
  v
自然语言答案
```

三次调用承担不同职责，不能混为一个 Prompt：

| 调用类型 | system prompt 的角色 | user prompt 中是否有本体知识 | 作用 |
| --- | --- | --- | --- |
| `CS_ROUTE` | 意图分类器 | 否；客服场景只会附加最近 10 条负反馈 | 判断走口径、语义查询还是客服专用处理器 |
| `CS_SEMANTIC_PLAN` | 本体语义查询规划器 | 是；概念、属性、确认映射、枚举和关系 | 生成 `QUERY`、`MODEL_ANSWER` 或 `UNANSWERABLE` |
| `CS_SEMANTIC_ANSWER` | 数据问答/业务规则解答助手 | 不带完整本体；只带规划结论和查询证据 | 把已验证结果组织成人话 |

### 4.2 第一步：从数据库读取哪些知识

`build_semantic_context()` 每次规划查询时直接读取当前表：

```python
concepts = Concept where status == "PUBLISHED"
attributes = all Attribute
tables = all PhysicalTable
mappings = Mapping where confirmed == 1
relations = all Relation
```

这里有几个重要边界：

- 概念只有 `PUBLISHED` 状态才进入上下文。
- 属性虽然是全量读取，但只有挂在已发布概念上的属性会在“本体概念”段输出。
- 只有 `confirmed=1` 的映射进入上下文，未确认映射对模型不可见，也不能进入 SQL 白名单。
- 关系是全量读取，当前没有状态过滤。
- `Term`、`Metric`、`Rule`、`Action`、`Axiom`、`Release.snapshotJson` 均不在这个函数的读取范围内。

### 4.3 第二步：各类记录如何转换成文本

假设平台库中有以下简化记录：

```text
Concept:  code=DISPENSE, name=发药记录, status=PUBLISHED
Attribute: concept_code=DISPENSE, attr_code=STATUS,
           attr_name=发药状态, data_type=STRING
Mapping:  ds_code=DS_PHARMACY, table_name=dispense_record,
          column_name=status, concept_code=DISPENSE,
          attr_code=STATUS, value_map={"0":"待发药","1":"已发药","2":"已退药"},
          confirmed=1
Relation: from_concept=MEDICAL_ORDER, relation_name=调剂发药,
          to_concept=DISPENSE
PhysicalTable: ds_code=DS_PHARMACY, table_name=dispense_record,
               table_comment=发药记录表
```

代码会把它们转换成下面三段，而不是输出原始字段：

```text
【本体概念】
DISPENSE(发药记录): 发药状态/STRING

【物理映射】（概念.属性 = 数据源.表.列，枚举列为原始码=中文）
DS_PHARMACY:
  dispense_record（发药记录表）: status=DISPENSE.发药状态{0:待发药,1:已发药,2:已退药}

【概念关系】
MEDICAL_ORDER(医嘱)—调剂发药→DISPENSE(发药记录)
```

字段转换规则如下：

| 知识字段 | 进入上下文后的形式 | 当前未进入的字段 |
| --- | --- | --- |
| `Concept.code/name` | `DISPENSE(发药记录)` | `definition`、`domainCode`、`owner`、`iri`、版本 |
| `Attribute.attrName/dataType` | `发药状态/STRING` | `attrCode`、`definition`、`isKey`、排序 |
| `PhysicalTable.tableName/tableComment` | `dispense_record（发药记录表）` | 其他表元数据 |
| `Mapping.columnName/conceptCode/attrCode` | `status=DISPENSE.发药状态` | 映射置信度等其他字段 |
| `Mapping.valueMap` | 去掉 JSON 花括号和引号后附在列后面 | 无法解析也仍可能以清洗文本出现 |
| `Relation.from/relationName/to` | `MEDICAL_ORDER(医嘱)—调剂发药→DISPENSE(发药记录)` | `description`、对称/传递/函数性、逆关系等语义标记 |

因此，“定义写得很详细”不代表开放问数一定能看到定义；目前开放问数主要看到的是结构和映射。概念定义和指标公式走的是另一条“口径检索”链路。

### 4.4 第三步：语义上下文如何拼进查询规划 Prompt

`plan_query(q)` 的实际拼接顺序是：

```python
user_prompt = build_semantic_context() + SEMANTIC_PLAN_PROMPT
system_prompt = "你是医疗信息平台的本体语义查询规划器，把自然语言问题编译为只读 SQL。只返回JSON，不要多余文字。"
```

`SEMANTIC_PLAN_PROMPT` 会把 `__TODAY__` 换成当天日期，把 `__QUESTION__` 换成用户问题。最终送给模型的内容可简化还原为：

```text
system:
你是医疗信息平台的本体语义查询规划器，把自然语言问题编译为只读 SQL。
只返回JSON，不要多余文字。

user:
【本体概念】
MEDICAL_ORDER(医嘱): 医嘱编号/STRING, 医嘱状态/STRING
DISPENSE(发药记录): 发药编号/STRING, 医嘱编号/STRING, 发药状态/STRING

【物理映射】（概念.属性 = 数据源.表.列，枚举列为原始码=中文）
DS_PHARMACY:
  dispense_record（发药记录表）:
  dispense_id=DISPENSE.发药编号,
  order_id=DISPENSE.医嘱编号,
  status=DISPENSE.发药状态{0:待发药,1:已发药,2:已退药}

【概念关系】
MEDICAL_ORDER(医嘱)—调剂发药→DISPENSE(发药记录)

规则：
1. ds 与表名只能取【物理映射】中列出的值……
2. 枚举列把中文反解为原始码……
3. SQL 只能是 SELECT，LIMIT 不得超过 100……
……
今天日期：2026-09-29
用户问题：已发药记录有多少？
只输出JSON：{"mode":"QUERY", ...}
```

模型据此完成四个翻译动作：

1. “发药记录”对应概念 `DISPENSE`。
2. `DISPENSE` 对应物理表 `DS_PHARMACY.dispense_record`。
3. “已发药”对应属性“发药状态”，再由 `valueMap` 反解为 `status='1'`。
4. “有多少”对应聚合函数 `COUNT(*)`。

期望模型输出：

```json
{
  "mode": "QUERY",
  "ds": "DS_PHARMACY",
  "sql": "SELECT COUNT(*) AS cnt FROM dispense_record WHERE status = '1' LIMIT 100",
  "semantics": "统计状态为已发药的发药记录数量"
}
```

### 4.5 第四步：为什么模型输出后还要再次使用映射

映射不只用于 Prompt，还用于程序侧硬校验：

```text
Mapping(dsCode=DS_PHARMACY, confirmed=1)
  -> allowed tables = [dispense_record]
  -> allowed columns = {dispense_id, order_id, status, ...}
```

`validate_sql()` 检查模型 SQL 中的表和列是否都在白名单中；随后 `normalize_enum_literals()` 还会再次读取 `valueMap`。即使模型写成 `status='已发药'`，程序也可在映射唯一时改写为 `status='1'`。所以映射同时承担：

- 给模型看的“语义翻译字典”。
- 给后端用的“SQL 访问白名单”。
- 给后端用的“枚举值纠错字典”。

### 4.6 第五步：查询结果如何进入答案 Prompt

SQL 执行后，完整本体上下文不会再次发送。`CS_SEMANTIC_ANSWER` 收到的是：

```text
system:
你是医院信息平台的数据问答助手。严格基于给定查询结果用中文回答，
先给结论再给关键数字，口语化，不超过200字。结果里没有的信息不要编造。

user:
用户问题：已发药记录有多少？
查询语义：统计状态为已发药的发药记录数量
执行SQL：SELECT COUNT(*) AS cnt FROM dispense_record WHERE status = '1' LIMIT 100
结果行数：1
结果JSON：[{"cnt":12}]
```

模型只负责把证据组织成“当前共有 12 笔已发药记录”这类答案。概念和映射在上一步已经完成了自然语言到 SQL 的转换，此时不会重复注入。

### 4.7 口径问题走的是另一种知识注入方式

问题“出院人数怎么算？”会先被路由为 `GLOSSARY`。`SearchService.search()` 在 `Term`、`Concept`、`Metric` 中做字符串匹配，命中后拼成：

```text
用户问题：出院人数

平台检索到的口径定义：
- [指标] 出院人数（负责人：病案室）：
  口径：统计期间内完成出院登记的患者人次 公式：COUNT(出院记录)
- [概念] 出院记录（DISCHARGE）：患者完成本次住院离院的业务记录

请基于以上定义用中文简洁回答用户问题（不超过200字）。
若定义不足以回答，请说明缺口。
```

它以 `SEARCH_ANSWER` 调用 LLM。这里会进入概念定义、指标定义和公式，但不会进入物理映射、关系、规则、动作或公理，也不会生成 SQL；指标探针的执行是指标页面的独立能力。

### 4.8 规则、动作、公理为什么没有进入 Prompt

当前 `build_semantic_context()` 没有查询 `Rule`、`Action`、`Axiom`，所以即使创建并发布以下知识：

```text
Rule:   缴费是发药的前置条件
Action: 未缴费发药异常 -> 冻结发药/创建核查工单
Axiom:  未缴费状态 与 可发药状态 互斥
```

开放问数的 Prompt 仍然只会看到概念、属性、映射和关系。它们不会以规则段、动作段或公理段出现在 `CS_SEMANTIC_PLAN` 中，也不会自动约束模型输出。

AI 客服看起来能够回答“没缴费可以发药吗？”，原因是该问题被路由到 `DISPENSE_PAY`，执行的是 `CsService.dispense_pay_answer()` 中写死的跨库 SQL 和回答模板。该处理器表达了“缴费是发药前置条件”，但没有读取 `bm_rule`。同理，点击“一键退费”调用固定的 `refund_action()`，没有读取 `bm_action`。

公理当前只有临床质控链路会实际读取，例如：

```text
已发布 QC Rule.exprJson
  -> {"type":"SEX_DISJOINT_DIAG", "axiom":"AXIOM_SEX_DIAG_DISJOINT", ...}
  -> QcRuleEngine 根据 axiomCode 查询 bm_axiom
  -> 解析为结构化互斥概念对
  -> 查询患者性别和诊断
  -> 输出违反公理的质控发现
```

这是一条确定性规则执行链，不是 LLM Prompt 注入链，也没有被 `/api/cs/ask` 或客服工单 RCA 调用。

### 4.9 AI 客服工单中的知识传递方式

客服工单诊断也不是把本体整体放入 Prompt。假设工单记录中：

```text
ticket.conceptCode = FEE_DETAIL
ticket.payload = {"inhos_no":"ZY0001", "patient":"张三"}
```

`RcaEngine.traverse()` 读取全部 `Relation`，从 `FEE_DETAIL` 双向遍历最多 4 层，得到概念路径。路径的用途是查询这些概念上的 `CHANGE`、`DEPLOY`、`TESTCASE`、`REQUIREMENT` 链路节点。随后程序执行固定 SQL 探针，得到患者账单、LIS 状态、字典映射裂缝和影响范围。

只有整理后的事实进入 `RCA_REPORT` Prompt：

```text
客诉工单：检验取消后仍然收费
分析结论：LIS 升级后撤销码由 X 改为 C，HIS 映射未同步……

证据链：
- 患者账单核查：存在 1 笔医嘱已取消但费用仍正常的记录
- 跨库事实核实：对应 LIS 申请状态为 C
- 字典裂缝定位：status_map 缺少 C 的退费映射
- 全院影响面：影响 3 名患者、5 笔费用……

关联链路记录：
- [DEPLOY] 2026-08-15 LIS v5.2 上线
- [TESTCASE] TC-FEE-0032 未覆盖新撤销码
```

也就是说，关系知识在客服工单中先由程序用于“圈定调查范围”，LLM 最终看到的是程序核验后的证据摘要，而不是原始关系表。规则、动作和公理仍未进入该报告 Prompt。

## 5. 知识建模与生效入口

### 5.1 概念、属性和关系

创建概念：

```http
POST /api/concept
Content-Type: application/json

{
  "code": "DISPENSE",
  "name": "发药记录",
  "domainCode": "PHARMACY",
  "definition": "药房对处方或医嘱进行调剂发放的记录",
  "owner": "药学部",
  "iri": null
}
```

创建后状态为 `DRAFT`。要进入智能问数的概念上下文，需流转到 `PUBLISHED`：

```http
POST /api/concept/transition/DISPENSE?target=REVIEW
POST /api/concept/transition/DISPENSE?target=PUBLISHED
```

创建属性：

```http
POST /api/concept/attribute
Content-Type: application/json

{
  "conceptCode": "DISPENSE",
  "attrCode": "STATUS",
  "attrName": "发药状态",
  "dataType": "STRING",
  "isKey": 0,
  "definition": "调剂发药当前状态",
  "sort": 1
}
```

创建关系：

```http
POST /api/concept/relation
Content-Type: application/json

{
  "fromConcept": "MEDICAL_ORDER",
  "toConcept": "DISPENSE",
  "relationName": "调剂发药",
  "description": "一条药品医嘱可产生一笔或多笔发药记录",
  "isSymmetric": 0,
  "isTransitive": 0,
  "isFunctional": 0,
  "isInverseFunctional": 0,
  "isAsymmetric": 0,
  "inverseOf": null,
  "iri": null
}
```

注意：当前语义上下文会读取全部关系，关系本身没有按发布状态过滤；概念则只读取 `PUBLISHED` 状态。

### 5.2 物理映射

物理字段必须映射到概念属性，且 `confirmed=1`，才会进入智能问数提示词和 SQL 白名单：

```http
POST /api/mapping/batch
Content-Type: application/json

[
  {
    "dsCode": "DS_PHARMACY",
    "tableName": "dispense_record",
    "columnName": "status",
    "conceptCode": "DISPENSE",
    "attrCode": "STATUS",
    "valueMap": "{\"0\":\"待发药\",\"1\":\"已发药\",\"2\":\"已退药\"}",
    "confirmed": 1
  }
]
```

`valueMap` 会帮助 LLM 和后端把“已发药”等中文口径反解为物理码值 `1`。

### 5.3 规则

```http
POST /api/rule
Content-Type: application/json

{
  "ruleCode": "RULE_DOSE_LIMIT",
  "name": "药品日剂量上限检查",
  "conceptCode": "MEDICAL_ORDER",
  "ruleType": "约束",
  "severity": "高",
  "metricCode": null,
  "engine": "QC",
  "exprJson": "{\"type\":\"DOSE_LIMIT\"}",
  "expression": "单日剂量不得超过药品字典最大日剂量",
  "owner": "医务处"
}
```

创建后需经状态流转才能被临床质控执行：

```http
POST /api/rule/transition/RULE_DOSE_LIMIT?target=REVIEW
POST /api/rule/transition/RULE_DOSE_LIMIT?target=PUBLISHED
```

当前只有 `engine=QC` 且 `status=PUBLISHED` 的规则由 `QcRuleEngine.run_rules()` 执行。智能问数和 AI 客服的 `CsService`、`SemanticQaService` 均未查询 `Rule`。

### 5.4 动作

```http
POST /api/action
Content-Type: application/json

{
  "actionCode": "REFUND_APPLY",
  "name": "申请退费",
  "conceptCode": "FEE_DETAIL",
  "fromStatus": "正常",
  "toStatus": "退费中",
  "triggerDesc": "确认取消未退费后触发",
  "description": "生成退费申请并进入财务处理"
}
```

动作同样支持 `DRAFT -> REVIEW -> PUBLISHED`：

```http
POST /api/action/transition/REFUND_APPLY?target=REVIEW
POST /api/action/transition/REFUND_APPLY?target=PUBLISHED
```

当前客服退费接口不会按 `actionCode` 查找或执行动作，动作只作为知识模型和发布内容存在。

### 5.5 公理

```http
POST /api/axiom
Content-Type: application/json

{
  "axiomCode": "AXIOM_SEX_DIAG_DISJOINT",
  "subject": "男性患者",
  "predicate": "互斥",
  "object": "妊娠诊断",
  "axiomType": "互斥",
  "description": "男性患者与妊娠类诊断互斥"
}
```

公理没有与规则/动作相同的状态流转接口。当前可执行用法是由 QC 规则的 `exprJson` 引用：

```json
{
  "type": "SEX_DISJOINT_DIAG",
  "sex": "男",
  "diagKeywords": ["妊娠"],
  "axiom": "AXIOM_SEX_DIAG_DISJOINT"
}
```

`QcRuleEngine` 会读取公理，再解析到结构化互斥概念对，作为质控判定依据。该链路目前不属于智能问数或 AI 客服。

## 6. 智能问数流程

### 6.1 入口与传参

前端 `bemodel-web/src/views/ask/index.vue` 调用：

```http
POST /api/cs/ask
Content-Type: application/json

{
  "question": "已发药但没有缴费的记录有多少？",
  "scene": "ANALYTICS"
}
```

后端调用栈：

```text
cs.router.ask
  -> CsService.ask(question, scene)
  -> LLM/关键词意图路由
  -> SemanticQaService.answer(question, analytics=True)
  -> build_semantic_context()
  -> plan_query()
  -> validate_sql()
  -> DatasourceService 查询业务库
  -> LLM 基于结果生成答案
```

### 6.2 路由环节

`scene=ANALYTICS` 时允许两类意图：

- `GLOSSARY`：指标口径、名词定义、计算方式。
- `SEMANTIC_QUERY`：数量、明细、统计、状态、库存、金额、名单，以及“能不能/是否允许”等业务结构问题。

配置 DeepSeek Key 时调用 `DeepSeekClient.chat("CS_ROUTE", ...)` 分类；无 Key 或分类失败时使用关键词规则兜底。

### 6.3 口径问答环节

若命中 `GLOSSARY`，调用 `SearchService.search()`，检索：

- `Term.term`：业务术语及别名。
- `Concept.name/definition`：标准概念及定义。
- `Metric.name/definition/formula`：指标口径及公式。

命中结果会作为 `SEARCH_ANSWER` 的提示词上下文。此环节不读取规则、动作或公理。

### 6.4 开放语义查询环节

`SemanticQaService.build_semantic_context()` 读取并拼装：

- `Concept.status == PUBLISHED` 的概念。
- 概念属性及数据类型。
- `Mapping.confirmed == 1` 的物理表列映射。
- 枚举 `valueMap`。
- 概念关系。

发送给 LLM 的计划请求包含“语义上下文 + 用户问题”，模型返回三种模式之一：

```json
{
  "mode": "QUERY",
  "ds": "DS_PHARMACY",
  "sql": "SELECT COUNT(*) AS cnt FROM dispense_record WHERE status = '1' LIMIT 100",
  "semantics": "按发药记录的发药状态统计已发药数量"
}
```

```json
{
  "mode": "MODEL_ANSWER",
  "ds": "DS_CHARGE",
  "semantics": "结算记录按住院号维系，一张结算单对应单个患者的一次住院",
  "conclusion": "不可以跨患者合并结算",
  "verifySql": "SELECT COUNT(*) AS cnt, COUNT(DISTINCT inhos_no) AS patients FROM settlement LIMIT 100"
}
```

```json
{
  "mode": "UNANSWERABLE",
  "reason": "没有可用的概念属性或确认映射"
}
```

`QUERY` 和 `MODEL_ANSWER.verifySql` 都要经过 SQL 白名单校验。只允许单条 `SELECT`，表和列必须来自当前数据源的确认映射，执行超时 15 秒，最多读取 100 行、向页面展示前 20 行。

### 6.5 返回结果

典型响应的 `data`：

```json
{
  "question": "已发药记录有多少？",
  "intent": "语义查询",
  "router": "SEMANTIC",
  "answer": "当前查询到已发药记录 12 笔。",
  "evidence": [
    {"label": "执行SQL", "value": "SELECT ... LIMIT 100"},
    {"label": "数据源", "value": "DS_PHARMACY / dispense_record"},
    {"label": "结果行数", "value": "1"}
  ],
  "semantics": "按发药状态统计发药记录",
  "rows": [{"cnt": 12}],
  "matchedConcepts": [{"code": "DISPENSE", "name": "发药记录", "match": "映射"}],
  "relations": [],
  "corrections": []
}
```

若语义层无法回答，会记录本体缺口，来源标记为 `QA_ASK`，并返回能力菜单及 `missRecorded=true`，供本体扩展提案闭环处理。

## 7. AI 客服流程

### 7.1 自然语言客服问答

入口与智能问数相同，仅场景不同：

```http
POST /api/cs/ask
Content-Type: application/json

{
  "question": "一张医嘱可以分开发药吗？",
  "scene": "CS"
}
```

客服场景支持 `FEE`、`DISPENSE_PAY`、`DISPENSE_SPLIT`、`DISPENSE_RETURN`、`MATERIAL`、`STAFF`、`GLOSSARY`、`SEMANTIC_QUERY` 等意图。

处理优先级如下：

1. 有 LLM Key 时，`CS_ROUTE` 根据问题和历史负反馈分类。
2. 分类不可用时，`route_by_keyword()` 使用关键词规则。
3. 命中专用意图时，调用 `CsService` 内固定处理器并执行预置跨库 SQL。
4. 命中 `GLOSSARY` 时，使用术语、概念和指标知识。
5. 命中 `SEMANTIC_QUERY` 时，复用智能问数的本体上下文和安全 SQL 链路。
6. 未命中时返回客服能力菜单；语义查询无法回答时记录来源为 `CS_ASK` 的本体缺口。

例如“分开发药”进入 `dispense_split_answer()`：它在回答中使用“医嘱—调剂发药→发药记录为 1:N”的本体语义，并实时查询药房库验证，但当前关系说明和 SQL 是服务代码中的固定实现，不是运行时按某条 `Rule` 或 `Axiom` 读取执行。

### 7.2 客服反馈闭环

```http
POST /api/cs/feedback
Content-Type: application/json

{
  "question": "一张医嘱可以分开发药吗？",
  "intent": "分次发药核对",
  "router": "RULE",
  "correct": 0,
  "comment": "应归入退药流程"
}
```

最近 10 条负反馈会加入客服意图分类提示词，帮助纠正后续路由。它改进的是意图路由，不会自动生成或修改本体规则。

### 7.3 客诉工单诊断

诊断入口：

```http
GET /api/cs/ticket/{ticketId}/diagnosis
```

无需请求体。后端根据 `ticketId` 读取 `LinkNode` 工单及其 `payload`，典型字段包括住院号和患者名。调用链：

```text
CsService.diagnosis(ticketId)
  -> 查找或创建 RcaCase
  -> RcaEngine.start(ticketRef)
  -> traverse(): 从 ticket.conceptCode 沿 Relation 图展开
  -> 固定跨库探针：患者账单、LIS 状态、映射裂缝、影响面
  -> 查询概念路径上的需求/变更/发布/测试节点
  -> DeepSeekClient.chat("RCA_REPORT", 证据上下文)
  -> 返回步骤、证据、影响面、建议和客户回复
```

本体知识在各环节的作用：

- **范围识别**：`ticket.conceptCode` 是起点，读取 `Relation` 后双向广度遍历最多 4 层，确定关联概念路径。
- **事实核查**：当前使用代码内固定 SQL 探针，不按 `Rule.expression/exprJson` 生成。
- **枚举口径**：诊断说明和流程服务会使用映射码值；通用流程展示通过 `Mapping.valueMap` 解码。
- **变更关联**：按遍历得到的概念编码查询 `CHANGE/DEPLOY/TESTCASE/REQUIREMENT` 链路节点。
- **报告生成**：LLM 只消费已核实的结论、证据链和关联记录，不直接读取完整本体。

### 7.4 客服退费处置

```http
POST /api/cs/ticket/{ticketId}/refund?operator=客服小周
```

后端 `CsService.refund_action(ticketId, operator)` 会：

1. 校验工单存在且尚未处置。
2. 用固定 SQL 查询“医嘱已取消但费用仍正常”的费用记录。
3. 在收费库逐笔创建退费申请，每笔业务库写入独立提交。
4. 在平台库创建 `DISPOSAL` 链路节点，并把工单标记为“已处置”。

这里的 `operator` 来自查询参数，不在 JSON 请求体中。该接口当前不读取 `bm_action`，也不根据动作的 `fromStatus/toStatus/triggerDesc` 做动态编排。

## 8. 规则、动作、公理的真实运行边界

### 8.1 规则

当前 `Rule` 的运行时执行者是临床质控 `QcRuleEngine`：

- 过滤条件：`engine == "QC"` 且 `status == "PUBLISHED"`。
- 执行定义：解析 `exprJson`，按 `type` 进入确定性规则实现。
- 支持类型包括诊断所需项目、术前检查、异常结果处置、并发症处置、性别互斥诊断、检查异常覆盖、过敏禁忌和剂量上限等。
- 输出会包含命中的 `ruleCode` 和引用的 `axiomCode`。

因此，在本体管理中新建普通规则并发布，并不会自然影响智能问数或 AI 客服。只有符合 QC 引擎约定的规则才会影响临床质控业务。

### 8.2 动作

`Action` 当前具备建模字段、状态流转和发布快照能力，但没有通用动作执行器。客服退费、流程操作等均由各业务服务显式实现。动作模型目前表达“能做什么、状态如何变化”，尚未成为“调用哪个服务/接口”的可执行编排定义。

### 8.3 公理

公理的实际执行方式有两类：

- `axiomType=互斥` 可在种子阶段解析为结构化概念互斥关系。
- QC 规则可在 `exprJson.axiom` 中引用公理，质控引擎据此生成判定依据。

智能问数的 `build_semantic_context()` 不读取 `Axiom`，RCA 工单诊断也不读取 `Axiom`。因此公理目前不会直接约束问数 SQL，也不会自动触发客服处置。

## 9. 发布与版本关系

发布接口：

```http
POST /api/release/publish
Content-Type: application/json

{
  "changeSummary": "补充发药与退药语义模型",
  "releasedBy": "admin",
  "force": false
}
```

发布前执行本体自检；发布快照包含已发布概念及其属性、全部关系、术语、指标、已发布规则、已发布动作和关系传递闭包。

需要注意：智能问数和 AI 客服运行时读取的是当前业务表，不读取 `Release.snapshotJson`。因此发布快照用于版本记录和审计，不是问答运行时的版本锁定机制。概念是否进入问数上下文由自身 `status=PUBLISHED` 决定，映射是否生效由 `confirmed=1` 决定。

## 10. 当前缺口与建议接入点

若希望“本体管理中配置的规则、动作、公理”真正统一驱动智能问数和 AI 客服，可按以下顺序演进：

1. **规则检索层**：按命中概念检索已发布规则，把规则编码、自然语言表达和结构化表达作为独立上下文加入 `MODEL_ANSWER`，并保留来源引用。
2. **公理约束层**：把可执行公理转换为结构化约束，在查询计划生成后、SQL 执行前做确定性校验，而不是只靠提示词。
3. **动作注册表**：为 `Action` 增加受控的执行器标识、参数模式、权限和幂等约束；动作只映射到后端白名单服务，不允许模型生成任意调用。
4. **客服建议与执行分离**：LLM 可推荐 `actionCode`，但必须经过规则校验、人工确认和服务端参数校验后执行。
5. **版本绑定**：问数和客服请求记录所用本体发布版本，必要时从发布快照构造语义上下文，保证答案可追溯和可复现。
6. **统一证据模型**：返回结果明确列出 `conceptCodes`、`relationIds`、`ruleCodes`、`axiomCodes`、`actionCode` 和数据探针，区分“模型推断”与“确定性执行”。

在完成这些改造前，产品说明应使用“概念与映射驱动问数、关系辅助客服诊断、规则/公理驱动临床质控、动作作为建模资产”的准确表述，不应宣称规则、动作、公理已经统一驱动智能问数和客服执行。

## 11. 关键实现位置

| 能力 | 实现位置 |
| --- | --- |
| 智能问数/客服统一入口 | `bemodel-server-py/src/bemodel/cs/router.py` |
| 意图路由、客服专用处理器、工单诊断和退费入口 | `bemodel-server-py/src/bemodel/cs/services.py` |
| 本体上下文、查询规划、SQL 校验执行、答案生成 | `bemodel-server-py/src/bemodel/cs/semantic.py` |
| 意图和查询计划提示词 | `bemodel-server-py/src/bemodel/cs/prompts.py` |
| SQL 白名单 | `bemodel-server-py/src/bemodel/cs/sql_validation.py` |
| 概念、属性、关系、术语、指标接口 | `bemodel-server-py/src/bemodel/ontology/router.py` |
| 规则、动作、公理和发布接口 | `bemodel-server-py/src/bemodel/modeling/router.py` |
| 规则、动作状态与发布快照 | `bemodel-server-py/src/bemodel/modeling/services.py` |
| 客诉 RCA 诊断 | `bemodel-server-py/src/bemodel/rca/services.py` |
| QC 规则和公理执行 | `bemodel-server-py/src/bemodel/clinical/rule_engine.py` |
| 前端 API 参数 | `bemodel-web/src/api/cs.js`、`bemodel-web/src/api/ontology.js` |
