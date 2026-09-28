import pytest
from bemodel.cs.sql_validation import validate_sql
from bemodel.core.exceptions import BizException

TABLES = {'fee_detail', 'medical_order', 'inpatient'}
COLUMNS = set('fee_id order_id inhos_no item_name amount fee_status order_status order_type create_time patient_name sex dept_code'.split())


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


def test_planned_query_executes_mysql_and_caps_output(mysql_session, monkeypatch):
    import json
    from bemodel.cs.semantic import SemanticQaService
    service = SemanticQaService(mysql_session)
    calls = []
    def chat(kind, system, prompt):
        calls.append((kind, prompt))
        return json.dumps(dict(mode='QUERY', ds='DS_HIS', sql='SELECT order_id FROM medical_order LIMIT 500',
            semantics='医嘱清单')) if kind == 'CS_SEMANTIC_PLAN' else None
    monkeypatch.setattr(service.llm, 'chat', chat)
    answer, missed = service.answer('医嘱清单', analytics=True)
    assert not missed and answer['router'] == 'SEMANTIC'
    assert len(answer['rows']) == 20
    assert answer['evidence'][0]['value'].endswith('LIMIT 100')
    assert answer['evidence'][2]['value'] == '100（展示前20行）'
    assert [kind for kind, _ in calls] == ['CS_SEMANTIC_PLAN', 'CS_SEMANTIC_ANSWER']
    assert '结果行数：100' in calls[1][1]


def test_model_answer_uses_real_verification_probe(mysql_session, monkeypatch):
    import json
    from bemodel.cs.semantic import SemanticQaService
    service = SemanticQaService(mysql_session)
    def chat(kind, system, prompt):
        return json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='可以查询医嘱',
            semantics='MEDICAL_ORDER 通过映射访问业务数据', verifySql='SELECT COUNT(*) cnt FROM medical_order')) if kind == 'CS_SEMANTIC_PLAN' else None
    monkeypatch.setattr(service.llm, 'chat', chat)
    answer, missed = service.answer('可以查询医嘱吗？')
    assert not missed and answer['router'] == 'SEMANTIC'
    assert '验证探针返回：{cnt=' in answer['answer']
    assert answer['evidence'][1]['value'].startswith('SELECT COUNT(*) cnt')
    assert any('MEDICAL_ORDER' in link['route'] for link in answer['links'])


@pytest.mark.parametrize('mode', ['UNANSWERABLE', 'UNSAFE_QUERY'])
def test_unanswerable_and_rejected_plan_record_miss(mysql_session, monkeypatch, mode):
    import json
    from uuid import uuid4
    from bemodel.cs.semantic import SemanticQaService
    from bemodel.core.base_dao import BaseDAO
    from bemodel.ontology.entities import OntologyMiss
    question = '验收规划边界' + uuid4().hex[:12]
    service = SemanticQaService(mysql_session)
    plan = dict(mode='UNANSWERABLE') if mode == 'UNANSWERABLE' else dict(mode='QUERY',ds='DS_HIS',sql='DELETE FROM medical_order')
    monkeypatch.setattr(service.llm, 'chat', lambda *args: json.dumps(plan))
    def forbidden(*args):
        pytest.fail('Rejected model SQL must never execute')
    monkeypatch.setattr(service, 'execute', forbidden)
    dao = BaseDAO(mysql_session, OntologyMiss)
    try:
        result, missed = service.answer(question, analytics=True)
        assert result is None and missed
        row = dao.select_one(OntologyMiss.term == question)
        assert row.source == 'QA_ASK' and row.count == 1
    finally:
        dao.delete(OntologyMiss.term == question)
