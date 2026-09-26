"""校验纠错智能体：触发门控、接受条件、降级路径与端到端修正。

智能体 LLM 调用经 monkeypatch 注入判定，不触达 MAF/DeepSeek；
runtime 适配层的降级与审计见 test_agents_runtime.py。
"""

import pytest
from bemodel.agents.critic import describe_result, improved, parse_verdict, suspicious_result
from bemodel.cs.semantic import SemanticQaService
from bemodel.datasource.entities import Mapping
from bemodel.ontology.entities import Attribute, Concept


class StubLLM:
    """规划器按预设返回，答案组织固定文本。"""

    def __init__(self, plan_response, answer='已完成'):
        self.plan_response = plan_response
        self.answer_text = answer

    def chat(self, call_type, system_prompt, user_prompt):
        return self.plan_response if call_type == 'CS_SEMANTIC_PLAN' else self.answer_text


def seed_exam_mappings(session):
    """体检表映射：姓名 + 状态列（无 value_map，确定性改写层不会碰 exam_status）。"""
    session.add(Concept(code='PATIENT', name='患者', domain_code='EXAM', status='PUBLISHED'))
    session.add(Concept(code='CHECK_REPORT', name='检查报告', domain_code='EXAM', status='PUBLISHED'))
    session.add(Attribute(concept_code='PATIENT', attr_code='name', attr_name='姓名', data_type='STRING'))
    session.add(Attribute(concept_code='CHECK_REPORT', attr_code='exam_status', attr_name='体检状态', data_type='STRING'))
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='person_name',
                        concept_code='PATIENT', attr_code='name', confirmed=1, source='MANUAL'))
    session.add(Mapping(ds_code='DS_PEIS', table_name='peis_exam', column_name='exam_status',
                        concept_code='CHECK_REPORT', attr_code='exam_status', confirmed=1, source='MANUAL'))
    session.commit()


def fake_execute(scripted_results, sample_rows=None, calls=None):
    """替身 execute：样例探针（SELECT * FROM）返回固定样例，业务 SQL 按脚本顺序出结果。"""
    def execute(ds, sql):
        if calls is not None:
            calls.append(sql)
        if sql.startswith('SELECT * FROM'):
            return sample_rows or []
        return scripted_results.pop(0)
    return execute


# ---------- 判定纯函数 ----------

def test_suspicious_result_gate():
    assert suspicious_result([]) is True                       # 明细 0 行
    assert suspicious_result([{'n': 0}]) is True               # COUNT=0
    assert suspicious_result([{'n': 5}]) is False
    assert suspicious_result([{'n': 0}, {'n': 1}]) is False    # 多行明细
    assert suspicious_result([{'a': 0, 'b': 0}]) is False      # 多列非聚合形态
    assert suspicious_result([{'name': '张三'}]) is False


def test_improved_accept_condition():
    assert improved([], [{'name': '张三'}]) is True            # 0行 → 有数据：接受
    assert improved([{'n': 0}], [{'n': 5}]) is True            # 计0 → 计N：接受
    assert improved([], []) is False                           # 仍无数据：拒绝
    assert improved([{'n': 0}], [{'n': 0}]) is False
    assert improved([{'n': 5}], [{'n': 9}]) is False           # 原本正常：不进入纠错路径


def test_describe_result():
    assert describe_result([]) == '0 行（没有任何记录）'
    assert describe_result([{'n': 0}]) == '返回 1 行：n=0'
    assert describe_result([{'a': 1, 'b': 'x'}]) == '1 行，首行：a=1; b=x'


def test_parse_verdict_variants():
    assert parse_verdict(None) is None                         # LLM 降级
    assert parse_verdict('') is None
    assert parse_verdict('前言 {"verdict":"OK"} 后语')['verdict'] == 'OK'
    assert parse_verdict('```json\n{"verdict":"fix","correctedSql":" SELECT 1 ","reason":" r "}\n```') == {
        'verdict': 'FIX', 'correctedSql': 'SELECT 1', 'reason': 'r'}
    assert parse_verdict('不是JSON')['verdict'] == 'PARSE_FAIL'
    assert parse_verdict('[1,2]')['verdict'] == 'PARSE_FAIL'


# ---------- 编排：触发 / 修正 / 拒绝 / 降级 ----------

ENUM_PLAN = ('{"mode":"QUERY","ds":"DS_PEIS",'
             '"sql":"SELECT person_name FROM peis_exam WHERE exam_status = \'完成\'",'
             '"semantics":"查状态为完成的体检登记"}')


def test_agent_fixes_enum_chinese_literal(session, monkeypatch):
    """端到端（对齐方案实验④）：无值映射时中文直查 0 行 → 智能体改码值 → 结果改善被采用。"""
    seed_exam_mappings(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(ENUM_PLAN)
    judge_calls = []
    monkeypatch.setattr(svc.critic, 'judge', lambda q, ctx, sql, desc, samples:
                        judge_calls.append(dict(q=q, sql=sql, desc=desc, samples=samples)) or
                        {'verdict': 'FIX',
                         'correctedSql': "SELECT person_name FROM peis_exam WHERE exam_status = '1'",
                         'reason': "库里存码值'1'表示完成"})
    monkeypatch.setattr(svc, 'execute', fake_execute(
        [[], [{'person_name': '张三'}]], sample_rows=[{'person_name': '张三', 'exam_status': '1'}]))

    result, recorded = svc.answer('体检状态为完成的患者名单')

    assert recorded is False
    executed = next(e['value'] for e in result['evidence'] if e['label'] == '执行SQL')
    assert "exam_status = '1'" in executed
    assert result['rows'] == [{'person_name': '张三'}]
    assert len(result['corrections']) == 1
    fix = result['corrections'][0]
    assert "exam_status = '完成'" in fix['before'] and "exam_status = '1'" in fix['after']
    assert fix['reason'].startswith('库里存码值')
    # 智能体拿到的证据：可疑结果描述 + 真实样例
    assert judge_calls[0]['desc'] == '0 行（没有任何记录）'
    assert 'peis_exam' in judge_calls[0]['samples'] and 'exam_status' in judge_calls[0]['samples']


def test_agent_not_triggered_on_normal_result(session, monkeypatch):
    seed_exam_mappings(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(ENUM_PLAN)

    def no_way(*args, **kwargs):
        raise AssertionError('结果正常时智能体不应被调用')
    monkeypatch.setattr(svc.critic, 'judge', no_way)
    monkeypatch.setattr(svc, 'execute', fake_execute([[{'person_name': '张三'}]]))

    result, recorded = svc.answer('体检状态为完成的患者名单')

    assert recorded is False and result['corrections'] == []


def test_agent_correction_rejected_without_improvement(session, monkeypatch):
    """修正后仍 0 行：不接受，保留原 SQL 与原结果。"""
    seed_exam_mappings(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(ENUM_PLAN)
    monkeypatch.setattr(svc.critic, 'judge', lambda *a, **k: {
        'verdict': 'FIX', 'correctedSql': "SELECT person_name FROM peis_exam WHERE exam_status = '1'",
        'reason': '码值'})
    monkeypatch.setattr(svc, 'execute', fake_execute([[], []]))

    result, _ = svc.answer('体检状态为完成的患者名单')

    assert result['corrections'] == []
    executed = next(e['value'] for e in result['evidence'] if e['label'] == '执行SQL')
    assert "exam_status = '完成'" in executed


def test_agent_correction_rejected_by_whitelist(session, monkeypatch):
    """修正 SQL 引用白名单外表：validate_sql 拒绝，保留原结果不崩溃。"""
    seed_exam_mappings(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(ENUM_PLAN)
    monkeypatch.setattr(svc.critic, 'judge', lambda *a, **k: {
        'verdict': 'FIX', 'correctedSql': 'SELECT person_name FROM user_passwords', 'reason': '越权'})
    monkeypatch.setattr(svc, 'execute', fake_execute([[]]))

    result, _ = svc.answer('体检状态为完成的患者名单')

    assert result['corrections'] == []
    executed = next(e['value'] for e in result['evidence'] if e['label'] == '执行SQL')
    assert 'peis_exam' in executed


def test_agent_degrades_on_critic_failure(session, monkeypatch):
    """智能体降级（None / PARSE_FAIL / OK）一律保留原结果。"""
    seed_exam_mappings(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(ENUM_PLAN)
    for verdict in (None, {'verdict': 'PARSE_FAIL'}, {'verdict': 'OK'}):
        monkeypatch.setattr(svc.critic, 'judge', lambda *a, **k: verdict)
        monkeypatch.setattr(svc, 'execute', fake_execute([[]]))
        result, _ = svc.answer('体检状态为完成的患者名单')
        assert result['corrections'] == []
        assert "exam_status = '完成'" in next(e['value'] for e in result['evidence'] if e['label'] == '执行SQL')


def test_agent_exits_after_accepted_fix(session, monkeypatch):
    """接受条件使修正结果不再可疑：即使 critic 总想再修，也只判定一轮（MAX_AGENT_FIXES 为防御上限）。"""
    seed_exam_mappings(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM(ENUM_PLAN)
    judge_calls = []
    monkeypatch.setattr(svc.critic, 'judge', lambda *a, **k: judge_calls.append(1) or {
        'verdict': 'FIX', 'correctedSql': "SELECT person_name FROM peis_exam WHERE exam_status = '1'",
        'reason': '码值'})
    monkeypatch.setattr(svc, 'execute', fake_execute([[], [{'person_name': '张三'}]]))

    result, _ = svc.answer('体检状态为完成的患者名单')

    assert len(judge_calls) == 1 and len(result['corrections']) == 1
