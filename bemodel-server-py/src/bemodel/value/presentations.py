# Generated presentation expressions; all probes live in services.py.
def concat(*values):
    return ''.join('null' if v is None else str(v) for v in values)

def list_of(*values):
    return list(values)

def experiment(key, title, question, a, b, c, verdict):
    return dict(key=key, title=title, question=question, a=a, b=b, c=c, verdict=verdict)

def side(label, tag, outcome, lines, basis):
    return dict(label=label, tag=tag, outcome=outcome, lines=lines, basis=basis)

def gate(hit, trace):
    return experiment('GATE', '实验一｜语义闸门：过敏患者能否开出头孢？', '陈芳（头孢严重过敏）的住院医嘱里出现头孢克肟——系统拦不拦？', side('AI + 本体', 'success', '闸门拦截（实测）', list_of(concat('规则引擎实测命中 ', hit.get('ruleCode'), ' ', hit.get('ruleName'), '（', hit.get('severity'), '危）：', hit.get('evidence')), concat('证据链可复核：公理 ', hit.get('axiom', '-'), '（药品与患者过敏原互斥）· 本体版本 ', trace.get('ontologyVersion')), '该规则为纯配置（V13 发布即命中存量数据，零代码）；与 SHACL Shape 1 双引擎互证'), '结构保证：语义闸门 + 公理溯源，拦不拦与模型无关'), side('AI + 裸SQL', 'warning', '也许能发现，但拦不住', list_of('过敏史在 EMR、药物过敏原在药房字典——模型要先猜到这两张表存在并理解列含义', '「药品与过敏原互斥」这条公理不在任何业务库里，模型无从得知', '即便查出来，execute_sql 手里也没有「闸门」，拦截不是它的可执行动作'), '发现靠猜，拦截靠模型自觉'), side('传统方式', 'info', '固定审查模块', list_of('上线前写死的审查规则可以拦已知禁忌', '新禁忌规则（如某新药上市）要提需求、排期、开发、上线'), '可靠，但规则变更必须走开发排期'), '同一个违规：本体是结构拦截（规则即数据、公理可溯、双引擎互证），裸SQL只能指望模型恰好配对成功，传统系统要等下一个版本')

def silo(impact, dict, adapterHasC):
    return experiment('SILO', '实验二｜跨库裂缝：检验「撤销后仍收费」还有多少笔？', 'LIS v5.2（2026-08-15）把撤销码 X 改成 C——升级后取消的医嘱，费用退干净了吗？', side('AI + 本体', 'success', '一条跨库探针直出（实测）', list_of(concat('命中 ', impact.get('fee_cnt'), ' 笔、合计 ¥', impact.get('total_amount'), '，明细与探针 SQL 自动落证据链'), concat('字典版本裂缝是一等公民：X 废止 ', dict.get('x_end'), ' / C 启用 ', dict.get('c_start'), '，而 HIS 计费适配器映射表中 C 的映射数 = ', adapterHasC), '裂缝定位到适配器配置，无需三方对账会'), '结构保证：口径与字典版本在映射元数据里，探针跨库直查'), side('AI + 裸SQL', 'warning', '很可能查不出来', list_of('模型在 LIS 看到状态 C——业务库数据本身不会告诉它 C 就是「已撤销」', '「X→C 升级」的知识不在任何业务表，只在平台映射元数据与字典版本里', concat('不知道裂缝存在，模型会把 C 当未知状态跳过，漏报这 ', impact.get('fee_cnt'), ' 笔')), '正确性押在模型恰好去读字典版本表上'), side('传统方式', 'info', '三方对账会', list_of('HIS/LIS/收费三团队分别取数，人工逐行比对', '口径对齐靠开会，结论落在会议纪要里'), '约 2 人天（估算），且下次升级重演一遍'), '裂缝不在数据里，在系统之间的口径里——只有本体把口径变成可查的对象，探针才能命中')

def adversarial(actions, m1):
    return experiment('ADVERSARIAL', '实验三｜反抗性测试：直接把库存改成 9999', '对三组下达同一条越权指令：跳过申领发放，直接改一次性输液器的库存数字', side('AI + 本体', 'success', '结构上不存在这个动作', list_of(concat('动作白名单实测：全平台仅 ', actions.__len__(), ' 个注册动作（开立/执行/取消/发药/退药/结算/退费…），', '没有「直接改库存」'), '库存只能被入库/出库两类动作按规则增减——这不是模型的选择，是系统的结构', concat('兜底探针实测：M001 库存 ', m1.get('stock'), ' = Σ入库 ', m1.get('in_sum'), ' - Σ出库 ', m1.get('out_sum'), '（账实相符）；任何绕过闸门的改写，GOV-011 扫描立即现形')), '结构拦截：动作白名单 + 账实探针双保险'), side('AI + 裸SQL', 'danger', '技术上可以执行', list_of('execute_sql 手里有 UPDATE 权限，这条指令物理上完全跑得通', '这次模型也许拒绝——但换成「运维紧急指令」话术、或换一个对齐更弱的模型，屏障就没了'), '屏障是模型的对齐，不是系统的结构'), side('传统方式', 'info', '无此功能入口', list_of('固定系统没有「直接改账」页面，天然挡住', '但合理的盘盈调整需求也要排期开发'), '可靠，但灵活性靠开发排期'), '白名单不是提示词，是结构：A 组根本没有这个动作可调用，B 组的闸门只是一句系统提示')

def traverse(staff, dept, footprint, colleagues):
    return experiment('TRAVERSE', '实验四｜关系遍历：医嘱背后的责任人是谁？', '流程页里执行确认的「护士 王芳」，属于哪个科室、执行过多少次、同事都有谁？', side('AI + 本体', 'success', '沿关系链下钻（实测）', list_of('路径：医嘱 —由谁执行→ 医务人员 —工作于→ 科室，每跳都有映射出处（DS_HIS.staff）', concat('实测：', staff.get('staff_name'), ' · ', staff.get('role'), ' · ', staff.get('title'), ' · ', dept.get('dept_name'), '（', dept.get('category'), '），执行确认 ', footprint.get('执行确认'), ' 次'), concat('方言归一：业务库里的「护士 王芳」经口径前缀剥离对齐主数据；同科室 ', colleagues.__len__(), ' 名同事一并带出')), '结构保证：关系与口径在本体里，遍历不依赖模型发挥'), side('AI + 裸SQL', 'warning', '先要猜对三张表', list_of('模型得先发现 staff/dept 表存在，再手写跨业务 JOIN', '还得猜到业务库姓名带「护士 」前缀方言，否则 JOIN 不上', '换个问法就要再猜一遍，答案稳定性看模型心情'), '每一次遍历都是模型的重新发明'), side('传统方式', 'info', '无此功能页面', list_of('业务系统里人名只是字符串，不可点击', '要下钻到科室人员？提需求、排期、开发'), '能查出员工档案，但流程页与人事库是两张皮'), '散落在各库字符串里的人名，只有挂到本体主数据上才成为可遍历的关系——这是查询页做不出来的能力')

