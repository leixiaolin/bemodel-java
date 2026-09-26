import pytest
from bemodel.cs.semantic import SemanticQaService
from bemodel.cs.sql_validation import validate_sql
from bemodel.core.exceptions import BizException
from bemodel.datasource.entities import Mapping
from bemodel.ontology.entities import Attribute, Concept, Relation, Term

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


def seed_id_card_mapping(session):
    """身份证号列映射（属性名含「身份证」）+ 姓名列映射。"""
    session.add(Concept(code='PATIENT', name='患者', domain_code='EXAM', status='PUBLISHED'))
    session.add(Attribute(concept_code='PATIENT', attr_code='id_card', attr_name='身份证号', data_type='STRING'))
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='id_card',
                        concept_code='PATIENT', attr_code='id_card', confirmed=1, source='MANUAL'))
    session.commit()


def test_id_card_year_prefix_rewritten_to_contains(session):
    """身份证列按出生年份前缀匹配（LIKE '1988%'）改写为包含匹配（'%1988%'）：
    证号开头是6位地区码、出生年份在第7-14位，前缀匹配永远查不到数据。"""
    seed_id_card_mapping(session)
    svc = SemanticQaService(session)

    sql = "SELECT exam_no FROM peis_exam WHERE id_card LIKE '1988%' LIMIT 100"
    assert svc.fix_id_card_year_prefix('DS_PEIS', sql) == (
        "SELECT exam_no FROM peis_exam WHERE id_card LIKE '%1988%' LIMIT 100")

    sql = "SELECT e.exam_no FROM peis_exam e WHERE e.id_card LIKE '1988%' LIMIT 100"
    assert svc.fix_id_card_year_prefix('DS_PEIS', sql) == (
        "SELECT e.exam_no FROM peis_exam e WHERE e.id_card LIKE '%1988%' LIMIT 100")

    # 非身份证列的前缀匹配不动
    sql = "SELECT exam_no FROM peis_exam WHERE exam_no LIKE '1988%' LIMIT 100"
    assert svc.fix_id_card_year_prefix('DS_PEIS', sql) == sql


def test_answer_rewrites_id_card_year_prefix(session, monkeypatch):
    """端到端：LLM 仍生成 LIKE '1988%' 时，执行SQL证据里的条件已是 '%1988%'。"""
    seed_id_card_mapping(session)
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='person_name',
                        concept_code='PATIENT', attr_code='name', confirmed=1, source='MANUAL'))
    session.commit()
    svc = SemanticQaService(session)
    svc.llm = StubLLM(['{"mode":"QUERY","ds":"DS_PEIS",'
                       '"sql":"SELECT person_name FROM peis_exam WHERE id_card LIKE \'1988%\'",'
                       '"semantics":"按身份证出生年份1988查体检报告"}'])
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'person_name': '张三'}])

    result, recorded = svc.answer('1988年出生的患者体检报告')

    assert result is not None and recorded is False
    executed = next(e['value'] for e in result['evidence'] if e['label'] == '执行SQL')
    assert "id_card LIKE '%1988%'" in executed


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


def test_fill_parse_marks_used_vs_adjacent_relations(session):
    """关系面板标注：仅当关系两端概念都被本次 SQL 用到的表映射到才标 used，
    否则是命中概念在本体中的相邻关系（如 医嘱—生成检查报告→检查报告）。"""
    session.add(Concept(code='MEDICAL_ORDER', name='医嘱', domain_code='EXAM', status='PUBLISHED'))
    session.add(Concept(code='CHECK_REPORT', name='检查报告', domain_code='EXAM', status='PUBLISHED'))
    session.add(Relation(from_concept='MEDICAL_ORDER', to_concept='CHECK_REPORT', relation_name='生成检查报告'))
    session.commit()

    svc = SemanticQaService(session)
    # 单表查询只用到 CHECK_REPORT → 医嘱这条关系只是本体相邻
    result = {}
    svc.fill_parse(result, '上个月体检异常有多少人次 查上个月检查报告异常人次', ['CHECK_REPORT'])
    assert [h['code'] for h in result['matchedConcepts']] == ['CHECK_REPORT']
    assert len(result['relations']) == 1
    rel = result['relations'][0]
    assert rel['fromName'] == '医嘱' and rel['toName'] == '检查报告'
    assert rel['used'] is False

    # 两端概念都被查询用到 → 标为本次查询
    result = {}
    svc.fill_parse(result, '上个月体检异常有多少人次 查上个月检查报告异常人次',
                   ['CHECK_REPORT', 'MEDICAL_ORDER'])
    assert result['relations'][0]['used'] is True


def test_fill_parse_falls_back_to_used_concepts(session):
    """问题用词（体检/客户）与概念名（检查报告/患者）对不上：名称匹配 0 命中时，
    兜底计入 SQL 实际用到表所映射的概念，关系邻域不再空面板。"""
    for code, name in [('CHECK_REPORT', '检查报告'), ('PATIENT', '患者'),
                       ('MEDICAL_ORDER', '医嘱'), ('INP_VISIT', '住院就诊')]:
        session.add(Concept(code=code, name=name, domain_code='EXAM', status='PUBLISHED'))
    session.add(Relation(from_concept='MEDICAL_ORDER', to_concept='CHECK_REPORT', relation_name='生成检查报告'))
    session.add(Relation(from_concept='PATIENT', to_concept='INP_VISIT', relation_name='发生就诊'))
    session.commit()

    result = {}
    SemanticQaService(session).fill_parse(result, '最早体检的客户是谁 按体检时间升序取第一条',
                                          ['PATIENT', 'CHECK_REPORT'])

    assert [(h['code'], h['match']) for h in result['matchedConcepts']] == [
        ('PATIENT', '映射'), ('CHECK_REPORT', '映射')]
    assert {(r['from'], r['to']) for r in result['relations']} == {
        ('MEDICAL_ORDER', 'CHECK_REPORT'), ('PATIENT', 'INP_VISIT')}
    assert all(r['used'] is False for r in result['relations'])


def test_fill_parse_skips_unpublished_used_concepts(session):
    """映射 confirmed 不要求概念已发布：未发布概念不进解析面板。"""
    session.add(Concept(code='DRAFT_X', name='草稿概念', domain_code='EXAM', status='DRAFT'))
    session.commit()

    result = {}
    SemanticQaService(session).fill_parse(result, '最早体检的客户是谁', ['DRAFT_X'])

    assert result['matchedConcepts'] == [] and result['relations'] == []


def test_fill_parse_matches_term_alias(session):
    """术语层：bm_term 里 客户→患者 这类叫法命中问题用词（match='术语'）。"""
    session.add(Concept(code='PATIENT', name='患者', domain_code='EXAM', status='PUBLISHED'))
    session.commit()
    svc = SemanticQaService(session)

    result = {}
    svc.fill_parse(result, '最早体检的客户是谁', ())
    assert result['matchedConcepts'] == []

    session.add(Term(term='客户', concept_code='PATIENT', source_product='PEIS', term_type='ALIAS'))
    session.commit()
    result = {}
    svc.fill_parse(result, '最早体检的客户是谁', ())
    assert result['matchedConcepts'] == [dict(code='PATIENT', name='患者', match='术语')]
    assert result['relations'] == []


def test_fill_parse_layer_priority(session):
    """同一概念多层命中只保留最高优先级：名称 > 术语 > 映射。"""
    session.add(Concept(code='PATIENT', name='患者', domain_code='EXAM', status='PUBLISHED'))
    session.add(Term(term='客户', concept_code='PATIENT', source_product='PEIS', term_type='ALIAS'))
    session.commit()
    svc = SemanticQaService(session)

    result = {}
    svc.fill_parse(result, '住院患者（客户）名单', ['PATIENT'])
    assert result['matchedConcepts'] == [dict(code='PATIENT', name='患者', match='名称')]

    result = {}
    svc.fill_parse(result, '客户名单', ['PATIENT'])
    assert result['matchedConcepts'] == [dict(code='PATIENT', name='患者', match='术语')]


def test_answer_parse_panel_falls_back_to_mapped_concepts(session, monkeypatch):
    """端到端：问「最早体检的客户是谁」用词与概念名不一致，答案正常返回，
    解析面板兜底展示 SQL 实际用到表（peis_exam）所映射的概念。"""
    session.add(Concept(code='CHECK_REPORT', name='检查报告', domain_code='EXAM', status='PUBLISHED'))
    session.add(Concept(code='PATIENT', name='患者', domain_code='EXAM', status='PUBLISHED'))
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='person_name',
                        concept_code='PATIENT', attr_code='name', confirmed=1, source='MANUAL'))
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='exam_date',
                        concept_code='CHECK_REPORT', attr_code='exam_date', confirmed=1, source='MANUAL'))
    session.commit()
    svc = SemanticQaService(session)
    svc.llm = StubLLM(['{"mode":"QUERY","ds":"DS_PEIS",'
                       '"sql":"SELECT person_name FROM peis_exam",'
                       '"semantics":"按体检时间最早一条"}'])
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'person_name': '钱七'}])

    result, recorded = svc.answer('最早体检的客户是谁')

    assert result is not None and recorded is False
    assert {(h['code'], h['match']) for h in result['matchedConcepts']} == {
        ('PATIENT', '映射'), ('CHECK_REPORT', '映射')}
