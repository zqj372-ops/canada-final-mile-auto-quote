from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask, WeComBotConfig
from apps.api.db.repositories.wecom_bot_config_repository import GROUP_WEBHOOK_BOT_TYPE, WeComBotConfigRepository
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult
from packages.wecom.bot_client import WeComBotClient, WeComSendResult
from packages.wecom.templates import (
    build_ai_missing_fields_markdown,
    build_ai_quote_success_markdown,
    build_manual_required_markdown,
    build_manual_task_resolved_markdown,
    build_quote_success_markdown,
)


logger = logging.getLogger(__name__)
MANUAL_REQUIRED_AT_ALL_TEXT = "@all 有新的加拿大尾程报价需人工确认，请查看上一条详情。"


def notify_quote_success(
    db: Session,
    *,
    result: ZoneQuoteResult,
    request: ZoneQuoteRequest,
    bot_id: int | None = None,
) -> WeComSendResult | None:
    markdown = build_quote_success_markdown(result, request)
    return _send_markdown(db, purpose="quote_success", markdown=markdown, bot_id=bot_id)


def notify_ai_quote_success(db: Session, *, response: object, bot_id: int | None = None) -> WeComSendResult | None:
    markdown = build_ai_quote_success_markdown(response)
    return _send_markdown(db, purpose="ai_quote", markdown=markdown, bot_id=bot_id)


def notify_ai_missing_fields(
    db: Session,
    *,
    customer_reply: str,
    missing_fields: list[str],
    bot_id: int | None = None,
) -> WeComSendResult | None:
    markdown = build_ai_missing_fields_markdown(customer_reply, missing_fields)
    return _send_markdown(db, purpose="ai_quote", markdown=markdown, bot_id=bot_id)


def notify_manual_required(
    db: Session,
    *,
    result: ZoneQuoteResult,
    request: ZoneQuoteRequest,
    bot_id: int | None = None,
) -> WeComSendResult | None:
    markdown = build_manual_required_markdown(result, request)
    repository = WeComBotConfigRepository(db)
    bot = _select_bot(repository, purpose="manual_required", bot_id=bot_id)
    if bot is None:
        return None
    result = _send_with_bot(repository, bot, markdown=markdown)
    if bot.mention_all_on_manual_required:
        _send_manual_required_at_all(repository, bot)
    return result


def notify_manual_task_resolved(
    db: Session,
    *,
    task: ManualQuoteTask,
    bot_id: int | None = None,
) -> WeComSendResult | None:
    markdown = build_manual_task_resolved_markdown(task)
    return _send_markdown(db, purpose="manual_resolved", markdown=markdown, bot_id=bot_id)


def _send_markdown(
    db: Session,
    *,
    purpose: str,
    markdown: str,
    bot_id: int | None = None,
) -> WeComSendResult | None:
    repository = WeComBotConfigRepository(db)
    bot = _select_bot(repository, purpose=purpose, bot_id=bot_id)
    if bot is None:
        return None
    return _send_with_bot(repository, bot, markdown=markdown)


def _select_bot(repository: WeComBotConfigRepository, *, purpose: str, bot_id: int | None) -> WeComBotConfig | None:
    if bot_id is not None:
        bot = repository.get_config(bot_id)
        if bot is None or not bot.enabled:
            return None
        return bot
    return repository.get_by_purpose(purpose)


def _send_with_bot(
    repository: WeComBotConfigRepository,
    bot: WeComBotConfig,
    *,
    markdown: str,
) -> WeComSendResult:
    if bot.bot_type != GROUP_WEBHOOK_BOT_TYPE:
        result = WeComSendResult(
            success=False,
            error="WeComAIBotLongConnectionRequiresActiveWorker",
            latency_ms=0,
            status_code=None,
        )
        logger.warning(
            "WeCom bot notification skipped for non-webhook bot.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "bot_type": bot.bot_type},
        )
        return result
    webhook_url = repository.decrypt_webhook_url(bot)
    if not webhook_url:
        return WeComSendResult(success=False, error="WeComWebhookUrlMissing", latency_ms=0, status_code=None)
    client = WeComBotClient(webhook_url)
    try:
        result = client.send_markdown(markdown)
    except Exception as exc:
        logger.warning(
            "WeCom bot notification failed.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "error": exc.__class__.__name__},
        )
        return WeComSendResult(success=False, error=exc.__class__.__name__, latency_ms=0, status_code=None)
    if not result.success:
        logger.warning(
            "WeCom bot notification failed.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "error": result.error},
        )
    return result


def _send_manual_required_at_all(repository: WeComBotConfigRepository, bot: WeComBotConfig) -> None:
    if bot.bot_type != GROUP_WEBHOOK_BOT_TYPE:
        logger.warning(
            "WeCom bot @all reminder skipped for non-webhook bot.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "bot_type": bot.bot_type},
        )
        return
    webhook_url = repository.decrypt_webhook_url(bot)
    if not webhook_url:
        logger.warning(
            "WeCom bot @all reminder skipped because webhook URL is missing.",
            extra={"bot_id": bot.id, "purpose": bot.purpose},
        )
        return
    try:
        result = WeComBotClient(webhook_url).send_text(MANUAL_REQUIRED_AT_ALL_TEXT, mentioned_list=["@all"])
    except Exception as exc:
        logger.warning(
            "WeCom bot @all reminder failed.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "error": exc.__class__.__name__},
        )
        return
    if not result.success:
        logger.warning(
            "WeCom bot @all reminder failed.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "error": result.error},
        )
