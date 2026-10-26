"""Personal skill grants and a deliberately limited quote interface."""
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import QuoteSkillGrant, SalesQuoteRecord, User
from apps.api.services.ai_quote_service import AIAutoQuoteRequest, calculate_ai_auto_quote
from apps.api.services.wecom_quote_worker import manual_review_reply, save_coded_reply, with_quote_defaults

CODE_TTL_SECONDS = 600
CREDENTIAL_TTL_DAYS = 90
ELIGIBLE_ROLES = ("sales", "admin")


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_grant(db: Session, user: User, name: str) -> tuple[QuoteSkillGrant, str]:
    if not user.enabled or user.role not in ELIGIBLE_ROLES:
        raise HTTPException(403, "该账号没有个人报价授权权限。")
    code = "cqa_" + secrets.token_urlsafe(24)
    now = utcnow()
    grant = QuoteSkillGrant(user_id=user.id, name=name, code_hash=secret_hash(code),
                           code_expires_at=now + timedelta(seconds=CODE_TTL_SECONDS), created_at=now)
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant, code


def bind_grant(db: Session, code: str) -> tuple[QuoteSkillGrant, User, str]:
    if not re.fullmatch(r"cqa_[A-Za-z0-9_-]{32}", code):
        raise HTTPException(401, "授权码无效、已使用或已过期。")
    now = utcnow()
    credential = "cqs_" + secrets.token_urlsafe(32)
    # A single conditional UPDATE consumes the code. Concurrent binds cannot
    # both succeed, including when the dialect does not support row locks.
    grant_id = db.scalar(update(QuoteSkillGrant).where(
        QuoteSkillGrant.code_hash == secret_hash(code),
        QuoteSkillGrant.enabled.is_(True),
        QuoteSkillGrant.credential_hash.is_(None),
        QuoteSkillGrant.code_expires_at > now,
        QuoteSkillGrant.user_id.in_(select(User.id).where(User.enabled.is_(True), User.role.in_(ELIGIBLE_ROLES))),
    ).values(credential_hash=secret_hash(credential), bound_at=now,
             credential_expires_at=now + timedelta(days=CREDENTIAL_TTL_DAYS)).returning(QuoteSkillGrant.id))
    if grant_id is None:
        db.rollback()
        raise HTTPException(401, "授权码无效、已使用或已过期。")
    db.commit()
    grant = db.get(QuoteSkillGrant, grant_id)
    user = db.get(User, grant.user_id)
    return grant, user, credential


def authenticate_grant(db: Session, credential: str) -> tuple[QuoteSkillGrant, User]:
    if not re.fullmatch(r"cqs_[A-Za-z0-9_-]{43}", credential):
        raise HTTPException(401, "Skill 尚未绑定，或授权已经失效。")
    pair = db.execute(select(QuoteSkillGrant, User).join(User).where(
        QuoteSkillGrant.credential_hash == secret_hash(credential),
        QuoteSkillGrant.enabled.is_(True), QuoteSkillGrant.credential_expires_at > utcnow(),
        User.enabled.is_(True), User.role.in_(ELIGIBLE_ROLES),
    )).first()
    if pair is None:
        raise HTTPException(401, "Skill 尚未绑定，或授权已经失效。")
    grant, user = pair
    grant.last_used_at = utcnow()
    db.commit()
    return grant, user


def public_grant(grant: QuoteSkillGrant) -> dict:
    return {"id": grant.id, "name": grant.name, "enabled": grant.enabled,
            "created_at": grant.created_at, "code_expires_at": grant.code_expires_at,
            "bound_at": grant.bound_at, "credential_expires_at": grant.credential_expires_at,
            "last_used_at": grant.last_used_at}


def personal_actor(user: User) -> CurrentActor:
    # Even an administrator's skill is a personal sales client, never an admin token.
    return CurrentActor(user_id=user.id, api_key_id=None, name=user.display_name, role="sales")


def quote_for_skill(db: Session, user: User, message: str) -> dict:
    prepared, default_note = with_quote_defaults(message, channel_label="Skill")
    actor = personal_actor(user)
    result = calculate_ai_auto_quote(db, AIAutoQuoteRequest(customer_message=prepared), actor, notify_manual=False)
    if result.manual_review_required:
        result.customer_reply = manual_review_reply(result)
    if default_note:
        result.customer_reply = (result.customer_reply or "请在报价工作台核对结果。") + "\n\n" + default_note
    save_coded_reply(db, result, actor, prepared)
    quote = result.quote_result
    # Do not expose raw model diagnostics, internal notes, or provider metadata.
    return {
        "customer_reply": result.customer_reply,
        "quote_code": result.customer_reply.splitlines()[0].removeprefix("报价编码：") if quote else None,
        "manual_review_required": result.manual_review_required,
        "missing_fields": result.missing_fields,
        "extracted_fields": result.extraction.model_dump(mode="json", include={
            "postal_code", "city", "province", "piece_count", "cbm", "weight_kg", "packaging_type",
            "longest_side_cm", "explicit_pallet_count", "address_type", "requires_appointment",
            "requires_liftgate", "requires_pallet_jack",
        }),
        "total_price_usd": str(quote.total_price_usd) if quote and quote.total_price_usd is not None else None,
    }


def public_record(record: SalesQuoteRecord) -> dict:
    return {"quote_code": record.result_json.get("quote_code"), "status": record.status,
            "created_at": record.created_at, "customer_message": record.customer_message,
            "customer_reply": record.customer_reply}
