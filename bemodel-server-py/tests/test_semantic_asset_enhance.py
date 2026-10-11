"""智能问数增强（资产注入/指标直查/引用核验）测试。

sqlite+StubLLM 覆盖设计方案 8.1 的开关、资产选择、准入、语义边界、
执行护栏、结果类型、引用核验、依据不足、QUERY/critic 与完整入口；
mysql_session 部分在 13317 隔离库核对真实业务数值与种子资产。
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.cs import asset_context, metric_policy
from bemodel.cs.semantic import SemanticQaService
from bemodel.datasource.entities import Mapping
from bemodel.modeling.entities import Action, Axiom, Rule
from bemodel.ontology.entities import Concept, Metric

PROBE_SQL = ("SELECT COUNT(*) FROM fee_detail f JOIN medical_order o ON f.order_id = o.order_id "
             "WHERE o.order_status = '2' AND f.fee_status = '1'")
METRIC_DEFINITION = '医嘱已取消但费用状态仍为正常的明细笔数，计费一致性核心监控指标，正常应为0。'
METRIC_FORMULA = 'COUNT(医嘱状态=已取消 AND 费用状态=正常)'


@pytest.fixture(autouse=True)
def enable_enhancement(monkeypatch):
    monkeypatch.setattr(settings, 'semantic_asset_enhance', True)
    monkeypatch.setattr(settings, 'deepseek_api_key', '')


class StubLLM:
    """按调用类型返回预设响应；answer=None 模拟作答降级（走确定性模板）。"""

    def __init__(self, plan_responses, answer=None):
        self.plan_responses = list(plan_responses)
        self.answer_text = answer
        self.plan_calls = 0
        self.plan_prompts = []
        self.answer_prompts = []

    def chat(self, call_type, system_prompt, user_prompt):
        if call_type == 'CS_SEMANTIC_PLAN':
            self.plan_calls += 1
            self.plan_prompts.append(user_prompt)
            return self.plan_responses.pop(0)
        self.answer_prompts.append(user_prompt)
        return self.answer_text


def seed_his_mappings(session):
    """DS_HIS confirmed 映射白名单：探针与测试 QUERY 计划所需的表/列/枚举码表。"""
    session.add(Mapping(ds_code='DS_HIS', table_name='medical_order', column_name='order_id',
                        concept_code='MEDICAL_ORDER', attr_code='order_id', confirmed=1, source='MANUAL'))
    session.add(Mapping(ds_code='DS_HIS', table_name='medical_order', column_name='order_status',
                        concept_code='MEDICAL_ORDER', attr_code='status',
                        value_map='{"0":"未执行","1":"已执行","2":"已取消"}', confirmed=1, source='MANUAL'))
    session.add(Mapping(ds_code='DS_HIS', table_name='fee_detail', column_name='order_id',
                        concept_code='FEE_DETAIL', attr_code='order_id', confirmed=1, source='MANUAL'))
    session.add(Mapping(ds_code='DS_HIS', table_name='fee_detail', column_name='fee_status',
                        concept_code='FEE_DETAIL', attr_code='status',
                        value_map='{"1":"正常","2":"已退费"}', confirmed=1, source='MANUAL'))
    session.commit()


def seed_metric(session, warn_threshold=0, **overrides):
    """与资格清单核对基准逐字节一致的最小指标资产 + 探针所需 confirmed 映射。"""
    row = dict(metric_code='CANCEL_NOT_REFUND', name='取消未退费笔数',
               definition=METRIC_DEFINITION, formula=METRIC_FORMULA,
               concept_code='FEE_DETAIL', owner='陈财务', ds_code='DS_HIS',
               probe_sql=PROBE_SQL, warn_threshold=warn_threshold)
    row.update(overrides)
    session.add(Metric(**row))
    seed_his_mappings(session)


def seed_assets(session):
    """一组已发布资产 + 一条 REVIEW 规则（状态过滤反例）+ 查询白名单映射。"""
    seed_his_mappings(session)
    session.add(Concept(code='MEDICAL_ORDER', name='医嘱', domain_code='HIS', status='PUBLISHED'))
    session.add(Concept(code='FEE_DETAIL', name='费用明细', domain_code='HIS', status='PUBLISHED'))
    session.add(Rule(rule_code='RULE-X', name='取消医嘱不得计费', concept_code='FEE_DETAIL', rule_type='约束',
                     expression='医嘱状态=已取消 的明细，其费用状态必须=已退费。', status='PUBLISHED', version=1))
    session.add(Rule(rule_code='RULE-REVIEW', name='评审中规则', concept_code='FEE_DETAIL', rule_type='约束',
                     expression='未发布内容。', status='REVIEW', version=1))
    session.add(Axiom(axiom_code='AX-X', subject='医嘱', predicate='产生', object='费用明细',
                      axiom_type='因果', description='医嘱执行必然产生费用；取消必须联动退费', status='PUBLISHED'))
    session.add(Action(action_code='ACT-X', name='取消医嘱', concept_code='MEDICAL_ORDER',
                       from_status='未执行,已执行', to_status='已取消', trigger_desc='医生取消',
                       description='必须联动退费', status='PUBLISHED', version=1))
    session.commit()


def query_plan(sql="SELECT order_id FROM medical_order WHERE order_status = '2'", **extra):
    plan = dict(mode='QUERY', ds='DS_HIS', sql=sql, semantics='测试查询')
    plan.update(extra)
    return json.dumps(plan)


# ---------- 开关 ----------

def test_switch_off_disables_all_lines(session, monkeypatch):
    """关闭增强：不注入资产段/补充指令、不触发指标直查、不产生 citations。"""
    monkeypatch.setattr(settings, 'semantic_asset_enhance', False)
    seed_assets(session)
    seed_metric(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan()], answer='已完成')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'order_id': 'O1'}])

    result, recorded = svc.answer('取消未退费有多少笔？')

    assert result is not None and recorded is False
    assert svc.llm.plan_calls == 1                      # 走了规划，直查未触发
    assert '取消未退费' not in result['intent']
    assert 'citations' not in result
    assert '【业务规则】' not in svc.llm.plan_prompts[0]
    assert '补充规则' not in svc.llm.plan_prompts[0]


# ---------- 资产选择 ----------

def test_asset_sections_published_only_and_format(session):
    seed_assets(session)
    snapshot = asset_context.build_asset_snapshot(session, '取消医嘱的费用')
    assert '【业务规则】' in snapshot.text and 'RULE-X' in snapshot.text
    assert '【概念公理】' in snapshot.text and 'AX-X' in snapshot.text
    assert '【状态动作】' in snapshot.text and 'ACT-X' in snapshot.text
    assert '未执行,已执行→已取消' in snapshot.text        # 动作含前置/目标状态
    assert 'RULE-REVIEW' not in snapshot.text            # REVIEW 不注入
    assert all(snapshot.omitted[k] == 0 for k in ('rule', 'axiom', 'action'))


def test_asset_sections_empty_keeps_context_byte_identical(session):
    svc = SemanticQaService(session)
    assert svc.build_semantic_context('任意问题') == svc.base_context()


def test_asset_ranking_cap_and_relevance(session, monkeypatch):
    """超过条目上限按相关性裁剪：相关问题保留，低相关按编码序淘汰。"""
    for i in range(3):
        session.add(Rule(rule_code=f'RULE-A{i:02d}', name='无关', concept_code='X', rule_type='约束',
                         expression='无关内容。', status='PUBLISHED', version=1))
    session.add(Rule(rule_code='RULE-ZZ', name='取消医嘱规则', concept_code='MEDICAL_ORDER', rule_type='约束',
                     expression='医嘱取消必须联动退费。', status='PUBLISHED', version=1))
    session.commit()
    monkeypatch.setattr(asset_context, 'MAX_ENTRIES', 2)
    snapshot = asset_context.build_asset_snapshot(session, '取消医嘱')
    codes = [e.code for e in snapshot.entries if e.kind == 'rule']
    assert 'RULE-ZZ' in codes                            # 相关性最高保留
    assert len(codes) == 2 and snapshot.omitted['rule'] == 2


def test_oversized_entry_omitted_whole(session):
    session.add(Rule(rule_code='RULE-BIG', name='超长', concept_code='X', rule_type='约束',
                     expression='长'*asset_context.ENTRY_CHAR_BUDGET, status='PUBLISHED', version=1))
    session.add(Rule(rule_code='RULE-OK', name='正常', concept_code='X', rule_type='约束',
                     expression='正常内容。', status='PUBLISHED', version=1))
    session.commit()
    snapshot = asset_context.build_asset_snapshot(session, '问题')
    assert 'RULE-BIG' not in snapshot.text and 'RULE-OK' in snapshot.text
    assert snapshot.omitted['rule'] == 1                 # 整条省略，不截断


def test_clipped_asset_cannot_be_cited(session, monkeypatch):
    """被裁剪而未送入上下文的资产不可引用（即使库内存在且已发布）。"""
    for i in range(3):
        session.add(Rule(rule_code=f'RULE-A{i:02d}', name='无关', concept_code='X', rule_type='约束',
                         expression='无关。', status='PUBLISHED', version=1))
    session.add(Rule(rule_code='RULE-ZZ', name='裁剪项', concept_code='X', rule_type='约束',
                     expression='内容。', status='PUBLISHED', version=1))
    session.commit()
    monkeypatch.setattr(asset_context, 'MAX_ENTRIES', 2)
    snapshot = asset_context.build_asset_snapshot(session, '无关问题')
    valid, invalid, err = asset_context.verify_citations(session, snapshot, {'ruleCodes': ['RULE-ZZ']})
    assert valid == [] and invalid == ['RULE-ZZ'] and err is None


# ---------- 指标准入 ----------

def test_qualified_metric_passes_verification(session):
    seed_metric(session)
    policy, row, reason = metric_policy.verify_qualified(session, 'CANCEL_NOT_REFUND')
    assert row is not None and reason is None
    assert policy['unit'] == '笔' and metric_policy.fingerprint(row)


@pytest.mark.parametrize('override,fragment', [
    ({'definition': '口径被改写。'}, 'definition'),
    ({'formula': 'SUM(x)'}, 'formula'),
    ({'ds_code': 'DS_OTHER'}, 'ds_code'),
    ({'probe_sql': 'SELECT 1'}, 'probe_sql'),
])
def test_metric_content_change_disqualifies(session, override, fragment):
    seed_metric(session, **override)
    policy, row, reason = metric_policy.verify_qualified(session, 'CANCEL_NOT_REFUND')
    assert row is None and reason is not None and fragment in reason


def test_enum_meaning_change_disqualifies(session):
    seed_metric(session)
    mapping = BaseDAO(session, Mapping).select_one(
        Mapping.ds_code == 'DS_HIS', Mapping.table_name == 'medical_order', Mapping.column_name == 'order_status')
    mapping.value_map = '{"0":"未执行","1":"已执行","2":"已完成"}'   # 2 不再是「取消」
    session.commit()
    policy, row, reason = metric_policy.verify_qualified(session, 'CANCEL_NOT_REFUND')
    assert row is None and '枚举映射含义变化' in reason


def test_unlisted_metric_never_qualified(session):
    session.add(Metric(metric_code='DISCHARGE_COUNT', name='出院人数', ds_code='DS_CHARGE',
                       probe_sql='SELECT 1', definition='d', formula='f'))
    session.commit()
    assert metric_policy.verify_qualified(session, 'DISCHARGE_COUNT')[2] == '指标不在直查资格清单中'
    assert metric_policy.match_question('出院人数是多少') is None


# ---------- 语义匹配：完整问法覆盖 ----------

@pytest.mark.parametrize('question', [
    '取消未退费笔数是多少', '取消未退费有多少笔', '取消未退费多少笔',
    '现在取消未退费的费用有多少笔', '请问取消未退费笔数是多少？', '当前取消未退费笔数多少',
])
def test_match_question_accepts_approved_phrasings(question):
    assert metric_policy.match_question(question) == 'CANCEL_NOT_REFUND'


@pytest.mark.parametrize('question', [
    '今天取消未退费有多少笔',            # 时间条件
    '内科取消未退费笔数是多少',          # 科室条件
    '张三的取消未退费笔数是多少',        # 患者条件
    '按科室统计取消未退费笔数',          # 分组
    '取消未退费比昨天增加多少',          # 同比比较
    '取消未退费的明细有哪些',            # 明细请求
    '取消未退费笔数怎么算',              # 定义请求（口径卡）
    '为什么取消未退费还有费用',          # 原因请求
    '取消未退费笔数和出院人数是多少',    # 多指标
    '帮我查一下取消未退费',              # 无取值尾
    '出院人数是多少',                    # 未准入指标（探针无周期）
    '检验撤销率现在多少',                # 未准入指标（探针是数量非比例）
    '出院患者均次费用是多少',            # 未准入指标（精度/分母未核定）
    '',                                  # 空问题
])
def test_match_question_rejects_unapproved(question):
    assert metric_policy.match_question(question) is None


# ---------- 执行护栏与直查编排 ----------

def test_metric_direct_executes_probe_without_llm(session, monkeypatch):
    seed_metric(session)
    session.add(Concept(code='PATIENT', name='患者', domain_code='HIS', status='PUBLISHED'))
    session.commit()
    svc = SemanticQaService(session)
    svc.llm = StubLLM([], answer='不应调用')
    executed = []
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: executed.append(sql) or [{'cnt': 3}])

    result, recorded = svc.answer('取消未退费有多少笔？')

    assert recorded is False and result['intent'] == '指标实测'
    assert svc.llm.plan_calls == 0                        # 规划/作答 LLM 均未调用
    assert result['citations']['metric']['code'] == 'CANCEL_NOT_REFUND'
    assert result['citations']['metric']['route'] == '/glossary?metric=CANCEL_NOT_REFUND'
    assert executed[0].endswith('LIMIT 100')              # 白名单管线追加 LIMIT
    labels = [e['label'] for e in result['evidence']]
    assert labels == ['指标', '指标口径', '统计范围', '单位', '执行SQL', '数据源', '实测值']
    assert next(e['value'] for e in result['evidence'] if e['label'] == '实测值') == '3笔'
    assert '共 3 笔' in result['answer'] and '不限定发生日期' in result['answer']
    assert result['rows'] == [] and 'corrections' not in result


def test_metric_direct_zero_is_valid_and_no_correction(session, monkeypatch):
    """COUNT=0 是合法业务态（该指标正常应为0）：不触发纠错、正常作答。"""
    seed_metric(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([])
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'cnt': 0}])
    result, _ = svc.answer('取消未退费有多少笔？')
    assert '共 0 笔' in result['answer']
    assert 'corrections' not in result


def test_metric_direct_warn_threshold_alarm(session, monkeypatch):
    seed_metric(session, warn_threshold=0)
    svc = SemanticQaService(session)
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'cnt': 2}])
    result, _ = svc.answer('取消未退费有多少笔？')
    assert '超过预警阈值 0笔' in result['answer']


def test_metric_direct_null_value_uses_null_answer(session, monkeypatch):
    seed_metric(session)
    svc = SemanticQaService(session)
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'cnt': None}])
    result, _ = svc.answer('取消未退费有多少笔？')
    assert '暂无可用实测值' in result['answer']
    assert next(e['value'] for e in result['evidence'] if e['label'] == '实测值') == '暂无可用实测值'


def test_metric_direct_does_not_touch_monitor_values(session, monkeypatch):
    seed_metric(session)
    svc = SemanticQaService(session)
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'cnt': 3}])
    svc.answer('取消未退费有多少笔？')
    row = BaseDAO(session, Metric).select_one(Metric.metric_code == 'CANCEL_NOT_REFUND')
    assert row.last_val is None and row.last_eval_at is None   # 不与巡检监控混淆


def test_metric_direct_falls_back_when_validate_rejects(session, monkeypatch):
    """探针引用白名单外列（order_id 映射缺失）→ 校验拒绝 → 回落 LLM 规划，不放宽白名单。
    枚举映射（order_status/fee_status）保持完整，资格核验通过，专门触达校验拒绝分支。"""
    seed_metric(session)
    BaseDAO(session, Mapping).delete(Mapping.ds_code == 'DS_HIS', Mapping.column_name == 'order_id')
    session.commit()
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(sql="SELECT order_status FROM medical_order WHERE order_status = '2'")], answer='已完成')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'order_id': 'O1'}])
    result, _ = svc.answer('取消未退费有多少笔？')
    assert svc.llm.plan_calls == 1 and result['intent'] == '语义查询'


def test_metric_direct_falls_back_when_execute_fails(session, monkeypatch):
    seed_metric(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan()], answer='已完成')

    def boom(ds, sql):
        if 'COUNT(*)' in sql:
            raise RuntimeError('timeout')
        return [{'order_id': 'O1'}]
    monkeypatch.setattr(svc, 'execute', boom)
    result, _ = svc.answer('取消未退费有多少笔？')
    assert svc.llm.plan_calls == 1 and result['answer'] == '已完成'


def test_metric_direct_disqualified_content_falls_back(session, monkeypatch):
    seed_metric(session, definition='被运维改过的口径')
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan()], answer='已完成')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'order_id': 'O1'}])
    result, _ = svc.answer('取消未退费有多少笔？')
    assert svc.llm.plan_calls == 1                        # 资格失效回落规划


# ---------- 结果类型 ----------

@pytest.mark.parametrize('rows,accepted,value', [
    ([{'cnt': 3}], True, 3),
    ([{'cnt': 0}], True, 0),
    ([{'cnt': Decimal(3)}], True, 3),
    ([{'cnt': 3.0}], True, 3),
    ([{'cnt': None}], True, None),
    ([], True, None),
])
def test_result_value_accepted(rows, accepted, value):
    ok, v, reason = metric_policy.check_result_value(rows, {'numeric_type': 'non_negative_integer'})
    assert ok and v == value and reason is None


@pytest.mark.parametrize('rows,fragment', [
    ([{'cnt': 1}, {'cnt': 2}], '2行'),
    ([{'cnt': 1, 'n': 2}], '2列'),
    ([{'cnt': '3'}], '字符串'),
    ([{'cnt': True}], '布尔'),
    ([{'cnt': Decimal('3.5')}], '不是整数'),
    ([{'cnt': -1}], '负数'),
    ([{'cnt': float('nan')}], '非有限'),
    ([{'cnt': float('inf')}], '非有限'),
])
def test_result_value_rejected(rows, fragment):
    ok, v, reason = metric_policy.check_result_value(rows, {'numeric_type': 'non_negative_integer'})
    assert not ok and fragment in reason


# ---------- 引用核验 ----------

def test_query_valid_rule_citation_surfaces(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['RULE-X'])], answer='已完成')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'order_id': 'O1'}])
    result, _ = svc.answer('取消医嘱的费用')
    assert result['citations']['rules'][0]['code'] == 'RULE-X'
    assert result['citations']['rules'][0]['route'] == '/ontology?tab=rules&assetCode=RULE-X'
    assert any(e['label'] == '依据规则 RULE-X' for e in result['evidence'])
    assert '补充规则' in svc.llm.plan_prompts[0]         # 补充指令随开关追加


def test_model_answer_valid_axiom_citation(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='不可以',
                                       semantics='结构判断', axiomCodes=['AX-X']))], answer=None)
    result, _ = svc.answer('医嘱取消了费用怎么处理')
    assert result['citations']['axioms'][0]['code'] == 'AX-X'
    assert any(e['label'] == '依据公理 AX-X' for e in result['evidence'])
    assert '依据：AX-X' in result['answer']               # 降级作答也带依据编码


def test_model_answer_without_citation_is_insufficient(session):
    """有已发布资产却无引用的 MODEL_ANSWER：保守依据不足，不输出无依据结论。"""
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='可以',
                                       semantics='结构判断'))], answer='不应采用')
    result, _ = svc.answer('可以合并结算吗')
    assert '不足以确认' in result['answer']
    assert 'citations' not in result and svc.llm.plan_calls == 1
    assert any(e['label'] == '处理说明' for e in result['evidence'])


def test_model_answer_invalid_citation_replans_once(session):
    """无效引用触发一次重规划；重试有效则采用，不得仅删引用保留原结论。"""
    seed_assets(session)
    svc = SemanticQaService(session)
    bad = json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='可以', semantics='判断', axiomCodes=['AX-NOPE']))
    good = json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='不可以', semantics='判断', axiomCodes=['AX-X']))
    svc.llm = StubLLM([bad, good], answer=None)
    result, _ = svc.answer('医嘱取消了费用怎么处理')
    assert svc.llm.plan_calls == 2
    assert result['citations']['axioms'][0]['code'] == 'AX-X'
    assert '不可以' in result['answer']


def test_model_answer_retry_failure_keeps_only_valid_evidence(session):
    """重试仍含失效引用：依据不足结果保留有效证据，不保留肯定结论。"""
    seed_assets(session)
    svc = SemanticQaService(session)
    bad = json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='可以', semantics='判断',
                          ruleCodes=['RULE-X', 'RULE-NOPE']))
    svc.llm = StubLLM([bad, bad], answer='不应采用')
    result, _ = svc.answer('取消医嘱后费用怎么处理')
    assert '不足以确认' in result['answer'] and 'citations' not in result
    assert any(e['label'] == '依据规则 RULE-X' for e in result['evidence'])   # 保留有效证据
    assert svc.llm.plan_calls == 2


def test_model_answer_without_assets_is_insufficient(session):
    """空库也必须拒绝无依据结构判断。"""
    svc = SemanticQaService(session)
    svc.llm = StubLLM([json.dumps(dict(mode='MODEL_ANSWER', ds='', conclusion='可以', semantics='结构'))],
                      answer='模型作答')
    result, _ = svc.answer('可以合并结算吗')
    assert '不足以确认' in result['answer'] and 'citations' not in result
    assert not svc.llm.answer_prompts


def test_query_fabricated_citation_never_executes(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['RULE-NOPE']), query_plan(ruleCodes=['RULE-NOPE'])],
                      answer='不应到达')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: pytest.fail('无效依据的计划不得执行'))
    result, _ = svc.answer('取消医嘱的费用')
    assert '不足以确认' in result['answer'] and svc.llm.plan_calls == 2


def test_query_invalid_citation_replan_recovers(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['RULE-NOPE']), query_plan(ruleCodes=['RULE-X'])], answer='已完成')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'order_id': 'O1'}])
    result, _ = svc.answer('取消医嘱的费用')
    assert result['answer'] == '已完成' and result['citations']['rules'][0]['code'] == 'RULE-X'
    assert svc.llm.plan_calls == 2


def test_query_replan_to_unanswerable_is_insufficient(session):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['RULE-NOPE']),
                       json.dumps(dict(mode='UNANSWERABLE', reason='无依据'))])
    result, recorded = svc.answer('取消医嘱的费用')
    assert '不足以确认' in result['answer'] and recorded is False


def test_citation_field_type_and_length_guards(session):
    seed_assets(session)
    snapshot = asset_context.build_asset_snapshot(session, '取消医嘱')
    valid, invalid, err = asset_context.verify_citations(session, snapshot, {'ruleCodes': 'RULE-X'})
    assert err and '类型错误' in err                       # 非数组
    valid, invalid, err = asset_context.verify_citations(
        session, snapshot, {'ruleCodes': [f'RULE-N{i}' for i in range(asset_context.MAX_CITED_CODES + 1)]})
    assert err and '上限' in err                          # 超长列表
    valid, invalid, err = asset_context.verify_citations(
        session, snapshot, {'ruleCodes': ['RULE-X', 'RULE-X']})
    assert not err and len(valid) == 1                    # 重复编码去重


def test_citation_invalidated_by_content_change(session):
    """快照构建后资产内容被改：引用视为失效，不混用旧结论与新证据。"""
    seed_assets(session)
    snapshot = asset_context.build_asset_snapshot(session, '取消医嘱')
    rule = BaseDAO(session, Rule).select_one(Rule.rule_code == 'RULE-X')
    rule.expression = '改写后的口径。'
    session.commit()
    valid, invalid, err = asset_context.verify_citations(session, snapshot, {'ruleCodes': ['RULE-X']})
    assert valid == [] and invalid == ['RULE-X']


# ---------- QUERY/critic ----------

def test_query_without_declared_citations_unchanged(session, monkeypatch):
    """未声明引用的 QUERY 完全兼容既有行为（不核验、无 citations）。"""
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan()], answer='已完成')
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: [{'order_id': 'O1'}])
    result, _ = svc.answer('医嘱清单')
    assert result['answer'] == '已完成' and 'citations' not in result
    assert not any(e['label'].startswith('依据') for e in result['evidence'])


def test_correction_clears_asset_citations(session, monkeypatch):
    """纠错采纳新 SQL 后原规划引用不继承：清空资产引用，保留最终 SQL 与 corrections。"""
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan(ruleCodes=['RULE-X'])], answer=None)
    states = {'main': 0}

    def fake_execute(ds, sql):
        if sql.startswith('SELECT * FROM'):
            return [{'order_id': 'O1'}]
        states['main'] += 1
        return [[{'cnt': 0}], [{'cnt': 5}]][min(states['main'] - 1, 1)]

    monkeypatch.setattr(svc, 'execute', fake_execute)
    monkeypatch.setattr(svc.critic, 'judge', lambda *args: dict(
        verdict='FIX', correctedSql="SELECT COUNT(*) AS cnt FROM medical_order WHERE order_status = '2'", reason='枚举码纠正'))
    result, _ = svc.answer('取消医嘱有多少')
    assert result['corrections'] and 'citations' not in result
    assert not any(e['label'].startswith('依据规则') for e in result['evidence'])
    assert any(e['label'] == '执行SQL' for e in result['evidence'])


def test_critic_receives_asset_context(session, monkeypatch):
    seed_assets(session)
    svc = SemanticQaService(session)
    svc.llm = StubLLM([query_plan()], answer=None)
    captured = {}
    monkeypatch.setattr(svc, 'execute', lambda ds, sql: ([] if not sql.startswith('SELECT * FROM') else [{'order_id': 'O1'}]))
    monkeypatch.setattr(svc.critic, 'judge',
                        lambda q, context, sql, desc, samples: captured.update(context=context) or None)
    svc.answer('医嘱清单')
    assert '【业务规则】' in captured['context'] and 'RULE-X' in captured['context']


# ---------- 完整入口（CsService.ask / HTTP） ----------

def test_ask_analytics_routes_metric_question_to_direct(session, monkeypatch):
    """完整入口：统计问法经关键词路由进语义服务后命中直查（非服务层直调）。"""
    monkeypatch.setattr(settings, 'deepseek_api_key', '')   # 入口测试不调真实外部 LLM
    seed_metric(session)
    monkeypatch.setattr(SemanticQaService, 'execute', lambda self, ds, sql: [{'cnt': 3}])
    from bemodel.cs.services import CsService
    result = CsService(session).ask('取消未退费有多少笔', scene='ANALYTICS')
    assert result['intent'] == '指标实测'
    assert '共 3 笔' in result['answer']
    assert result['citations']['metric']['code'] == 'CANCEL_NOT_REFUND'


def test_ask_analytics_glossary_word_keeps_metric_card(session, monkeypatch):
    """口径问法维持指标卡（定义/公式），不转直查。"""
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    seed_metric(session)
    from bemodel.cs.services import CsService
    result = CsService(session).ask('取消未退费笔数怎么算', scene='ANALYTICS')
    assert result['card'] == 'METRIC' and result['intent'] == '口径查询'
    assert 'citations' not in result


def test_ask_analytics_rate_question_not_direct(session, monkeypatch):
    """撤销率问法不走数量探针直查：无 Key 时落引导菜单。"""
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    seed_metric(session)
    from bemodel.cs.services import CsService
    result = CsService(session).ask('检验撤销率现在多少', scene='ANALYTICS')
    assert result['intent'] == '场景引导' and result['router'] == 'RULE'


def test_api_ask_contract_with_citations(client, session, monkeypatch):
    """HTTP 契约：VIEWER 可访问，code=0，直查结果携带 citations，camelCase 键。"""
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    from bemodel.auth.jwt_service import JwtService
    seed_metric(session)
    monkeypatch.setattr(SemanticQaService, 'execute', lambda self, ds, sql: [{'cnt': 3}])
    token = JwtService().issue(SimpleNamespace(username='t', display_name=None, role='VIEWER'))
    response = client.post('/api/cs/ask', json={'question': '取消未退费有多少笔', 'scene': 'ANALYTICS'},
                           headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 200
    body = response.json()
    assert body['code'] == 0 and body['data']['intent'] == '指标实测'
    assert body['data']['citations']['metric']['code'] == 'CANCEL_NOT_REFUND'


# ---------- MySQL 集成（13317 隔离库） ----------

def test_context_contains_seed_assets_mysql(mysql_session):
    svc = SemanticQaService(mysql_session)
    ctx = svc.build_semantic_context('取消医嘱')
    for token in ('【业务规则】', 'RULE-FEE-001', '【概念公理】', 'AX-005', '【状态动作】', 'ACT-ORDER-CANCEL'):
        assert token in ctx
    assert 'RULE-OPD-001' not in ctx                        # REVIEW 规则不注入


def test_metric_direct_real_value_mysql(mysql_session):
    """真库直查：数值/单位/范围与独立口径计算一致；不写监控最近值。"""
    from bemodel.ontology.entities import Metric as MetricEntity
    svc = SemanticQaService(mysql_session)
    before = BaseDAO(mysql_session, MetricEntity).select_one(MetricEntity.metric_code == 'CANCEL_NOT_REFUND')
    before_eval, before_val = before.last_eval_at, before.last_val

    result, recorded = svc.answer('现在取消未退费的费用有多少笔？', analytics=True)

    assert recorded is False and result['intent'] == '指标实测'
    # 独立等价口径（子查询形式，不经被测资格/匹配函数）
    expected = svc.ds.query('DS_HIS', "SELECT COUNT(*) AS n FROM fee_detail WHERE fee_status = '1' "
                            "AND order_id IN (SELECT order_id FROM medical_order WHERE order_status = '2')")[0]['n']
    assert next(e['value'] for e in result['evidence'] if e['label'] == '实测值') == f"{expected}笔"
    executed = next(e['value'] for e in result['evidence'] if e['label'] == '执行SQL')
    assert 'fee_detail' in executed and 'medical_order' in executed and executed.endswith('LIMIT 100')
    assert result['citations']['metric']['code'] == 'CANCEL_NOT_REFUND'
    after = BaseDAO(mysql_session, MetricEntity).select_one(MetricEntity.metric_code == 'CANCEL_NOT_REFUND')
    assert (after.last_eval_at, after.last_val) == (before_eval, before_val)


def test_model_answer_with_seed_axiom_citation_mysql(mysql_session, monkeypatch):
    """真库 MODEL_ANSWER：引用种子公理 AX-005 通过核验，证据与深链完整。"""
    svc = SemanticQaService(mysql_session)

    def chat(kind, system, prompt):
        return json.dumps(dict(mode='MODEL_ANSWER', ds='DS_HIS', conclusion='不可以',
                               semantics='MEDICAL_ORDER 通过映射访问业务数据',
                               verifySql='SELECT COUNT(*) cnt FROM medical_order',
                               axiomCodes=['AX-005'])) if kind == 'CS_SEMANTIC_PLAN' else None
    monkeypatch.setattr(svc.llm, 'chat', chat)
    answer, missed = svc.answer('可以查询医嘱吗？')
    assert not missed and answer['router'] == 'SEMANTIC'
    assert answer['citations']['axioms'][0]['code'] == 'AX-005'
    assert answer['citations']['axioms'][0]['route'] == '/ontology?tab=axioms&assetCode=AX-005'
    assert any(e['label'] == '依据公理 AX-005' for e in answer['evidence'])
    assert '验证探针返回：{cnt=' in answer['answer']
