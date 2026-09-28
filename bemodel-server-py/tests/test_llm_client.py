import httpx
import pytest
import bemodel.llm.services as llm_services
from bemodel.config import settings
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



@pytest.fixture
def gateway(session, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test-only-key")
    client = DeepSeekClient(session)
    entries = []
    monkeypatch.setattr(client.logs, "log", lambda *args: entries.append(args))
    return client, entries


def test_chat_request_contract(gateway, monkeypatch):
    client, logs = gateway
    monkeypatch.setattr(settings, "deepseek_base_url", "https://example.invalid/")
    monkeypatch.setattr(settings, "deepseek_timeout_seconds", 7)
    def post(url, **kwargs):
        assert url == "https://example.invalid/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-only-key"
        assert kwargs["timeout"] == 7
        assert kwargs["json"] == {"model": settings.deepseek_model, "temperature": .2,
            "messages": [{"role": "system", "content": "系统"}, {"role": "user", "content": "问题"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": "回答"}}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    assert client.chat("QA", "系统", "问题") == "回答"
    assert logs[0][2] == "系统 | 问题"
    assert logs[0][4:6] == (True, None)


@pytest.mark.parametrize("body,expected", [
    ({}, None), ({"choices": None}, None), ({"choices": [None]}, None),
    ({"choices": [{"message": None}]}, None), ([], None),
    ({"choices": [{"message": {"content": None}}]}, None),
    ({"choices": [{"message": {"content": {"unexpected": 1}}}]}, ""),
    ({"choices": [{"message": {"content": [1]}}]}, ""),
    ({"choices": [{"message": {"content": True}}]}, "true"),
    ({"choices": [{"message": {"content": 42}}]}, "42"),
])
def test_jackson_content_coercion(gateway, monkeypatch, body, expected):
    client, logs = gateway
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=body,
        request=httpx.Request("POST", "https://example.invalid")))
    assert client.chat("QA", None, None) == expected
    assert logs[0][4:6] == (expected is not None, None)


@pytest.mark.parametrize("failure", ["timeout", "http", "json"])
def test_failures_degrade_and_record_audit(gateway, monkeypatch, failure):
    client, logs = gateway
    def post(*args, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout("test timeout")
        return httpx.Response(503 if failure == "http" else 200, text="invalid json",
            request=httpx.Request("POST", "https://example.invalid"))
    monkeypatch.setattr(httpx, "post", post)
    assert client.chat("QA", "s", "u") is None
    assert len(logs) == 1 and logs[0][4] is False and logs[0][5]


def test_missing_key_never_sends_request(gateway, monkeypatch):
    client, logs = gateway
    monkeypatch.setattr(settings, "deepseek_api_key", "  ")
    def forbidden(*args, **kwargs):
        pytest.fail("No key must not perform an HTTP request")
    monkeypatch.setattr(httpx, "post", forbidden)
    assert client.chat("QA", "s", "u") is None
    assert logs[0][3:] == (0, False, "API Key 未配置")
