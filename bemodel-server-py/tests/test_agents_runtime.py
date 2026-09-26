"""MAF 适配层：key 未配置降级 + 审计落库（不触达真实 DeepSeek）。"""

from bemodel.agents.critic import SqlCritic
from bemodel.agents.runtime import CRITIC_CALL_TYPE, critic_chat
from bemodel.config import settings
from bemodel.llm.entities import LlmLog


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
