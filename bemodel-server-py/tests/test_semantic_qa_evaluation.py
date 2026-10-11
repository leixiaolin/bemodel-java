"""评测脚本本身也必须失败可见，隔离会话，核对业务数值与完整 API 契约。"""
import importlib.util
from types import SimpleNamespace
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from bemodel.config import settings
from bemodel.core.database import get_session
from bemodel.main import create_app
from bemodel.cs.services import CsService

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluation = load('eval_semantic_qa')
fixture = load('semantic_qa_eval_fixture')


def test_expected_cancel_not_refund_reads_query_row():
    class Flow:
        @staticmethod
        def query(ds, sql):
            assert ds == 'HIS'
            assert 'COUNT(*) AS n' in sql
            return [{'n': 3}]

    assert evaluation.expected_cancel_not_refund(SimpleNamespace(flow=Flow())) == 3


def test_full_entry_fixed_business_dataset_both_switches(monkeypatch):
    from bemodel.agents import runtime
    monkeypatch.setattr(runtime,'_chat_client',lambda:pytest.fail('离线评测不能创建外部模型客户端'))
    monkeypatch.setattr(settings, 'semantic_asset_enhance', False)
    off = evaluation.run_round(3, fixture.QUESTIONS, fixture.fixture_session)
    monkeypatch.setattr(settings, 'semantic_asset_enhance', True)
    on = evaluation.run_round(3, fixture.QUESTIONS, fixture.fixture_session)
    failures = []
    evaluation.check_deterministic(off, [on], 3, failures, fixture.QUESTIONS)
    assert failures == []
    rate = next(r for r in on if r['category']=='ratio')
    assert rate['expectedValue'] == 20 and rate['valueOk'] and not rate['direct']
    zero = next(r for r in on if r['category']=='zero')
    assert zero['measured']=='0笔' and zero['llmCalls']=={'CS_ROUTE':1}
    assert next(r for r in on if r['category']=='changed_metric')['fallbackReason']
    assert all(r['error'] is None for r in off+on)


def test_failure_does_not_abort_following_questions(monkeypatch):
    monkeypatch.setattr(settings, 'semantic_asset_enhance', True)
    items = fixture.QUESTIONS[:2]
    original = CsService.ask
    def ask(self, q, scene=None):
        if q == items[0]['q']:
            raise RuntimeError('sensitive connection or payload must not be logged')
        return original(self,q,scene)
    monkeypatch.setattr(CsService, 'ask', ask)
    results = evaluation.run_round(3,items,fixture.fixture_session)
    assert results[0]['error']=='RuntimeError' and results[0]['failures']
    assert results[1]['direct'] and not results[1]['failures']
    assert 'sensitive' not in str(results)


def test_real_mode_marks_failed_model_attempt(monkeypatch):
    monkeypatch.setattr(settings, 'semantic_asset_enhance', False)
    monkeypatch.setattr(evaluation.DeepSeekClient, 'chat', lambda *args, **kwargs: None)
    item = next(q for q in fixture.QUESTIONS if q['cat'] == 'plain')
    records = evaluation.run_round(3, [item], fixture.fixture_session, require_llm_success=True)
    assert any(f.startswith('真实模型调用失败:') for f in records[0]['failures'])
    summary = evaluation.summarize(records)
    assert summary['failedLlmCalls'] > 0
    assert summary['successfulLlmCalls'] + summary['failedLlmCalls'] == summary['llmCalls']


def test_wrong_business_value_fails_evaluation(monkeypatch):
    monkeypatch.setattr(settings,'semantic_asset_enhance',True)
    original = CsService.ask
    def wrong(self,q,scene=None):
        data = original(self,q,scene)
        for e in data['evidence']:
            if e['label']=='实测值':
                e['value']='999笔'
        return data
    monkeypatch.setattr(CsService,'ask',wrong)
    records = evaluation.run_round(3,fixture.QUESTIONS[:1],fixture.fixture_session)
    assert not records[0]['valueOk'] and records[0]['failures']


def test_each_question_has_independent_session(monkeypatch):
    monkeypatch.setattr(settings,'semantic_asset_enhance',True)
    sessions=[]
    @contextmanager
    def factory(item):
        with fixture.fixture_session(item) as session:
            sessions.append(session)
            yield session
    evaluation.run_round(3,fixture.QUESTIONS[:3],factory)
    assert len({id(s) for s in sessions})==3


def test_viewer_api_real_sql_and_no_business_or_monitor_writes(monkeypatch):
    from bemodel.auth.jwt_service import JwtService
    monkeypatch.setattr(settings,'semantic_asset_enhance',True)
    item=fixture.QUESTIONS[0]
    with fixture.fixture_session(item) as session:
        app=create_app(startup=False)
        app.dependency_overrides[get_session]=lambda:session
        before=list(session.execute(text('SELECT * FROM fee_detail ORDER BY order_id')))
        with TestClient(app) as client:
            token=JwtService().issue(SimpleNamespace(username='viewer',display_name=None,role='VIEWER'))
            response=client.post('/api/cs/ask',headers={'Authorization':'Bearer '+token},json={'question':item['q'],'scene':'ANALYTICS'})
        assert response.status_code==200
        body=response.json()
        assert body['code']==0 and body['msg']=='ok'
        assert '共 3 笔' in body['data']['answer']
        assert body['data']['citations']['metric']['code']=='CANCEL_NOT_REFUND'
        assert list(session.execute(text('SELECT * FROM fee_detail ORDER BY order_id')))==before
        assert session.execute(text('SELECT last_val,last_eval_at FROM bm_metric')).one()==(None,None)
