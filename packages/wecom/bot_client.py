from __future__ import annotations

import asyncio
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
                error=exc.__class__.__name__,
                latency_ms=latency_ms,
                status_code=None,
            )


class WeComAIBotLongConnectionClient:
    def __init__(self, bot_id: str, secret: str, *, timeout_seconds: int = 8):
        self.bot_id = bot_id
        self.secret = secret
        self.timeout_seconds = timeout_seconds

    def test_connection(self) -> WeComSendResult:
        started = perf_counter()
        try:
            asyncio.run(self._test_connection_async())
            latency_ms = int((perf_counter() - started) * 1000)
            return WeComSendResult(success=True, latency_ms=latency_ms, status_code=None)
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            return WeComSendResult(
                success=False,
                error=_safe_aibot_error(exc),
                latency_ms=latency_ms,
                status_code=None,
            )

    async def _test_connection_async(self) -> None:
        try:
            from aibot import WSClient, WSClientOptions
        except ImportError as exc:
            raise RuntimeError("WeComAIBotSDKNotInstalled") from exc

        authenticated = asyncio.Event()
        errors: list[Exception] = []
        client = WSClient(
            WSClientOptions(
                bot_id=self.bot_id,
                secret=self.secret,
                max_reconnect_attempts=0,
                request_timeout=self.timeout_seconds * 1000,
                logger=_SilentAIBotLogger(),
            )
        )
        client.on("authenticated", lambda: authenticated.set())
        client.on("error", lambda error: errors.append(error))
        try:
            await asyncio.wait_for(client.connect(), timeout=self.timeout_seconds)
            await asyncio.wait_for(authenticated.wait(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            if errors:
                raise RuntimeError(
                    f"WeComAIBotConnectionError:{self._safe_sdk_error(errors[-1])}"
                ) from exc
            raise RuntimeError("WeComAIBotAuthTimeout") from exc
        finally:
            client.disconnect()

    def _safe_sdk_error(self, exc: Exception) -> str:
        message = str(exc)
        if self.bot_id:
            message = message.replace(self.bot_id, "<bot_id>")
        if self.secret:
            message = message.replace(self.secret, "<secret>")
        compact = " ".join(message.split())
        if not compact:
            return exc.__class__.__name__
        if len(compact) > 120:
            compact = compact[:120] + "..."
        return f"{exc.__class__.__name__}:{compact}"


class _SilentAIBotLogger:
    def debug(self, *_args: object) -> None:
        return None

    def info(self, *_args: object) -> None:
        return None

    def warn(self, *_args: object) -> None:
        return None

    def error(self, *_args: object) -> None:
        return None


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


def _safe_aibot_error(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("WeComAIBot"):
        return message
    return exc.__class__.__name__
