"""Verified extraction receipts and reviewed correction labels in quote audits."""
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import QuoteAuditLog
from packages.quote_engine.zone_models import ZoneQuoteRequest

_PROCESS_SECRET = secrets.token_bytes(32)
CorrectionReason = Literal["extraction_error", "customer_update", "business_decision"]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _identity(actor: CurrentActor | None):
    return [actor.user_id, actor.api_key_id, actor.name] if actor else None


def _signature(encoded: str) -> str:
    configured = os.getenv("EXTRACTION_RECEIPT_SECRET") or os.getenv("AUTH_TOKEN_SECRET")
    secret = configured.encode() if configured else _PROCESS_SECRET
    return hmac.new(secret, b"quote-extraction-v1:" + encoded.encode(), hashlib.sha256).hexdigest()


def issue_extraction_receipt(raw: str, snapshot: dict, metadata: dict, actor: CurrentActor | None) -> str:
    body = {"raw_hash": digest(raw), "snapshot_hash": digest(snapshot), "metadata": metadata,
            "actor": _identity(actor), "expires_at": int(time.time()) + 12 * 3600,
            "run_id": secrets.token_hex(16)}
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()
    return encoded + "." + _signature(encoded)


def verify_extraction_receipt(receipt: str | None, raw: str, snapshot: dict | None, actor: CurrentActor):
    if receipt is None:
        return None
    try:
        encoded, signature = receipt.split(".", 1)
        if not hmac.compare_digest(signature, _signature(encoded)):
            raise ValueError()
        body = json.loads(base64.urlsafe_b64decode(encoded))
        if (body["expires_at"] < time.time() or body["actor"] != _identity(actor)
                or body["raw_hash"] != digest(raw) or body["snapshot_hash"] != digest(snapshot)):
            raise ValueError()
        return body
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=422, detail="解析记录已过期或与原文、快照不一致，请重新解析。") from None


def _equivalent(field: str, before: object, after: object) -> bool:
    if field in {"cbm", "weight_kg", "piece_count", "longest_side_cm", "explicit_pallet_count", "detention_minutes"}:
        try:
            return Decimal(str(before)) == Decimal(str(after))
        except InvalidOperation:
            return before == after
    if field in {"postal_code", "city", "province", "address_line", "packaging_type"}:
        return " ".join(str(before or "").upper().split()) == " ".join(str(after or "").upper().split())
    return before == after


def build_extraction_feedback(*, raw: str, snapshot: dict | None, confirmed: dict,
                              receipt: str | None, reasons: dict[str, str], actor: CurrentActor) -> dict:
    verified = verify_extraction_receipt(receipt, raw, snapshot, actor)
    corrections = []
    if snapshot is not None:
        for field in ZoneQuoteRequest.model_fields:
            before, after = snapshot.get(field), confirmed.get(field)
            if not _equivalent(field, before, after):
                corrections.append({"field": field, "before": before, "after": after,
                                    "reason": reasons.get(field, "unclassified")})
    data = {"schema_version": 1, "verified_source": verified is not None,
            "run_id": verified["run_id"] if verified else None,
            "metadata": verified["metadata"] if verified else None,
            "corrections": corrections, "status": "pending_review" if corrections else "no_corrections",
            "approved_fields": []}
    data["version"] = digest(data)
    return data


class FeedbackReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str
    approved_fields: list[str] = Field(default_factory=list, max_length=30)
    note: str = Field(min_length=1, max_length=1000)
    evaluation_group: str = Field(min_length=1, max_length=200)
    split: Literal["train", "validation", "test"] = "test"


def review_extraction_feedback(db: Session, quote_id: str, payload: FeedbackReviewPayload, actor: CurrentActor) -> dict:
    record = db.scalar(select(QuoteAuditLog).where(QuoteAuditLog.quote_id == quote_id).with_for_update())
    if record is None:
        raise HTTPException(status_code=404, detail="Quote audit not found.")
    request = dict(record.request_json or {})
    feedback = dict(request.get("extraction_feedback") or {})
    if not feedback or feedback.get("version") != payload.expected_version:
        raise HTTPException(status_code=409, detail="纠错记录已变化，请刷新。")
    eligible = {item["field"] for item in feedback.get("corrections", []) if item["reason"] == "extraction_error"}
    approved = sorted(set(payload.approved_fields))
    if approved and (not feedback.get("verified_source") or not set(approved).issubset(eligible)):
        raise HTTPException(status_code=422, detail="只能批准来源已验证且标记为解析错误的字段；客户补充和业务调整不能作为纠错标签。")
    feedback.update(approved_fields=approved, status="approved" if approved else "excluded",
                    evaluation_group=payload.evaluation_group, split=payload.split,
                    reviewed_by=actor.name, reviewed_at=datetime.now(timezone.utc).isoformat(), review_note=payload.note)
    feedback["version"] = digest({key: value for key, value in feedback.items() if key != "version"})
    record.request_json = {**request, "extraction_feedback": feedback}
    db.commit()
    return feedback
