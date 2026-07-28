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
        def __init__(self, *, timeout: int):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> FakeResponse:
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("packages.ai_assistant.model_client.httpx.Client", FakeClient)
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
