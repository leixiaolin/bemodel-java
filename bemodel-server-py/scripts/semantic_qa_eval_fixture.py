"""仅供离线评测的固定合成数据；不读取配置数据库，不调用外部模型。"""
import json
from contextlib import contextmanager
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from bemodel.config import settings
from bemodel.core.database import Base
from bemodel.cs.semantic import SemanticQaService
from bemodel.datasource.entities import Mapping
from bemodel.llm.services import DeepSeekClient, LlmLogService
from bemodel.modeling.entities import Rule, Action, Axiom
from bemodel.ontology.entities import Concept, Metric
from bemodel.agents import runtime

VERSION = 'semantic-qa-synthetic-v1'
BASE_DATE = '2026-10-10'
PROBE = "SELECT COUNT(*) FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1'"
COUNT = "SELECT COUNT(*) AS n FROM fee_detail f JOIN medical_order o ON f.order_id=o.order_id WHERE o.order_status='2' AND f.fee_status='1'"


def query(sql, **extra):
    return dict(mode='QUERY', ds='DS_HIS', sql=sql, semantics='固定合成数据统计', **extra)


def model(**extra):
    return dict(mode='MODEL_ANSWER', conclusion='取消医嘱必须联动退费，但须核对触发条件。', semantics='医嘱取消规则', **extra)


# 期望数值由下方固定记录人工标注，不调用准入/匹配函数或被测 SQL 生成。
QUESTIONS = [
    dict(cat='direct', q='取消未退费有多少笔', expectDirect=True, expectedValue=3, plan=query(COUNT)),
    dict(cat='alias', q='现在取消未退费的费用有多少笔', expectDirect=True, expectedValue=3, plan=query(COUNT)),
    dict(cat='zero', q='取消未退费笔数是多少', expectDirect=True, expectedValue=0, scenario='zero', plan=query(COUNT)),
    dict(cat='card', q='取消未退费笔数怎么算', expectCard='METRIC', plan=query(COUNT)),
    dict(cat='date', q='今天取消未退费有多少笔', expectedValue=1, filter='create_time=2026-10-10', plan=query(COUNT+" AND o.create_time='2026-10-10'")),
    dict(cat='department', q='内科取消未退费笔数是多少', expectedValue=2, filter='dept=内科', plan=query(COUNT+" AND o.dept='内科'")),
    dict(cat='patient', q='患者甲取消未退费笔数是多少', expectedValue=1, filter='patient=甲', plan=query(COUNT+" AND o.patient='甲'")),
    dict(cat='group', q='按科室统计取消未退费笔数', expectedRows=[{'dept':'内科','n':2},{'dept':'外科','n':1}], filter='GROUP BY dept', plan=query(COUNT.replace('COUNT(*) AS n','o.dept, COUNT(*) AS n')+' GROUP BY o.dept ORDER BY o.dept')),
    dict(cat='comparison', q='取消未退费比昨天增加多少', expectedValue=0, filter='今日减昨日', plan=query("SELECT SUM(CASE WHEN o.create_time='2026-10-10' THEN 1 WHEN o.create_time='2026-10-09' THEN -1 ELSE 0 END) AS n FROM fee_detail f JOIN medical_order o ON f.order_id=o.order_id WHERE o.order_status='2' AND f.fee_status='1'")),
    dict(cat='ratio', q='检验撤销率现在多少', expectedValue=20, unit='%', filter='2/10*100', plan=query("SELECT 100.0 * SUM(CASE WHEN status='C' THEN 1 ELSE 0 END) / COUNT(*) AS n FROM lab_request")),
    dict(cat='plain', q='医嘱记录总数是多少', expectedValue=5, plan=query('SELECT COUNT(*) AS n FROM medical_order')),
    dict(cat='valid_assets', q='取消医嘱的规则是什么', expectCitations=['EVAL-RULE','EVAL-ACTION','EVAL-AXIOM'], plan=model(ruleCodes=['EVAL-RULE'],actionCodes=['EVAL-ACTION'],axiomCodes=['EVAL-AXIOM'])),
    dict(cat='fake_model', q='医嘱允许任意取消吗', expectInsufficient=True, plan=model(ruleCodes=['FAKE'])),
    dict(cat='fake_query', q='统计医嘱伪造规则结果', expectInsufficient=True, plan=query('SELECT COUNT(*) AS n FROM medical_order',ruleCodes=['FAKE'])),
    dict(cat='clipped', q='统计超长规则允许的医嘱', scenario='clipped', expectInsufficient=True, plan=model(ruleCodes=['EVAL-RULE'])),
    dict(cat='missing_condition', q='医嘱没有条件能取消吗', expectInsufficient=True, plan=model()),
    dict(cat='changed_metric', q='请问取消未退费有多少笔', scenario='changed', expectedValue=3, plan=query(COUNT)),
    dict(cat='ambiguous_amount', q='取消未退费费用多少', expectInsufficient=True, plan=model()),
    dict(cat='multiple', q='取消未退费笔数和出院人数是多少', expectInsufficient=True, plan=model()),
    dict(cat='period', q='出院人数是多少', expectInsufficient=True, plan=model()),
    dict(cat='precision', q='出院患者均次费用是多少', expectInsufficient=True, plan=model()),
    dict(cat='conflict', q='医嘱冲突规则能确认吗', scenario='conflict', expectInsufficient=True, plan=model(ruleCodes=['EVAL-RULE','EVAL-CONFLICT'],evidenceStatus='CONFLICT')),
    dict(cat='write', q='帮我给患者甲取消医嘱', expectInsufficient=True, plan=model()),
    dict(cat='export', q='导出药品价格表', expectedRows=[{'drug':'合成药品','price':12.5}], plan=query('SELECT drug, price FROM drug_price')),
    dict(cat='cs_card', q='取消未退费笔数怎么算', scene='CS', expectCard=None, plan=query(COUNT)),
]


def seed(engine, scenario):
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE medical_order(order_id TEXT, order_status TEXT, create_time TEXT, dept TEXT, patient TEXT)'))
        conn.execute(text("INSERT INTO medical_order VALUES ('O1','2','2026-10-10','内科','甲'),('O2','2','2026-10-09','内科','乙'),('O3','2','2026-08-01','外科','丙'),('O4','2','2026-10-10','外科','丁'),('O5','1','2026-10-10','内科','戊')"))
        conn.execute(text('CREATE TABLE fee_detail(order_id TEXT, fee_status TEXT)'))
        conn.execute(text("INSERT INTO fee_detail VALUES ('O1','1'),('O2','1'),('O3','1'),('O4','2'),('O5','1')"))
        conn.execute(text('CREATE TABLE lab_request(status TEXT)'))
        conn.execute(text("INSERT INTO lab_request VALUES ('C'),('C'),('N'),('N'),('N'),('N'),('N'),('N'),('N'),('N')"))
        conn.execute(text('CREATE TABLE drug_price(drug TEXT, price NUMERIC)'))
        conn.execute(text("INSERT INTO drug_price VALUES ('合成药品',12.5)"))
        if scenario == 'zero':
            conn.execute(text("UPDATE fee_detail SET fee_status='2'"))
    with Session(engine) as s:
        s.add_all([Concept(code='MEDICAL_ORDER',name='医嘱',status='PUBLISHED'), Concept(code='FEE_DETAIL',name='费用',status='PUBLISHED')])
        for table, columns in {'medical_order':['order_id','order_status','create_time','dept','patient'], 'fee_detail':['order_id','fee_status'], 'lab_request':['status'], 'drug_price':['drug','price']}.items():
            for column in columns:
                enums = {'2':'已取消'} if column=='order_status' else {'1':'正常'} if column=='fee_status' else None
                s.add(Mapping(ds_code='DS_HIS',table_name=table,column_name=column,concept_code='MEDICAL_ORDER' if table=='medical_order' else 'FEE_DETAIL',attr_code=column,confirmed=1,value_map=json.dumps(enums,ensure_ascii=False) if enums else None))
        s.add(Metric(metric_code='CANCEL_NOT_REFUND',name='取消未退费笔数',definition='变更口径' if scenario=='changed' else '医嘱已取消但费用状态仍为正常的明细笔数，计费一致性核心监控指标，正常应为0。',formula='COUNT(医嘱状态=已取消 AND 费用状态=正常)',ds_code='DS_HIS',probe_sql=PROBE,warn_threshold=0))
        s.add(Rule(rule_code='EVAL-RULE',name='取消联动退费',expression='限制'*2100 if scenario=='clipped' else '取消医嘱必须联动退费，但须核对触发条件。',status='PUBLISHED'))
        s.add(Action(action_code='EVAL-ACTION',name='取消医嘱',from_status='未执行',to_status='已取消',trigger_desc='医生确认',description='须核对退费条件',status='PUBLISHED'))
        s.add(Axiom(axiom_code='EVAL-AXIOM',subject='医嘱',predicate='关联',object='费用',description='取消须核对费用',status='PUBLISHED'))
        if scenario=='conflict':
            s.add(Rule(rule_code='EVAL-CONFLICT',name='冲突规则',expression='取消医嘱禁止退费',status='PUBLISHED'))
        s.commit()


@contextmanager
def fixture_session(item):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread':False})
    seed(engine, item.get('scenario'))
    original_key = settings.deepseek_api_key
    # 强制经过完整入口的路由分支；所有 chat 在本上下文内被替身截获。
    settings.deepseek_api_key = 'offline-stub-only'

    def chat(client, kind, system, prompt):
        response = 'SEMANTIC_QUERY' if kind=='CS_ROUTE' else json.dumps(item['plan'],ensure_ascii=False) if kind=='CS_SEMANTIC_PLAN' else None
        client.logs.log(kind, 'StubLLM', '合成评测', 0, True, None)
        return response

    def execute(svc, ds, sql):
        # 只替换数据库方言适配；仍由服务执行原有白名单、结果形态与引用管线。
        return [dict(r) for r in svc.session.execute(text(sql)).mappings().fetchmany(100)]

    def critic(session, system, prompt):
        LlmLogService(session).log('CS_SEMANTIC_CRITIQUE', 'StubLLM', '合成评测', 0, True, None)
        return '{"verdict":"OK"}'

    try:
        with Session(engine, expire_on_commit=False) as session, patch.object(DeepSeekClient,'chat',chat), patch.object(SemanticQaService,'execute',execute), patch.object(runtime,'critic_chat',critic):
            yield session
    finally:
        settings.deepseek_api_key = original_key
        engine.dispose()
