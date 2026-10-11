"""资产问数边界回归：检查真实编排，不以资格函数或测试替身返回值掩盖误直查。"""
import json

import pytest

from bemodel.config import settings
from bemodel.cs import asset_context, metric_policy
from bemodel.cs.semantic import SemanticQaService
from bemodel.datasource.entities import Mapping
from bemodel.modeling.entities import Rule, Action
from test_semantic_asset_enhance import seed_metric, seed_assets, seed_his_mappings, StubLLM, query_plan


@pytest.fixture(autouse=True)
def enhancement(monkeypatch):
    monkeypatch.setattr(settings, 'semantic_asset_enhance', True)
    monkeypatch.setattr(settings, 'deepseek_api_key', '')


@pytest.mark.parametrize('overrides', [
    {'definition': '变更口径'}, {'formula': 'COUNT(全部医嘱)'},
    {'probe_sql': 'SELECT COUNT(*) FROM medical_order'}, {'ds_code': 'OTHER'}, {'name': ''}, {'name':'其他指标'},
])
def test_disqualified_metric_never_executes_probe(session, monkeypatch, overrides):
    seed_metric(session, **overrides)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan()], answer='正常规划')
    executed = []
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: executed.append(sql) or [{'cnt': 3}])
    result, _ = svc.answer('取消未退费有多少笔')
    assert svc.llm.plan_calls == 1 and result['intent'] == '语义查询'
    assert len(executed) == 1 and 'COUNT' not in executed[0]


@pytest.mark.parametrize('label,confirmed', [('未取消', 1), ('已取消', 0), ('取消', 1), (None, 1)])
def test_unconfirmed_or_changed_enum_blocks_direct(session, monkeypatch, label, confirmed):
    seed_metric(session)
    row = session.query(Mapping).filter_by(table_name='medical_order', column_name='order_status').one()
    row.value_map = json.dumps({'2': label}) if label else None
    row.confirmed = confirmed
    session.commit()
    svc = SemanticQaService(session)
    monkeypatch.setattr(svc, 'execute', lambda *args: pytest.fail('资格失效不得执行'))
    assert svc.metric_direct_answer('取消未退费有多少笔') is None


def test_recheck_failure_before_execution(session, monkeypatch):
    seed_metric(session)
    svc = SemanticQaService(session)
    verify = metric_policy.verify_qualified
    calls = []

    def checked(*args):
        calls.append(1)
        policy, row, reason = verify(*args)
        return (policy, row, '执行前已撤回') if len(calls) == 2 else (policy, row, reason)

    monkeypatch.setattr(metric_policy, 'verify_qualified', checked)
    monkeypatch.setattr(svc, 'execute', lambda *args: pytest.fail('复核失效不得执行'))
    assert svc.metric_direct_answer('取消未退费有多少笔') is None
    assert len(calls) == 2


@pytest.mark.parametrize('question', ['取消未退费费用多少', '取消未退费的费用有多少', '取消未退费有多少', '取消当前未退费有多少笔'])
def test_ambiguous_value_or_embedded_modifier_not_direct(question):
    assert metric_policy.match_question(question) is None


@pytest.mark.parametrize('clipped', [False, True])
@pytest.mark.parametrize('mode', ['QUERY', 'MODEL_ANSWER'])
def test_empty_snapshot_rejects_fake_citations(session, monkeypatch, clipped, mode):
    if clipped:
        seed_assets(session)
        monkeypatch.setattr(asset_context, 'TOTAL_CHAR_BUDGET', 0)
    else:
        seed_his_mappings(session)
    svc = SemanticQaService(session)
    plan = query_plan(ruleCodes=['RULE-X']) if mode == 'QUERY' else json.dumps(dict(
        mode=mode, conclusion='可以', ruleCodes=['RULE-X']))
    svc.llm = StubLLM([plan, plan], answer='错误结论')
    monkeypatch.setattr(svc, 'execute', lambda *args: pytest.fail('失效引用不得执行'))
    result, missed = svc.answer('测试问题')
    assert not missed and '不足以确认' in result['answer']
    assert svc.llm.plan_calls == 2 and not svc.llm.answer_prompts


def test_query_to_model_retry_does_not_retry_twice(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['FAKE']), json.dumps(dict(
        mode='MODEL_ANSWER', conclusion='可以', ruleCodes=['FAKE']))])
    monkeypatch.setattr(svc, 'execute', lambda *args: pytest.fail('不得执行'))
    result, missed = svc.answer('测试问题')
    assert not missed and '不足以确认' in result['answer'] and svc.llm.plan_calls == 2


def test_query_answer_receives_complete_evidence(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['RULE-X'], actionCodes=['ACT-X'])])
    monkeypatch.setattr(svc, 'execute', lambda *args: [{'order_id': 'O1'}])
    result, _ = svc.answer('查询医嘱')
    prompt = svc.llm.answer_prompts[0]
    for e in result['evidence']:
        if e['label'].startswith('依据'):
            assert e['value'] in prompt
    assert '医生取消' in prompt and '必须联动退费' in prompt


def test_total_budget_includes_headers_and_separators(session, monkeypatch):
    seed_assets(session)
    original = asset_context.build_asset_snapshot(session, '医嘱')
    for budget in (0, 1, 80, len(original.text) - 1, len(original.text)):
        monkeypatch.setattr(asset_context, 'TOTAL_CHAR_BUDGET', budget)
        snap = asset_context.build_asset_snapshot(session, '医嘱')
        assert len(snap.text) <= budget
        assert len(snap.entries) + sum(snap.omitted.values()) == 3
        assert all('\n' + e.line in snap.text for e in snap.entries)


def test_codes_are_scoped_by_type_and_routes_encoded(session):
    seed_assets(session)
    rule = session.query(Rule).filter_by(rule_code='RULE-X').one()
    action = session.query(Action).filter_by(action_code='ACT-X').one()
    rule.rule_code = action.action_code = 'SAME&other=1'
    session.commit()
    snap = asset_context.build_asset_snapshot(session, '医嘱')
    valid, invalid, error = asset_context.verify_citations(session, snap, {
        'ruleCodes': [rule.rule_code], 'actionCodes': [action.action_code]})
    assert len(valid) == 2 and not invalid and not error
    assert all('assetCode=SAME%26other%3D1' in e.route for e in valid)


def test_duplicate_overlong_array_rejected(session):
    seed_assets(session)
    snap = asset_context.build_asset_snapshot(session, '医嘱')
    valid, _, error = asset_context.verify_citations(session, snap, {
        'ruleCodes': ['RULE-X'] * (asset_context.MAX_CITED_CODES + 1)})
    assert not valid and '上限' in error


def test_switch_off_does_not_read_enhancement_assets(session, monkeypatch):
    monkeypatch.setattr(settings, 'semantic_asset_enhance', False)
    monkeypatch.setattr(asset_context, 'build_asset_snapshot', lambda *args: pytest.fail('开关关闭不能查资产'))
    monkeypatch.setattr(metric_policy, 'verify_qualified', lambda *args: pytest.fail('开关关闭不能查指标'))
    monkeypatch.setattr(asset_context, 'verify_citations', lambda *args: pytest.fail('开关关闭不能核验引用'))
    svc = SemanticQaService(session)
    svc.llm = StubLLM([json.dumps(dict(mode='MODEL_ANSWER', conclusion='旧行为', ruleCodes=['FAKE']))], answer='旧回答')
    result, _ = svc.answer('取消未退费有多少笔')
    assert result['answer'] == '旧回答' and 'citations' not in result


@pytest.mark.parametrize('mode',['QUERY','MODEL_ANSWER'])
def test_asset_changes_during_probe_do_not_reach_answer(session,monkeypatch,mode):
    from sqlalchemy import update
    seed_assets(session)
    svc=SemanticQaService(session)
    plan=query_plan(ruleCodes=['RULE-X']) if mode=='QUERY' else json.dumps(dict(
        mode=mode,conclusion='可以',ds='DS_HIS',verifySql='SELECT order_id FROM medical_order',ruleCodes=['RULE-X']))
    svc.llm=StubLLM([plan],answer='不应输出')
    # 保留旧实体引用，验证 ORM identity map 不会掩盖数据库中的内容变化。
    cached=session.query(Rule).filter_by(rule_code='RULE-X').one()
    def execute(*args):
        session.execute(update(Rule).where(Rule.rule_code=='RULE-X').values(expression='新限制').execution_options(synchronize_session=False))
        session.commit()
        assert cached.expression != '新限制'
        return [{'order_id':'O1'}]
    monkeypatch.setattr(svc,'execute',execute)
    result,_=svc.answer('测试')
    assert '不足以确认' in result['answer'] and not svc.llm.answer_prompts
    assert 'citations' not in result


def test_structured_constraint_changes_invalidate_citation(session):
    seed_assets(session)
    rule=session.query(Rule).filter_by(rule_code='RULE-X').one()
    rule.expr_json='{"condition":"A"}'
    session.commit()
    snap=asset_context.build_asset_snapshot(session,'规则')
    assert rule.expr_json in snap.text
    rule.expr_json='{"condition":"B"}'
    session.commit()
    valid,invalid,_=asset_context.verify_citations(session,snap,{'ruleCodes':['RULE-X']})
    assert not valid and invalid==['RULE-X']


@pytest.mark.parametrize('mode',['QUERY','MODEL_ANSWER'])
def test_explicit_conflict_with_valid_codes_is_insufficient(session,monkeypatch,mode):
    seed_assets(session)
    svc=SemanticQaService(session)
    plan=query_plan(ruleCodes=['RULE-X'],evidenceStatus='CONFLICT') if mode=='QUERY' else json.dumps(dict(
        mode=mode,conclusion='可以',ruleCodes=['RULE-X'],evidenceStatus='CONFLICT'))
    svc.llm=StubLLM([plan],answer='不应输出')
    monkeypatch.setattr(svc,'execute',lambda *args:pytest.fail('冲突不得查询'))
    result,missed=svc.answer('测试')
    assert not missed and '不足以确认' in result['answer'] and not svc.llm.answer_prompts
