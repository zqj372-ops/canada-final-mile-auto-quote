from __future__ import annotations

import re
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field


class AIModelConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    model_name: str
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1)
    timeout_seconds: int = Field(default=30, ge=1)


class AIMessage(BaseModel):
    role: str
    content: str


class AIResponse(BaseModel):
    content: str = ""
    raw: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int | None = None


class BaseAIClient(Protocol):
    def complete(self, messages: list[AIMessage]) -> AIResponse:
        ...


class OpenAICompatibleClient:
    def __init__(self, config: AIModelConfig):
        self.config = config

    def complete(self, messages: list[AIMessage]) -> AIResponse:
        if not self.config.base_url:
            return AIResponse(error="AI base_url is required.")
        if not self.config.api_key:
            return AIResponse(error="AI api_key is required.")

        url = self._chat_completion_url()
        payload = {
            "model": self.config.model_name,
            "messages": [message.model_dump() for message in messages],
            "temperature": self.config.temperature,
        }
        if self.config.provider == "minimax":
            # MiniMax reasoning models expose the final answer separately when
            # reasoning_split is enabled. Keeping <think> content out of
            # message.content makes downstream JSON contracts deterministic.
            payload["max_completion_tokens"] = self.config.max_tokens
            payload["reasoning_split"] = True
        else:
            payload["max_tokens"] = self.config.max_tokens
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        started = perf_counter()
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
            latency_ms = int((perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return AIResponse(
                    error=f"AI provider returned HTTP {response.status_code}: {_safe_error_body(response.text)}",
                    latency_ms=latency_ms,
                )
            data = response.json()
            content = _extract_openai_content(data)
            return AIResponse(content=content, raw=data, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            return AIResponse(error=f"{exc.__class__.__name__}: {exc}", latency_ms=latency_ms)

    def _chat_completion_url(self) -> str:
        base = (self.config.base_url or "").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def config_from_record(record: object, *, api_key: str | None) -> AIModelConfig:
    return AIModelConfig(
        provider=str(getattr(record, "provider")),
        base_url=getattr(record, "base_url"),
        api_key=api_key,
        model_name=str(getattr(record, "model_name")),
        temperature=float(getattr(record, "temperature")),
        max_tokens=int(getattr(record, "max_tokens")),
        timeout_seconds=int(getattr(record, "timeout_seconds")),
    )


def _extract_openai_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        return _strip_think_tags(content) if isinstance(content, str) else ""
    text = first.get("text")
    return _strip_think_tags(text) if isinstance(text, str) else ""


def _strip_think_tags(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL).strip()


def _safe_error_body(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) > 300:
        return compact[:300] + "..."
    return compact
