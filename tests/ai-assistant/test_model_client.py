from packages.ai_assistant.model_client import _extract_openai_content


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

