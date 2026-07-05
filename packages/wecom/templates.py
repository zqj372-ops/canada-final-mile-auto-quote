from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.api.db.models import ManualQuoteTask
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


def build_quote_success_markdown(result: ZoneQuoteResult, request: ZoneQuoteRequest) -> str:
    return "\n".join(
        [
            "### 加拿大尾程报价成功",
            f"- quote_id: `{result.quote_id}`",
            f"- address_line: {request.address_line or '-'}",
            f"- postal_code: {request.postal_code}",
            f"- city/province: {result.city or request.city or '-'} / {result.province or request.province or '-'}",
            f"- origin: {result.origin or '-'}",
            f"- zone: {result.zone if result.zone is not None else '-'}",
            f"- billing_pallets: {result.billing_pallets if result.billing_pallets is not None else '-'}",
            f"- total_price_usd: {_money(result.total_price_usd)}",
            f"- risk_tags: {_tags(result.risk_tags)}",
            "",
            "**sales_note**",
            result.sales_note or "-",
        ]
    )


def build_ai_quote_success_markdown(response: Any) -> str:
    quote_result = response.quote_result
    extraction = response.extraction
    return "\n".join(
        [
            "### AI 自动报价成功",
            f"- quote_id: `{quote_result.quote_id}`",
            f"- 提取置信度: {extraction.confidence}",
            f"- total_price_usd: {_money(quote_result.total_price_usd)}",
            f"- risk_tags: {_tags(quote_result.risk_tags)}",
            "",
            "**sales_note/customer_reply**",
            response.customer_reply or quote_result.sales_note or "-",
        ]
    )


def build_manual_required_markdown(result: ZoneQuoteResult, request: ZoneQuoteRequest) -> str:
    return "\n".join(
        [
            "### ⚠️ 加拿大尾程报价需人工确认",
            f"- quote_id: `{result.quote_id}`",
            f"- matched_rule: {result.matched_rule}",
            f"- risk_tags: {_tags(result.risk_tags)}",
            f"- address_line: {request.address_line or '-'}",
            f"- postal_code: {request.postal_code}",
            f"- city/province: {result.city or request.city or '-'} / {result.province or request.province or '-'}",
            "",
            "请运营/供应商确认后在人工任务中处理。",
        ]
    )


def build_manual_task_resolved_markdown(task: ManualQuoteTask) -> str:
    return "\n".join(
        [
            "### 加拿大尾程人工报价已处理",
            f"- quote_id: `{task.quote_id}`",
            f"- resolved_price_usd: {_money(task.resolved_price_usd)}",
            f"- assigned_to: {task.assigned_to or '-'}",
            f"- resolved_note: {task.resolved_note or '-'}",
            f"- status: {task.status}",
        ]
    )


def build_ai_missing_fields_markdown(customer_reply: str, missing_fields: list[str]) -> str:
    return "\n".join(
        [
            "### AI 自动报价缺少字段",
            f"- missing_fields: {_tags(missing_fields)}",
            "",
            customer_reply,
        ]
    )


def _money(value: Decimal | str | int | float | None) -> str:
    if value is None:
        return "-"
    try:
        return f"${Decimal(str(value)):.2f} USD"
    except Exception:
        return str(value)


def _tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "-"
