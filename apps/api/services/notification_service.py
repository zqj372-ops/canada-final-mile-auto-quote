from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy.orm import Session

from apps.api.db.models import EmailNotificationConfig, ManualQuoteTask, WeComBotConfig
from apps.api.db.repositories.email_notification_config_repository import EmailNotificationConfigRepository
from apps.api.db.repositories.wecom_bot_config_repository import GROUP_WEBHOOK_BOT_TYPE, WeComBotConfigRepository
from packages.email_notifier.client import EmailSendResult, SmtpEmailClient
from packages.email_notifier.templates import (
    build_ai_missing_fields_email,
    build_ai_quote_success_email,
    build_manual_required_email,
    build_manual_task_resolved_email,
    build_quote_success_email,
)
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
NotificationSendResult = EmailSendResult | WeComSendResult
NotificationChannel = Literal["email", "wecom"]


def notify_quote_success(
    db: Session,
    *,
    result: ZoneQuoteResult,
    request: ZoneQuoteRequest,
    bot_id: int | None = None,
    email_config_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
) -> NotificationSendResult | None:
    markdown = build_quote_success_markdown(result, request)
    subject, body_text = build_quote_success_email(result, request)
    return _send_notification(
        db,
        purpose="quote_success",
        subject=subject,
        body_text=body_text,
        markdown=markdown,
        bot_id=bot_id,
        email_config_id=email_config_id,
        channels=channels,
    )


def notify_ai_quote_success(
    db: Session,
    *,
    response: object,
    bot_id: int | None = None,
    email_config_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
) -> NotificationSendResult | None:
    markdown = build_ai_quote_success_markdown(response)
    subject, body_text = build_ai_quote_success_email(response)
    return _send_notification(
        db,
        purpose="ai_quote",
        subject=subject,
        body_text=body_text,
        markdown=markdown,
        bot_id=bot_id,
        email_config_id=email_config_id,
        channels=channels,
    )


def notify_ai_missing_fields(
    db: Session,
    *,
    customer_reply: str,
    missing_fields: list[str],
    bot_id: int | None = None,
    email_config_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
) -> NotificationSendResult | None:
    markdown = build_ai_missing_fields_markdown(customer_reply, missing_fields)
    subject, body_text = build_ai_missing_fields_email(customer_reply, missing_fields)
    return _send_notification(
        db,
        purpose="ai_quote",
        subject=subject,
        body_text=body_text,
        markdown=markdown,
        bot_id=bot_id,
        email_config_id=email_config_id,
        channels=channels,
    )


def notify_manual_required(
    db: Session,
    *,
    result: ZoneQuoteResult,
    request: ZoneQuoteRequest,
    bot_id: int | None = None,
    email_config_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
) -> NotificationSendResult | None:
    markdown = build_manual_required_markdown(result, request)
    subject, body_text = build_manual_required_email(result, request)
    legacy_email_selected = False
    if channels is None:
        email_repository = EmailNotificationConfigRepository(db)
        legacy_email_selected = _select_email_config(
            email_repository,
            purpose="manual_required",
            email_config_id=email_config_id,
        ) is not None
    result = _send_notification(
        db,
        purpose="manual_required",
        subject=subject,
        body_text=body_text,
        markdown=markdown,
        bot_id=bot_id,
        email_config_id=email_config_id,
        channels=channels,
    )
    should_mention_wecom = "wecom" in channels if channels is not None else not legacy_email_selected and email_config_id is None
    if should_mention_wecom:
        repository = WeComBotConfigRepository(db)
        bot = _select_bot(repository, purpose="manual_required", bot_id=bot_id)
        if bot is not None and bot.mention_all_on_manual_required:
            _send_manual_required_at_all(repository, bot)
    return result


def notify_manual_task_resolved(
    db: Session,
    *,
    task: ManualQuoteTask,
    bot_id: int | None = None,
    email_config_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
) -> NotificationSendResult | None:
    markdown = build_manual_task_resolved_markdown(task)
    subject, body_text = build_manual_task_resolved_email(task)
    return _send_notification(
        db,
        purpose="manual_resolved",
        subject=subject,
        body_text=body_text,
        markdown=markdown,
        bot_id=bot_id,
        email_config_id=email_config_id,
        channels=channels,
    )


def _send_notification(
    db: Session,
    *,
    purpose: str,
    subject: str,
    body_text: str,
    markdown: str,
    bot_id: int | None = None,
    email_config_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
) -> NotificationSendResult | None:
    if channels is None:
        email_repository = EmailNotificationConfigRepository(db)
        email_config = _select_email_config(email_repository, purpose=purpose, email_config_id=email_config_id)
        if email_config is not None:
            return _send_with_email_config(email_repository, email_config, subject=subject, body_text=body_text)
        if email_config_id is not None:
            return None
        return _send_markdown(db, purpose=purpose, markdown=markdown, bot_id=bot_id)

    result: NotificationSendResult | None = None
    if "email" in channels:
        email_repository = EmailNotificationConfigRepository(db)
        email_config = _select_email_config(email_repository, purpose=purpose, email_config_id=email_config_id)
        if email_config is not None:
            result = _send_with_email_config(email_repository, email_config, subject=subject, body_text=body_text)
    if "wecom" in channels:
        wecom_result = _send_markdown(db, purpose=purpose, markdown=markdown, bot_id=bot_id)
        if wecom_result is not None:
            result = wecom_result
    return result


def requested_notification_channels(*, email: bool, wecom: bool) -> set[NotificationChannel]:
    channels: set[NotificationChannel] = set()
    if email:
        channels.add("email")
    if wecom:
        channels.add("wecom")
    return channels


def _select_email_config(
    repository: EmailNotificationConfigRepository,
    *,
    purpose: str,
    email_config_id: int | None,
) -> EmailNotificationConfig | None:
    if email_config_id is not None:
        record = repository.get_config(email_config_id)
        if record is None or not record.enabled:
            return None
        return record
    return repository.get_by_purpose(purpose)


def _send_with_email_config(
    repository: EmailNotificationConfigRepository,
    record: EmailNotificationConfig,
    *,
    subject: str,
    body_text: str,
) -> EmailSendResult:
    try:
        result = SmtpEmailClient(
            smtp_host=record.smtp_host,
            smtp_port=record.smtp_port,
            username=record.username,
            password=repository.decrypt_password(record),
            from_email=record.from_email,
            from_name=record.from_name,
            use_tls=record.use_tls,
            use_ssl=record.use_ssl,
        ).send(subject=subject, body_text=body_text, to_emails=list(record.recipient_emails or []))
    except Exception as exc:
        logger.warning(
            "Email notification failed.",
            extra={"email_config_id": record.id, "purpose": record.purpose, "error": exc.__class__.__name__},
        )
        return EmailSendResult(success=False, error=exc.__class__.__name__, latency_ms=0, status_code=None)
    if not result.success:
        logger.warning(
            "Email notification failed.",
            extra={"email_config_id": record.id, "purpose": record.purpose, "error": result.error},
        )
    return result


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
