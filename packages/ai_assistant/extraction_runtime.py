"""Bounded extraction workers and request-local model observations."""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from time import perf_counter

from packages.ai_assistant.model_client import AIResponse, BaseAIClient, OpenAICompatibleClient

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="quote-extraction")
_slots = BoundedSemaphore(16)


def submit_extraction(function, *args, **kwargs):
    if not _slots.acquire(blocking=False):
        raise RuntimeError("extraction_capacity_exceeded")
    try:
        future = _pool.submit(function, *args, **kwargs)
    except Exception:
        _slots.release()
        raise
    future.add_done_callback(lambda _: _slots.release())
    return future


class ObservedAIClient:
    def __init__(self, client: BaseAIClient, *, deadline: float):
        self.client = (OpenAICompatibleClient(client.config, deadline=min(deadline, client.deadline or deadline))
                       if isinstance(client, OpenAICompatibleClient) else client)
        self.deadline = deadline
        self._lock = Lock()
        self._calls: list[dict] = []

    def complete(self, messages):
        if perf_counter() >= self.deadline:
            return AIResponse(error="extraction_deadline_exceeded", latency_ms=0)
        started = perf_counter()
        record = {"repair": any(message.role == "assistant" for message in messages), "status": "running"}
        with self._lock:
            self._calls.append(record)
        try:
            response = self.client.complete(messages)
        except Exception as exc:
            response = AIResponse(error=type(exc).__name__)
        usage = (response.raw or {}).get("usage") or {}
        with self._lock:
            record.update(status="error" if response.error else "completed",
                          latency_ms=round((perf_counter() - started) * 1000),
                          prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
        return response

    def snapshot(self):
        with self._lock:
            calls = [dict(item) for item in self._calls]
        return {"model_calls": len(calls), "repair_calls": sum(item["repair"] for item in calls), "calls": calls}
