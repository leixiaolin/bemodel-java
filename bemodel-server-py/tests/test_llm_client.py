import bemodel.llm.services as llm_services
from bemodel.llm.entities import LlmLog
from bemodel.llm.services import DeepSeekClient


class FakeResponse:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def call_with_capture(monkeypatch, session, content):
    captured = {}

    def fake_post(url, headers=None, timeout=None, json=None):
        captured["payload"] = json
        return FakeResponse(content)

    monkeypatch.setattr(llm_services.httpx, "post", fake_post)
    monkeypatch.setattr(llm_services.settings, "deepseek_api_key", " test-key ")
    return captured, DeepSeekClient(session)


def test_structured_calls_use_zero_temperature(monkeypatch, session):
    """标签/JSON 类结构化输出调用采样温度归零，避免同一问题路由/规划抖动。"""
    for call_type in ("CS_ROUTE", "CS_SEMANTIC_PLAN", "MAPPING_SUGGEST", "MISS_CLASSIFY"):
        captured, client = call_with_capture(monkeypatch, session, "x")
        client.chat(call_type, "s", "u")
        assert captured["payload"]["temperature"] == 0, call_type


def test_free_text_calls_keep_default_temperature(monkeypatch, session):
    """自由文本答复保留 0.2 采样。"""
    for call_type in ("CS_REPLY", "CS_SEMANTIC_ANSWER", "RCA_REPORT", "SEARCH_ANSWER"):
        captured, client = call_with_capture(monkeypatch, session, "x")
        client.chat(call_type, "s", "u")
        assert captured["payload"]["temperature"] == 0.2, call_type


def test_response_digest_recorded(monkeypatch, session):
    """审计日志记录模型输出摘要，便于事后排查答案抖动。"""
    _, client = call_with_capture(monkeypatch, session, '{"mode":"QUERY"}')
    assert client.chat("CS_SEMANTIC_PLAN", "s", "u") == '{"mode":"QUERY"}'
    row = session.query(LlmLog).order_by(LlmLog.id.desc()).first()
    assert row is not None and row.success == 1
    assert row.response_digest == '{"mode":"QUERY"}'


def test_response_digest_truncated_to_512(monkeypatch, session):
    _, client = call_with_capture(monkeypatch, session, "x" * 900)
    client.chat("CS_ROUTE", "s", "u")
    row = session.query(LlmLog).order_by(LlmLog.id.desc()).first()
    assert len(row.response_digest) == 512


def test_failure_records_no_response_digest(monkeypatch, session):
    """调用失败时 err_msg 有值、response_digest 为空。"""

    def fake_post(url, headers=None, timeout=None, json=None):
        raise llm_services.httpx.ConnectError("boom")

    monkeypatch.setattr(llm_services.httpx, "post", fake_post)
    monkeypatch.setattr(llm_services.settings, "deepseek_api_key", " test-key ")
    assert DeepSeekClient(session).chat("CS_ROUTE", "s", "u") is None
    row = session.query(LlmLog).order_by(LlmLog.id.desc()).first()
    assert row.success == 0 and "boom" in (row.err_msg or "")
    assert row.response_digest is None
