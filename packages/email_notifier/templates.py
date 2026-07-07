from __future__ import annotations

from typing import Any

from apps.api.db.models import ManualQuoteTask
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult
from packages.wecom.templates import (
    build_ai_missing_fields_markdown,
    build_ai_quote_success_markdown,
    build_manual_required_markdown,
    build_manual_task_resolved_markdown,
    build_quote_success_markdown,
)


def build_quote_success_email(result: ZoneQuoteResult, request: ZoneQuoteRequest) -> tuple[str, str]:
    return (
        f"[Canada Quote] 报价成功 {result.quote_id}",
        _email_body(build_quote_success_markdown(result, request)),
    )


def build_ai_quote_success_email(response: Any) -> tuple[str, str]:
    quote_id = getattr(getattr(response, "quote_result", None), "quote_id", "unknown")
    return (
        f"[Canada Quote] AI 报价成功 {quote_id}",
        _email_body(build_ai_quote_success_markdown(response)),
    )


def build_ai_missing_fields_email(customer_reply: str, missing_fields: list[str]) -> tuple[str, str]:
    return (
        "[Canada Quote] AI 报价缺少字段",
        _email_body(build_ai_missing_fields_markdown(customer_reply, missing_fields)),
    )


def build_manual_required_email(result: ZoneQuoteResult, request: ZoneQuoteRequest) -> tuple[str, str]:
    return (
        f"[Canada Quote] 需要人工确认 {result.quote_id}",
        _email_body(build_manual_required_markdown(result, request)),
    )


def build_manual_task_resolved_email(task: ManualQuoteTask) -> tuple[str, str]:
    return (
        f"[Canada Quote] 人工报价已处理 {task.quote_id}",
        _email_body(build_manual_task_resolved_markdown(task)),
    )


def _email_body(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        clean = line.replace("### ", "").replace("**", "").replace("`", "")
        lines.append(clean)
    return "\n".join(lines).strip() + "\n"
