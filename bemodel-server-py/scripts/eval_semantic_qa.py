"""智能问数增强 A/B 评测（设计方案 8.3）。

在同一隔离业务数据上跑「增强关/开」两臂，主报告经完整入口
CsService.ask(scene='ANALYTICS') 执行；确定性断言（合格指标直查数值、
未准入指标不直查、开关关闭零直查）失败时退出码非 0。

确定性模式（默认）：进程内清空 Key，单轮关/开，只出确定性结论。
真实模型模式（--real-llm）：保留进程内配置的 Key，开臂默认跑 3 轮
（--rounds 可调）、关臂 1 轮作基线，逐轮与分组报告；Key 不写入报告
与日志。

用法（在 bemodel-server-py/ 下，13317 隔离环境就绪后）：
  .venv/Scripts/python.exe scripts/eval_semantic_qa.py
  .venv/Scripts/python.exe scripts/eval_semantic_qa.py --real-llm [--rounds 3]
离线固定数据：python scripts/eval_semantic_qa.py --sqlite-fixture
报告按 sqlite / mysql / real 分别写入 artifacts/semantic-qa-eval-<模式>.json。
真实模型报告保留人工复核待办，不把引用编码有效率当作证据支持度。
"""

import argparse
import json
import subprocess
import sys
import time
import hashlib
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.orm import Session

from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import engine
from bemodel.cs import metric_policy, asset_context
from bemodel.cs.services import CsService
from bemodel.datasource.entities import Datasource
from bemodel.llm.entities import LlmLog
from bemodel.llm.services import DeepSeekClient
from bemodel.ontology.entities import OntologyMiss
from bemodel.agents import runtime

REPORT = Path(__file__).resolve().parents[1] / 'artifacts' / 'semantic-qa-eval.json'

# 基准问题集：分类覆盖设计方案 8.3。expectedDirect=合格指标直查；
# mustNotDirect=一致性反例（探针与口径不一致，禁止直查）。
QUESTIONS = [
    dict(cat='A_qualified_metric', q='现在取消未退费的费用有多少笔', expectDirect=True),
    dict(cat='A_qualified_metric', q='取消未退费笔数是多少', expectDirect=True),
    dict(cat='A_qualified_metric', q='请问取消未退费有多少笔？', expectDirect=True),
    dict(cat='A_boundary', q='取消未退费笔数怎么算', expectCard='METRIC'),
    dict(cat='A_boundary', q='今天取消未退费有多少笔', mustNotDirect=True),
    dict(cat='A_boundary', q='内科取消未退费笔数是多少', mustNotDirect=True),
    dict(cat='A_boundary', q='按科室统计取消未退费笔数', mustNotDirect=True),
    dict(cat='A_boundary', q='取消未退费笔数和出院人数是多少', mustNotDirect=True),
    dict(cat='B_assets', q='男性患者能有妊娠诊断吗'),
    dict(cat='B_assets', q='没有诊断指征能做手术吗'),
    dict(cat='B_assets', q='医嘱取消了费用该怎么处理'),
    dict(cat='B_assets', q='检验异常的报告必须处置吗'),
    dict(cat='C_inconsistent_probe', q='出院人数是多少', mustNotDirect=True),
    dict(cat='C_inconsistent_probe', q='今天出院人数是多少', mustNotDirect=True),
    dict(cat='C_inconsistent_probe', q='检验撤销率现在多少', mustNotDirect=True),
    dict(cat='C_inconsistent_probe', q='出院患者均次费用是多少', mustNotDirect=True),
    dict(cat='D_plain_query', q='最近10条缴费记录'),
    dict(cat='D_plain_query', q='昨天缴费总额是多少'),
    dict(cat='D_plain_query', q='内科有多少住院患者'),
    dict(cat='D_plain_query', q='2026年8月出院的结算单有多少'),
    dict(cat='E_reject', q='今天天气怎么样'),
    dict(cat='E_reject', q='医院门口有几个停车位'),
    dict(cat='E_write_op', q='帮我给张三开发票'),
    dict(cat='E_export', q='导出药品价格表'),
]


def git_info():
    def run(*args):
        try:
            return subprocess.run(['git', *args], capture_output=True, text=True,
                                  cwd=Path(__file__).resolve().parents[2]).stdout.strip()
        except Exception:
            return ''
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for path in sorted([*root.joinpath('src').rglob('*.py'), *root.joinpath('scripts').glob('*semantic_qa*.py')]):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return dict(head=run('rev-parse', 'HEAD')[:12], dirty=bool(run('status', '--short')), sourceSha256=digest.hexdigest())


def guard():
    """连接前确认平台库与所有测试数据源均指向任务隔离环境（13317/bemodel_py_test）。"""
    assert settings.mysql_host in ('127.0.0.1', 'localhost'), f'平台库主机非本机: {settings.mysql_host}'
    assert settings.mysql_port == 13317 and settings.mysql_database == 'bemodel_py_test', \
        f'平台库不是隔离测试库: {settings.mysql_port}/{settings.mysql_database}'
    with Session(engine) as session:
        for ds in BaseDAO(session, Datasource).select_list(Datasource.deleted == 0):
            assert (ds.host or '') in ('127.0.0.1', 'localhost') and ds.port == 13317, \
                f'数据源 {ds.ds_code} 指向非隔离环境: {ds.host}:{ds.port}'
            assert ds.db_name in {'demo_his','demo_lis','demo_charge','demo_pharmacy','demo_opd',
                                  'demo_emr','demo_pacs','demo_nurse','demo_material'}, \
                f'数据源 {ds.ds_code} 的库名不在隔离种子清单中'
    return True


def llm_counts(session, since_id):
    rows = BaseDAO(session, LlmLog).select_list(LlmLog.id > since_id)
    counts = {}
    for row in rows:
        counts[row.call_type] = counts.get(row.call_type, 0) + 1
    return counts, max((row.id for row in rows), default=since_id)


def expected_cancel_not_refund(cs):
    """独立口径计算预期值（子查询等价形式，不经被测资格/匹配函数）。"""
    row = cs.flow.query('HIS', "SELECT COUNT(*) AS n FROM fee_detail WHERE fee_status = '1' "
                        "AND order_id IN (SELECT order_id FROM medical_order WHERE order_status = '2')")[0]
    return row['n']


@contextmanager
def db_session(item):
    with Session(engine, expire_on_commit=False) as session:
        yield session


def run_round(expected_value, questions=QUESTIONS, session_factory=db_session, require_llm_success=False):
    """每题独立 Session；仅记录提示词长度和合成/脱敏证据，不保存完整查询明细。"""
    results = []
    for item in questions:
        with session_factory(item) as session:
            calls, snapshots = [], []
            original_chat, original_snapshot = DeepSeekClient.chat, asset_context.build_asset_snapshot
            original_critic = runtime.critic_chat
            def chat(client, kind, system, prompt):
                started = time.monotonic()
                response = None
                try:
                    response = original_chat(client, kind, system, prompt)
                    return response
                finally:
                    calls.append(dict(type=kind, promptChars=len(system or '')+len(prompt or ''),
                                      latencyMs=round((time.monotonic()-started)*1000), tokens=None,
                                      success=response is not None))
            def snapshot(*args):
                snap = original_snapshot(*args)
                snapshots.append(snap)
                return snap
            def critic(session, system, prompt):
                started = time.monotonic()
                response = None
                try:
                    response = original_critic(session, system, prompt)
                    return response
                finally:
                    calls.append(dict(type='CS_SEMANTIC_CRITIQUE', promptChars=len(system or '')+len(prompt or ''),
                                      latencyMs=round((time.monotonic()-started)*1000), tokens=None,
                                      success=response is not None))
            before_miss = sum(r.count or 0 for r in BaseDAO(session, OntologyMiss).select_list())
            cursor = BaseDAO(session, LlmLog).select_list(order=(LlmLog.id.desc(),), limit=1)
            since = cursor[0].id if cursor else 0
            started = time.monotonic()
            try:
                with patch.object(DeepSeekClient, 'chat', chat), patch.object(asset_context, 'build_asset_snapshot', snapshot), patch.object(runtime, 'critic_chat', critic):
                    data = CsService(session).ask(item['q'], scene=item.get('scene', 'ANALYTICS')) or {}
                error = None
            except Exception as exc:
                session.rollback()
                data, error = {}, type(exc).__name__  # 不泄漏连接串、SQL 参数或结果行
            latency = round((time.monotonic()-started)*1000)
            audit_calls, _ = llm_counts(session, since)
            after_miss = sum(r.count or 0 for r in BaseDAO(session, OntologyMiss).select_list())
            evidence = {e['label']:e['value'] for e in data.get('evidence', [])}
            direct = data.get('intent') == '指标实测'
            expected = item.get('expectedValue', expected_value if item.get('expectDirect') else None)
            citations = data.get('citations') or {}
            citation_errors = []
            declared = {field:[e['code'] for e in citations.get(group, [])]
                        for field, group in [('ruleCodes','rules'),('axiomCodes','axioms'),('actionCodes','actions')]}
            if any(declared.values()):
                valid, invalid, err = asset_context.verify_citations(session, snapshots[-1] if snapshots else None, declared)
                if invalid or err:
                    citation_errors.append('引用不属于有效快照')
                expected_citations = asset_context.build_citations(valid)
                if any(citations.get(k) != v for k,v in expected_citations.items()):
                    citation_errors.append('引用名称或链接与服务端证据不一致')
            if 'metric' in citations:
                _, metric, reason = metric_policy.verify_qualified(session, citations['metric']['code'])
                if reason or metric is None or not direct:
                    citation_errors.append('指标引用资格失效')
            checks = []
            if error:
                checks.append('调用异常: '+error)
            if citation_errors:
                checks.extend(citation_errors)
            failed_model_calls = [c['type'] for c in calls if not c['success']]
            if require_llm_success and failed_model_calls:
                checks.append('真实模型调用失败: ' + ','.join(failed_model_calls))
            value_ok = None
            if direct:
                value_ok = evidence.get('实测值') == f'{expected}笔'
                if not value_ok or evidence.get('单位') != '笔' or evidence.get('统计范围') != '当前全量数据快照（不限发生日期）':
                    checks.append('指标值、单位或范围不符')
                if not evidence.get('执行SQL') or not evidence.get('数据源','').startswith('DS_HIS'):
                    checks.append('缺失 SQL 或数据源证据')
                if any(c['type'] in ('CS_SEMANTIC_PLAN','CS_SEMANTIC_ANSWER','CS_SEMANTIC_CRITIQUE') for c in calls):
                    checks.append('直查发生语义规划/作答/纠错调用')
            elif expected is not None:
                rows = data.get('rows', [])
                value_ok = len(rows)==1 and len(rows[0])==1 and next(iter(rows[0].values()))==expected
                if 'plan' in item and not value_ok:
                    checks.append('查询业务数值不符')
            if 'expectedRows' in item and data.get('rows') != item['expectedRows']:
                checks.append('分组/明细结果不符')
            if settings.semantic_asset_enhance:
                if item.get('expectInsufficient') and '不足以确认' not in data.get('answer',''):
                    checks.append('未按依据不足降级')
                actual_codes = [e['code'] for k in ('rules','actions','axioms') for e in citations.get(k,[])]
                if item.get('expectCitations') and set(actual_codes) != set(item['expectCitations']):
                    checks.append('缺少预期引用')
            record = dict(category=item['cat'], question=item['q'], scene=item.get('scene','ANALYTICS'), error=error,
                latencyMs=latency, llmCalls=dict(Counter(c['type'] for c in calls)), calls=calls, auditCalls=audit_calls,
                missDelta=after_miss-before_miss, intent=data.get('intent'), router=data.get('router'), direct=direct,
                card=data.get('card'), citations=citations or None, measured=evidence.get('实测值'), valueOk=value_ok,
                expectedValue=expected, unit=item.get('unit','笔' if expected is not None else None),
                scope='当前全量数据快照（不限发生日期）' if item.get('expectDirect') else item.get('filter'),
                fallbackReason=metric_policy.verify_qualified(session, metric_policy.match_question(item['q']))[2]
                    if settings.semantic_asset_enhance and not direct and metric_policy.match_question(item['q']) else None,
                expectedCitations=item.get('expectCitations'), allowedPath='DIRECT' if item.get('expectDirect') else 'PLAN_OR_CARD',
                assetSnapshots=[dict(chars=len(s.text), omitted=s.omitted) for s in snapshots],
                failures=checks, businessReview='deterministic-fixture' if 'plan' in item else 'pending-human-review',
                evidenceSupport='pending-human-review' if 'plan' not in item else 'stub-only',
                answer=data.get('answer') if 'plan' in item else None)
            results.append(record)
    return results


def check_deterministic(off, on_rounds, expected_value, failures, questions=QUESTIONS):
    def fail(msg):
        failures.append(msg)
    if off is not None:
        for record in off:
            failures.extend('[off] '+record['question']+': '+f for f in record.get('failures', []))
            if record['direct'] or record['citations']:
                fail(f"[off] {record['question']} 出现直查/citations")
    for idx, on in enumerate(on_rounds, 1):
        for record in on:
            q, direct = record['question'], record['direct']
            item = next(i for i in questions if i['q'] == q and i.get('scene','ANALYTICS') == record.get('scene','ANALYTICS'))
            failures.extend(f'[on第{idx}轮] '+q+': '+f for f in record.get('failures', []))
            if item.get('expectDirect') and not (direct and record.get('valueOk')):
                fail(f"[on第{idx}轮] {q} 应直查且数值正确（期望 {expected_value}笔，实测 {record['measured']}）")
            if item.get('mustNotDirect') and direct:
                fail(f"[on第{idx}轮] {q} 属未准入/带附加条件问法，不得直查")
            if not item.get('expectDirect') and direct:
                fail(f'[on第{idx}轮] {q} 未标注为允许直查')
            if item.get('expectCard') and record['card'] != item['expectCard']:
                fail(f"[on第{idx}轮] {q} 应落口径卡 {item['expectCard']}，实际 {record['card']}")
            if item['cat'] in ('B_assets', 'C_inconsistent_probe', 'D_plain_query', 'E_reject', 'E_write_op', 'E_export') and direct:
                fail(f"[on第{idx}轮] {q} 不应走指标直查")


def summarize(results):
    latency_groups = {}
    for name, failed in (('passedChecks', False), ('failedChecks', True)):
        group = [r['latencyMs'] for r in results if bool(r.get('failures')) == failed]
        latency_groups[name] = dict(count=len(group), avgMs=round(sum(group)/len(group)) if group else None)
    model_calls = [c for r in results for c in r.get('calls', [])]
    return dict(total=len(results),
                direct=sum(r['direct'] for r in results),
                directValueOk=sum(r['direct'] and bool(r.get('valueOk')) for r in results),
                queryValueOk=sum(not r['direct'] and bool(r.get('valueOk')) for r in results),
                failed=sum(bool(r.get('failures')) for r in results),
                pendingHumanReview=sum(r.get('businessReview') == 'pending-human-review' for r in results),
                latencyByOutcome=latency_groups,
                promptChars=sum(c['promptChars'] for r in results for c in r.get('calls', [])),
                withCitations=sum(bool(r['citations']) for r in results),
                llmCalls=sum(sum(r['llmCalls'].values()) for r in results),
                successfulLlmCalls=sum(bool(c.get('success')) for c in model_calls),
                failedLlmCalls=sum(not bool(c.get('success')) for c in model_calls),
                avgLatencyMs=round(sum(r['latencyMs'] for r in results) / len(results)))


def aggregate_on(on_rounds):
    """真实模型多轮聚合：按分类统计直查/数值正确/引用出现率与平均耗时。"""
    by_cat = {}
    for results in on_rounds:
        for r in results:
            cat = by_cat.setdefault(r['category'], dict(questions=0, direct=0, valueOk=0, citations=0))
            cat['questions'] += 1
            cat['direct'] += int(r['direct'])
            cat['valueOk'] += int(r['direct'] and bool(r.get('valueOk')))
            cat['citations'] += int(bool(r['citations']))
    return {cat: dict(**counts, directRate=round(counts['direct'] / counts['questions'], 3))
            for cat, counts in by_cat.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real-llm', action='store_true', help='保留进程内配置的 DeepSeek Key 跑真实模型轮')
    parser.add_argument('--sqlite-fixture', action='store_true', help='固定合成数据 + StubLLM，不连接 MySQL 或外部模型')
    parser.add_argument('--output', type=Path, help='报告路径；离线/真实模型默认使用不同文件，避免覆盖旧证据')
    parser.add_argument('--rounds', type=int, default=None,
                        help='开臂轮数：默认确定性 1 轮、真实模型 3 轮（设计方案 8.3）')
    args = parser.parse_args()
    if args.sqlite_fixture and args.real_llm:
        parser.error('--sqlite-fixture 与 --real-llm 不能同时使用')
    rounds = max(1, args.rounds if args.rounds else (3 if args.real_llm else 1))

    if args.real_llm and rounds < 3:
        parser.error('真实模型验收至少运行 3 轮')
    if not args.sqlite_fixture:
        guard()
    key_configured = bool(settings.deepseek_api_key.strip())
    original_key = settings.deepseek_api_key
    if not args.real_llm:
        # 确定性轮不调用真实外部模型：进程内清空 Key（不回写 .env）
        settings.deepseek_api_key = ''
        llm_mode = 'deterministic(no-key)'
    else:
        if not key_configured:
            print('未配置 DeepSeek Key，无法运行真实模型轮', file=sys.stderr)
            sys.exit(2)
        llm_mode = f'real(rounds={rounds})'

    questions, session_factory = QUESTIONS, db_session
    fixture_version, baseline_date = 'isolated-seed-unversioned', str(date.today())
    if args.sqlite_fixture:
        import semantic_qa_eval_fixture as fixture
        questions, session_factory = fixture.QUESTIONS, fixture.fixture_session
        fixture_version, baseline_date = fixture.VERSION, fixture.BASE_DATE
        expected_value, llm_mode = 3, 'StubLLM+SQLite'
    else:
        with Session(engine) as session:
            expected_value = expected_cancel_not_refund(CsService(session))
    original = settings.semantic_asset_enhance
    try:
        settings.semantic_asset_enhance = False
        off = run_round(expected_value, questions, session_factory, require_llm_success=args.real_llm)
        settings.semantic_asset_enhance = True
        on_rounds = [run_round(expected_value, questions, session_factory, require_llm_success=args.real_llm)
                     for _ in range(rounds)]
    finally:
        settings.semantic_asset_enhance = original
        settings.deepseek_api_key = original_key

    failures = []
    check_deterministic(off, on_rounds, expected_value, failures, questions)
    all_records = off + [record for round_records in on_rounds for record in round_records]
    all_model_calls = [call for record in all_records for call in record.get('calls', [])]
    model_call_integrity = dict(
        attempted=len(all_model_calls),
        succeeded=sum(bool(call.get('success')) for call in all_model_calls),
        failed=sum(not bool(call.get('success')) for call in all_model_calls),
    )
    model_call_integrity['passed'] = bool(
        args.real_llm and model_call_integrity['succeeded'] > 0 and model_call_integrity['failed'] == 0)
    pending_validation = ['业务正确率、证据支持度人工复核']
    if not model_call_integrity['passed']:
        pending_validation.insert(0, '真实模型三轮 A/B（要求所有模型调用成功）')
    if args.sqlite_fixture:
        pending_validation.append('MySQL 超时及方言集成验证')

    report = dict(
        generatedAt=datetime.now().isoformat(timespec='seconds'),
        git=git_info(),
        policyVersion=metric_policy.POLICY_VERSION,
        fixtureVersion=fixture_version,
        baselineDate=baseline_date,
        releaseGatePassed=False,  # 需另外提交真实模型三轮和人工证据支持度复核，不能由替身断言代替。
        pendingValidation=pending_validation,
        llmMode=llm_mode,
        llmKeyConfigured=(key_configured if args.real_llm else False),  # 替身模式不把本地配置误报为实际使用
        modelCallIntegrity=model_call_integrity,
        expectedCancelNotRefund=expected_value,
        config=dict(semanticAssetEnhance='off 基线 1 轮 + on 轮', datasourceGuard='in-memory SQLite' if args.sqlite_fixture else '127.0.0.1:13317/bemodel_py_test'),
        rounds=dict(off=dict(summary=summarize(off), perQuestion=off),
                    on=[dict(round=i, summary=summarize(r), perQuestion=r)
                        for i, r in enumerate(on_rounds, 1)]),
        onAggregateByCategory=aggregate_on(on_rounds),
        deterministicFailures=failures,
        notes=[
            '主报告经完整入口 CsService.ask(scene=ANALYTICS) 执行；成本收益只统计实际进入合格直查的样本。',
            '未运行 --real-llm 时本报告仅为确定性验证，不宣称真实模型准确率或成本结论。',
            '真实模型自由文本的结论支持度需人工复核，编码有效率不等于业务正确率。',
            'citations 为业务证据，不参与任何双端归一化忽略。',
            'tokens=null：现有网关不向调用方暴露 usage；promptChars 是实际字符数，不估算 token。',
            'llmCalls 是调用入口尝试次数，包含无 Key 降级或替身；不等同于外部计费调用。',
        ])
    output = args.output or REPORT.with_name('semantic-qa-eval-'+('sqlite' if args.sqlite_fixture else 'real' if args.real_llm else 'mysql')+'.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'报告已写入 {output}')
    print('off 基线:', json.dumps(summarize(off), ensure_ascii=False))
    for i, r in enumerate(on_rounds, 1):
        print(f'on 第{i}轮:', json.dumps(summarize(r), ensure_ascii=False))
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        sys.exit(1)
    print('确定性断言全部通过')


if __name__ == '__main__':
    main()
