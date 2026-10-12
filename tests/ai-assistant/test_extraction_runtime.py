from time import perf_counter, sleep

import pytest

from packages.ai_assistant.extraction_runtime import ObservedAIClient
from packages.ai_assistant.model_client import AIResponse
from packages.ai_assistant.quote_extractor import QuoteExtractionError, extract_quote_draft_with_agents
from packages.ai_assistant.service_requirements import explicit_service_requirements


@pytest.mark.parametrize("text,expected", [
    ("是否需要尾板？", None), ("liftgate not required?", None),
    ("Deliver to 100 Fixture Street", None), ("尾板: 否", False),
    ("不需要尾板", False), ("无需尾板", False), ("需要尾板", True),
    ("no liftgate required", False), ("with liftgate", True),
    ("liftgate: yes\nliftgate: no", None), ("requires_liftgate=false", False),
])
def test_service_omission_negation_and_conflicts(text, expected):
    assert explicit_service_requirements(text)["requires_liftgate"] is expected


def test_deadline_returns_without_waiting_for_slow_workers():
    class SlowClient:
        def complete(self, messages):
            sleep(0.12)
            return AIResponse(content="{}")
    started = perf_counter()
    client = ObservedAIClient(SlowClient(), deadline=started + 0.025)
    with pytest.raises(QuoteExtractionError, match="deadline"):
        extract_quote_draft_with_agents("fixture", client, deadline=client.deadline)
    assert perf_counter() - started < 0.09
    assert client.snapshot()["model_calls"] == 2
    sleep(0.13)  # Join the short fixture work before other tests reuse the global pool.
    assert client.snapshot()["repair_calls"] == 0
