import httpx
import pytest
from bemodel.llm.services import DeepSeekClient
from bemodel.config import settings


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
    assert logs[0][4:] == (True, None)


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
    assert logs[0][4:] == (expected is not None, None)


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
