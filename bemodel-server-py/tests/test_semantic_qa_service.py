import pytest
from bemodel.cs.semantic import SemanticQaService
from bemodel.cs.sql_validation import validate_sql
from bemodel.core.exceptions import BizException
from bemodel.datasource.entities import Mapping
from bemodel.ontology.entities import Attribute, Concept

TABLES = {'fee_detail', 'medical_order', 'inpatient'}
COLUMNS = set('fee_id order_id inhos_no item_name amount fee_status order_status order_type create_time patient_name sex dept_code'.split())


class StubLLM:
    """按调用类型返回预设响应，记录 CS_SEMANTIC_PLAN 调用次数。"""

    def __init__(self, plan_responses, answer='已完成'):
        self.plan_responses = list(plan_responses)
        self.answer_text = answer
        self.plan_calls = 0

    def chat(self, call_type, system_prompt, user_prompt):
        if call_type == 'CS_SEMANTIC_PLAN':
            self.plan_calls += 1
            return self.plan_responses.pop(0)
        return self.answer_text


def seed_peis_ontology(session):
    """张三体检问题可命中的最小本体：概念+属性+映射。"""
    session.add(Concept(code='CHECK_REPORT', name='检查报告', domain_code='EXAM', status='PUBLISHED'))
    session.add(Attribute(concept_code='CHECK_REPORT', attr_code='exam_date', attr_name='体检时间', data_type='DATE'))
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='person_name',
                        concept_code='PATIENT', attr_code='name', confirmed=1, source='MANUAL'))
    session.commit()


QUERY_PLAN = ('{"mode":"QUERY","ds":"DS_PEIS",'
              '"sql":"SELECT person_name FROM peis_exam WHERE person_name LIKE \'%张三%\'",'
              '"semantics":"查张三的体检登记"}')
UNANSWERABLE_PLAN = '{"mode":"UNANSWERABLE","reason":"本体无体检概念"}'


@pytest.mark.parametrize('sql', [
    "SELECT item_name, amount FROM fee_detail WHERE fee_status = '1'",
    "SELECT item_name FROM fee_detail WHERE item_name = 'x; DROP TABLE fee_detail--'",
    'SELECT item_name FROM fee_detail -- WHERE 1=1; DELETE FROM fee_detail',
    "SELECT o.order_id, o.create_time FROM medical_order o WHERE o.order_status = '2'",
    'SELECT fee_status, COUNT(*) cnt, SUM(amount) total FROM fee_detail GROUP BY fee_status ORDER BY total DESC',
    "SELECT f.item_name, f.amount FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id WHERE o.order_status = '2' AND f.fee_status = '1'",
    "SELECT `item_name` FROM `fee_detail` WHERE `fee_status` = '1'",
])
def test_java_valid_queries(sql):
    assert validate_sql(sql, TABLES, COLUMNS) == sql+' LIMIT 100'


@pytest.mark.parametrize('sql', [
    'DELETE FROM fee_detail', 'UPDATE fee_detail SET amount = 0',
    'SELECT amount FROM fee_detail; DROP TABLE fee_detail',
    "SELECT amount INTO OUTFILE '/tmp/x' FROM fee_detail", 'SELECT * FROM user_passwords',
    'SELECT secret_col FROM fee_detail', 'SELECT item_name, secret_col FROM fee_detail',
    "SELECT item_name FROM fee_detail WHERE secret_col = '1'", 'SELECT f.secret_col FROM fee_detail f',
])
def test_java_rejected_queries(sql):
    with pytest.raises(BizException):
        validate_sql(sql, TABLES, COLUMNS)


def test_java_limit_clamping():
    assert validate_sql('SELECT item_name FROM fee_detail LIMIT 500', TABLES, COLUMNS).endswith('LIMIT 100')
    assert validate_sql('SELECT item_name FROM fee_detail LIMIT 20', TABLES, COLUMNS).endswith('LIMIT 20')


def test_enum_literal_uses_current_table_value_map(session):
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_item_result', column_name='abnormal',
                        concept_code='CHECK_REPORT', attr_code='abnormal',
                        value_map='{"1":"异常","0":"正常"}', confirmed=1, source='MANUAL'))
    session.commit()

    sql = ("SELECT COUNT(DISTINCT r.exam_no) AS abn_exam_cnt FROM peis_item_result r "
           "WHERE r.abnormal = 'Y' LIMIT 100")

    assert SemanticQaService(session).normalize_enum_literals('DS_PEIS', sql) == (
        "SELECT COUNT(DISTINCT r.exam_no) AS abn_exam_cnt FROM peis_item_result r "
        "WHERE r.abnormal = '1' LIMIT 100"
    )


def test_enum_literal_accepts_chinese_label(session):
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_item_result', column_name='abnormal',
                        concept_code='CHECK_REPORT', attr_code='abnormal',
                        value_map='{"1":"异常","0":"正常"}', confirmed=1, source='MANUAL'))
    session.commit()

    sql = "SELECT exam_no FROM peis_item_result WHERE abnormal = '异常'"

    assert SemanticQaService(session).normalize_enum_literals('DS_PEIS', sql) == (
        "SELECT exam_no FROM peis_item_result WHERE abnormal = '1'"
    )


def test_plan_query_retries_malformed_output(session):
    """首次输出非法 JSON 时重试一次，第二次合法即采用，不再直接落兜底。"""
    seed_peis_ontology(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(['不是JSON', QUERY_PLAN])

    plan = svc.plan_query('张三的体检做完了吗？')

    assert plan is not None and plan['mode'] == 'QUERY'
    assert svc.llm.plan_calls == 2


def test_unanswerable_guard_retries_on_coverage_hit(session, monkeypatch):
    """用词命中本体却拒答：带提示再规划一次，第二次 QUERY 正常出答案。"""
    seed_peis_ontology(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([UNANSWERABLE_PLAN, QUERY_PLAN])
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'person_name': '张三'}])

    result, recorded = svc.answer('张三的体检做完了吗？')

    assert result is not None and recorded is False
    assert result['answer'] == '已完成'
    assert svc.llm.plan_calls == 2
    assert any(e['label'] == '执行SQL' for e in result['evidence'])


def test_unanswerable_stands_without_coverage(session):
    """未命中本体词汇的拒答不重试，照常记缺口回落菜单。"""
    svc = SemanticQaService(session)
    svc.llm = StubLLM([UNANSWERABLE_PLAN])

    result, recorded = svc.answer('这个问题完全无关')

    assert result is None and recorded is True
    assert svc.llm.plan_calls == 1


def test_enum_mappings_tolerates_plain_text_value_map(session):
    """历史裸字典文本（0在检 1完成 2作废）也能参与问数枚举归一。"""
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='exam_status',
                        concept_code='CHECK_REPORT', attr_code='status',
                        value_map='0在检 1完成 2作废', confirmed=1, source='MANUAL'))
    session.commit()

    svc = SemanticQaService(session)
    assert svc.enum_mappings('DS_PEIS') == {
        ('peis_exam', 'exam_status'): {'0': '在检', '1': '完成', '2': '作废'}}
    assert svc.normalize_enum_literals(
        'DS_PEIS', "SELECT exam_no FROM peis_exam WHERE exam_status = '完成'"
    ) == "SELECT exam_no FROM peis_exam WHERE exam_status = '1'"
