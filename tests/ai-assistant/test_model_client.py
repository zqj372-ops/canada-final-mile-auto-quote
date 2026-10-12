import json
import pytest
from packages.ai_assistant.http_pool import close_model_http_clients

from packages.ai_assistant.model_client import (
    AIMessage,
    AIModelConfig,
    OpenAICompatibleClient,
    _extract_openai_content,
)


def test_extract_openai_content_strips_think_tags() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": "<think>private reasoning</think>\n\nok",
                }
            }
        ]
    }

    assert _extract_openai_content(data) == "ok"


def test_minimax_request_separates_reasoning_and_uses_completion_token_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_bytes(self):
            yield json.dumps(self.json()).encode()

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"status":"ok"}',
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: int, limits):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def close(self):
            return None

        def __exit__(self, *_args: object) -> None:
            return None

        def stream(self, method: str, url: str, *, json: dict[str, object], headers: dict[str, str], timeout) -> FakeResponse:
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("packages.ai_assistant.http_pool.httpx.Client", FakeClient)
    client = OpenAICompatibleClient(
        AIModelConfig(
            provider="minimax",
            base_url="https://api.minimax.chat/v1",
            api_key="test-key",
            model_name="MiniMax-M3",
            max_tokens=1200,
        )
    )

    response = client.complete([AIMessage(role="user", content="Return JSON.")])

    assert response.error is None
    assert response.content == '{"status":"ok"}'
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["reasoning_split"] is True
    assert payload["max_completion_tokens"] == 1200
    assert "max_tokens" not in payload


@pytest.fixture(autouse=True)
def clean_http_pool():
    close_model_http_clients()
    yield
    close_model_http_clients()


def test_connections_are_reused_and_credentials_are_isolated(monkeypatch):
    from packages.ai_assistant.http_pool import model_http_client
    instances = []
    class FakeClient:
        def __init__(self, **kwargs):
            self.closed = False
            instances.append(self)
        def close(self):
            self.closed = True
    monkeypatch.setattr("packages.ai_assistant.http_pool.httpx.Client", FakeClient)
    with model_http_client("https://fixture.invalid/v1", "fixture-a", 30) as first:
        pass
    with model_http_client("https://fixture.invalid/v1", "fixture-a", 30) as second:
        assert first is second
    with model_http_client("https://fixture.invalid/v1", "fixture-b", 30) as third:
        assert third is not first
    assert len(instances) == 2
    close_model_http_clients()
    assert all(item.closed for item in instances)
