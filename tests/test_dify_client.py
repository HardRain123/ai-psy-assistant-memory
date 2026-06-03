import httpx

from tests.dify_client import DEFAULT_DIFY_API_BASE, DifyClient


def test_dify_client_uses_official_chatflow_request_shape(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "answer": "可以，我们先把今天的压力拆小一点。",
                "conversation_id": "conv-123",
                "message_id": "msg-456",
            }

    class FakeHttpxClient:
        def __init__(self, timeout, trust_env):
            captured["timeout"] = timeout
            captured["trust_env"] = trust_env

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("tests.dify_client.httpx.Client", FakeHttpxClient)

    client = DifyClient(api_key="test-key", timeout_seconds=12)
    response = client.chat(
        user_id="codex-e2e-test-user-unit",
        query="用户输入",
        conversation_id="conv-previous",
    )

    assert captured["timeout"] == 12
    assert captured["trust_env"] is False
    assert captured["url"] == f"{DEFAULT_DIFY_API_BASE}/chat-messages"
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "inputs": {"user_id": "codex-e2e-test-user-unit"},
        "query": "用户输入",
        "response_mode": "blocking",
        "conversation_id": "conv-previous",
        "user": "codex-e2e-test-user-unit",
    }
    assert response.answer
    assert response.conversation_id == "conv-123"
    assert response.message_identifier == "msg-456"


def test_dify_client_env_defaults(monkeypatch):
    monkeypatch.setenv("DIFY_API_KEY", "env-key")
    monkeypatch.delenv("DIFY_API_BASE", raising=False)
    monkeypatch.delenv("DIFY_E2E_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DIFY_E2E_MAX_RETRIES", raising=False)

    client = DifyClient.from_env()

    assert client.api_base == DEFAULT_DIFY_API_BASE
    assert client.timeout_seconds == 60
    assert client.trust_env is False
    assert client.max_retries == 2


def test_dify_client_retries_transient_http_error(monkeypatch):
    calls = {"count": 0}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "answer": "可以，我们先把任务缩小一点。",
                "conversation_id": "conv-retry",
                "message_id": "msg-retry",
            }

    class FakeHttpxClient:
        def __init__(self, timeout, trust_env):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.RemoteProtocolError("server disconnected")
            return FakeResponse()

    monkeypatch.setattr("tests.dify_client.httpx.Client", FakeHttpxClient)
    monkeypatch.setattr("tests.dify_client.time.sleep", lambda seconds: None)

    client = DifyClient(api_key="test-key", max_retries=1)
    response = client.chat(user_id="codex-e2e-test-user-unit", query="继续")

    assert calls["count"] == 2
    assert response.conversation_id == "conv-retry"
