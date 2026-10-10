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
报告：artifacts/semantic-qa-eval.json
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.core.database import engine
from bemodel.cs import metric_policy
from bemodel.cs.services import CsService
from bemodel.datasource.entities import Datasource
from bemodel.llm.entities import LlmLog

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
    return dict(head=run('rev-parse', 'HEAD')[:12], dirty=bool(run('status', '--short')))


def guard():
    """连接前确认平台库与所有测试数据源均指向任务隔离环境（13317/bemodel_py_test）。"""
    assert settings.mysql_host in ('127.0.0.1', 'localhost'), f'平台库主机非本机: {settings.mysql_host}'
    assert settings.mysql_port == 13317 and settings.mysql_database == 'bemodel_py_test', \
        f'平台库不是隔离测试库: {settings.mysql_port}/{settings.mysql_database}'
    with Session(engine) as session:
        for ds in BaseDAO(session, Datasource).select_list(Datasource.deleted == 0):
            assert (ds.host or '') in ('127.0.0.1', 'localhost') and ds.port == 13317, \
                f'数据源 {ds.ds_code} 指向非隔离环境: {ds.host}:{ds.port}'
    return True


def llm_counts(session, since_id):
    rows = BaseDAO(session, LlmLog).select_list(LlmLog.id > since_id)
    counts = {}
    for row in rows:
        counts[row.call_type] = counts.get(row.call_type, 0) + 1
    return counts, max((row.id for row in rows), default=since_id)


def expected_cancel_not_refund(cs):
    """独立口径计算预期值（子查询等价形式，不经被测资格/匹配函数）。"""
    rows = cs.flow.query('HIS', "SELECT COUNT(*) AS n FROM fee_detail WHERE fee_status = '1' "
                         "AND order_id IN (SELECT order_id FROM medical_order WHERE order_status = '2')")[0]
    return rows[0]['n']


def run_round(session, expected_value):
    """跑一轮完整入口问答，逐题记录路由/直查/引用/LLM 调用/耗时。"""
    results = []
    for item in QUESTIONS:
        cursor_id = BaseDAO(session, LlmLog).select_list(order=(LlmLog.id.desc(),), limit=1)
        since = cursor_id[0].id if cursor_id else 0
        started = time.monotonic()
        try:
            data = CsService(session).ask(item['q'], scene='ANALYTICS')
            error = None
        except Exception as exc:  # 单题失败不中断整轮
            data, error = None, f'{type(exc).__name__}: {exc}'
        latency = round((time.monotonic() - started) * 1000)
        calls, _ = llm_counts(session, since)
        record = dict(category=item['cat'], question=item['q'], error=error, latencyMs=latency,
                      llmCalls=calls,
                      intent=data.get('intent') if data else None,
                      router=data.get('router') if data else None,
                      direct=data.get('intent') == '指标实测',
                      card=data.get('card') if data else None,
                      citations=data.get('citations') if data else None,
                      measured=next((e['value'] for e in data.get('evidence', []) if e['label'] == '实测值'), None)
                      if data else None,
                      answer=data.get('answer') if data else None)
        if record['direct']:
            record['valueOk'] = record['measured'] == f'{expected_value}笔'
        results.append(record)
    return results


def check_deterministic(off, on_rounds, expected_value, failures):
    def fail(msg):
        failures.append(msg)
    if off is not None:
        for record in off:
            if record['direct'] or record['citations']:
                fail(f"[off] {record['question']} 出现直查/citations")
    for idx, on in enumerate(on_rounds, 1):
        for record in on:
            q, direct = record['question'], record['direct']
            item = next(i for i in QUESTIONS if i['q'] == q)
            if item.get('expectDirect') and not (direct and record['valueOk']):
                fail(f"[on第{idx}轮] {q} 应直查且数值正确（期望 {expected_value}笔，实测 {record['measured']}）")
            if item.get('mustNotDirect') and direct:
                fail(f"[on第{idx}轮] {q} 属未准入/带附加条件问法，不得直查")
            if item.get('expectCard') and record['card'] != item['expectCard']:
                fail(f"[on第{idx}轮] {q} 应落口径卡 {item['expectCard']}，实际 {record['card']}")
            if item['cat'] in ('B_assets', 'C_inconsistent_probe', 'D_plain_query', 'E_reject', 'E_write_op', 'E_export') and direct:
                fail(f"[on第{idx}轮] {q} 不应走指标直查")


def summarize(results):
    return dict(total=len(results),
                direct=sum(r['direct'] for r in results),
                directValueOk=sum(bool(r.get('valueOk')) for r in results),
                withCitations=sum(bool(r['citations']) for r in results),
                llmCalls=sum(sum(r['llmCalls'].values()) for r in results),
                avgLatencyMs=round(sum(r['latencyMs'] for r in results) / len(results)))


def aggregate_on(on_rounds):
    """真实模型多轮聚合：按分类统计直查/数值正确/引用出现率与平均耗时。"""
    by_cat = {}
    for results in on_rounds:
        for r in results:
            cat = by_cat.setdefault(r['category'], dict(questions=0, direct=0, valueOk=0, citations=0))
            cat['questions'] += 1
            cat['direct'] += int(r['direct'])
            cat['valueOk'] += int(bool(r.get('valueOk')))
            cat['citations'] += int(bool(r['citations']))
    return {cat: dict(**counts, directRate=round(counts['direct'] / counts['questions'], 3))
            for cat, counts in by_cat.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real-llm', action='store_true', help='保留进程内配置的 DeepSeek Key 跑真实模型轮')
    parser.add_argument('--rounds', type=int, default=None,
                        help='开臂轮数：默认确定性 1 轮、真实模型 3 轮（设计方案 8.3）')
    args = parser.parse_args()
    rounds = max(1, args.rounds if args.rounds else (3 if args.real_llm else 1))

    guard()
    key_configured = bool(settings.deepseek_api_key.strip())
    if not args.real_llm:
        # 确定性轮不调用真实外部模型：进程内清空 Key（不回写 .env）
        settings.deepseek_api_key = ''
        llm_mode = 'deterministic(no-key)'
    else:
        if not key_configured:
            print('未配置 DeepSeek Key，无法运行真实模型轮', file=sys.stderr)
            sys.exit(2)
        llm_mode = f'real(rounds={rounds})'

    with Session(engine) as session:
        cs = CsService(session)
        expected_value = expected_cancel_not_refund(cs)
        original = settings.semantic_asset_enhance
        try:
            settings.semantic_asset_enhance = False
            off = run_round(session, expected_value)
            settings.semantic_asset_enhance = True
            on_rounds = [run_round(session, expected_value) for _ in range(rounds)]
        finally:
            settings.semantic_asset_enhance = original

    failures = []
    check_deterministic(off, on_rounds, expected_value, failures)

    report = dict(
        generatedAt=datetime.now().isoformat(timespec='seconds'),
        git=git_info(),
        policyVersion=metric_policy.POLICY_VERSION,
        llmMode=llm_mode,
        llmKeyConfigured=key_configured,      # 只记有无，不记内容
        expectedCancelNotRefund=expected_value,
        config=dict(semanticAssetEnhance='off 基线 1 轮 + on 轮', datasourceGuard='127.0.0.1:13317/bemodel_py_test'),
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
        ])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'报告已写入 {REPORT}')
    print('off 基线:', json.dumps(summarize(off), ensure_ascii=False))
    for i, r in enumerate(on_rounds, 1):
        print(f'on 第{i}轮:', json.dumps(summarize(r), ensure_ascii=False))
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        sys.exit(1)
    print('确定性断言全部通过')


if __name__ == '__main__':
    main()
