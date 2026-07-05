from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict


MAX_MARKDOWN_LENGTH = 3900


class WeComSendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    error: str | None = None
    latency_ms: int
    status_code: int | None = None


class WeComBotClient:
    def __init__(self, webhook_url: str, *, timeout_seconds: int = 10):
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    def send_text(
        self,
        content: str,
        *,
        mentioned_list: list[str] | None = None,
        mentioned_mobile_list: list[str] | None = None,
    ) -> WeComSendResult:
        payload: dict[str, Any] = {"msgtype": "text", "text": {"content": content}}
        if mentioned_list:
            payload["text"]["mentioned_list"] = mentioned_list
        if mentioned_mobile_list:
            payload["text"]["mentioned_mobile_list"] = mentioned_mobile_list
        return self._post(payload)

    def send_markdown(self, content: str) -> WeComSendResult:
        return self._post({"msgtype": "markdown", "markdown": {"content": truncate_markdown(content)}})

    def test_webhook(self) -> WeComSendResult:
        return self.send_text("加拿大尾程自动报价系统：企业微信机器人连接测试成功")

    def _post(self, payload: dict[str, Any]) -> WeComSendResult:
        started = perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.webhook_url, json=payload)
            latency_ms = int((perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return WeComSendResult(
                    success=False,
                    error=f"HTTP {response.status_code}: {_safe_error(response.text)}",
                    latency_ms=latency_ms,
                    status_code=response.status_code,
                )
            data = response.json()
            errcode = data.get("errcode")
            if errcode not in (0, None):
                return WeComSendResult(
                    success=False,
                    error=f"WeCom errcode {errcode}: {data.get('errmsg', '')}",
                    latency_ms=latency_ms,
                    status_code=response.status_code,
                )
            return WeComSendResult(success=True, latency_ms=latency_ms, status_code=response.status_code)
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            return WeComSendResult(
                success=False,
                error=f"{exc.__class__.__name__}: {exc}",
                latency_ms=latency_ms,
                status_code=None,
            )


def truncate_markdown(content: str) -> str:
    if len(content) <= MAX_MARKDOWN_LENGTH:
        return content
    suffix = "\n\n内容过长，已截断"
    return content[: MAX_MARKDOWN_LENGTH - len(suffix)] + suffix


def _safe_error(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) > 240:
        return compact[:240] + "..."
    return compact
