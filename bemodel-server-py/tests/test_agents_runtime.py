"""MAF 适配层：key 未配置降级 + 审计落库（不触达真实 DeepSeek）。"""

from bemodel.agents.critic import SqlCritic
from bemodel.agents.runtime import CRITIC_CALL_TYPE, critic_chat
from bemodel.config import settings
from bemodel.llm.entities import LlmLog
from types import SimpleNamespace
import pytest
import bemodel.agents.runtime as runtime


def test_critic_chat_degrades_without_api_key(session, monkeypatch):
    monkeypatch.setattr(settings, 'deepseek_api_key', '')

    assert critic_chat(session, 'system', 'user') is None

    logs = session.query(LlmLog).all()
    assert len(logs) == 1
    assert logs[0].call_type == CRITIC_CALL_TYPE
    assert logs[0].success == 0 and logs[0].err_msg == 'API Key 未配置'


def test_judge_returns_none_when_runtime_degrades(session, monkeypatch):
    monkeypatch.setattr(settings, 'deepseek_api_key', '')

    assert SqlCritic(session).judge('问题', '上下文', 'SQL', '结果', '样例') is None


@pytest.mark.parametrize('fails', [False, True])
def test_critic_logs_full_prompt_before_request(session, monkeypatch, caplog, fails):
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-only-secret')
    system = 'SQL校验系统提示\n' * 50
    user = '问题、上下文、SQL和查询结果\n' * 100
    captured = []

    class FakeClient:
        async def get_response(self, messages, **kwargs):
            captured.append((messages[0].text, messages[1].text, caplog.text))
            if fails:
                raise RuntimeError('模拟调用失败')
            return SimpleNamespace(text='校验结果')

    monkeypatch.setattr(runtime, '_chat_client', FakeClient)
    with caplog.at_level('INFO', logger='bemodel.llm.services'):
        assert critic_chat(session, system, user) == (None if fails else '校验结果')
    assert len(captured) == 1
    assert captured[0][:2] == (system, user)
    assert '[system]\n' + system in captured[0][2]
    assert '[user]\n' + user in captured[0][2]
    assert caplog.text.count('LLM prompt call_type=CS_SEMANTIC_CRITIQUE') == 1
    assert 'model=' + settings.deepseek_model in caplog.text
    assert 'test-only-secret' not in caplog.text
