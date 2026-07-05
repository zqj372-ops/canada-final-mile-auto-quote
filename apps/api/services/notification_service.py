from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask, WeComBotConfig
from apps.api.db.repositories.wecom_bot_config_repository import WeComBotConfigRepository
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
    return _send_with_bot(
        repository,
        bot,
        markdown=markdown,
        mention_all=bot.mention_all_on_manual_required,
    )


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
    mention_all: bool = False,
) -> WeComSendResult:
    webhook_url = repository.decrypt_webhook_url(bot)
    client = WeComBotClient(webhook_url)
    result = (
        client.send_text(markdown, mentioned_list=["@all"])
        if mention_all
        else client.send_markdown(markdown)
    )
    if not result.success:
        logger.warning(
            "WeCom bot notification failed.",
            extra={"bot_id": bot.id, "purpose": bot.purpose, "error": result.error},
        )
    return result
