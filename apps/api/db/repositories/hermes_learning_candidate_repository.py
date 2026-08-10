from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import HermesLearningCandidate, LearnedQuoteRule, ManualQuoteTask
from apps.api.db.repositories.learned_quote_rule_repository import (
    LearnedQuoteRuleRepository,
    quote_conditions_from_mapping,
)
from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province


class HermesLearningCandidateRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_from_manual_task(self, task: ManualQuoteTask) -> HermesLearningCandidate | None:
        if task.status != "resolved" or task.resolved_price_usd is None:
            return None

        data = self._candidate_data_from_task(task)
        if data is None:
            return None

        record = self._find_existing_by_duplicate_key(data["duplicate_key"])
        if record is None:
            record = HermesLearningCandidate(**data)
            self.session.add(record)
        else:
            record.support_count += 1
            record.source_task_id = data["source_task_id"]
            record.quote_id = data["quote_id"]
            record.resolved_total_price_usd = data["resolved_total_price_usd"]
            record.resolved_base_price_usd = data["resolved_base_price_usd"]
            record.confidence = max(record.confidence, data["confidence"])
            record.proposal_json = data["proposal_json"]
            record.evidence_json = data["evidence_json"]
            record.risk_tags = data["risk_tags"]
            if record.status == "rejected":
                record.status = "pending_review"
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_candidates(
        self,
        *,
        status: str | None = None,
        postal_prefix: str | None = None,
        city: str | None = None,
        province: str | None = None,
        billing_pallets: int | None = None,
        limit: int = 50,
    ) -> list[HermesLearningCandidate]:
        query = select(HermesLearningCandidate)
        if status and status != "all":
            query = query.where(HermesLearningCandidate.status == status)
        if postal_prefix:
            query = query.where(HermesLearningCandidate.postal_prefix == postal_prefix.strip().upper())
        if city:
            query = query.where(HermesLearningCandidate.city == normalize_city(city))
        if province:
            query = query.where(HermesLearningCandidate.province == normalize_province(province))
        if billing_pallets is not None:
            query = query.where(HermesLearningCandidate.billing_pallets == billing_pallets)
        safe_limit = max(1, min(limit, 200))
        return list(
            self.session.scalars(
                query.order_by(HermesLearningCandidate.updated_at.desc(), HermesLearningCandidate.id.desc()).limit(safe_limit)
            )
        )

    def get(self, candidate_id: int) -> HermesLearningCandidate | None:
        return self.session.get(HermesLearningCandidate, candidate_id)

    def approve(
        self,
        candidate_id: int,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> tuple[HermesLearningCandidate, LearnedQuoteRule] | None:
        record = self.get(candidate_id)
        if record is None:
            return None

        if review_note is not None:
            record.review_note = review_note
        record.reviewed_by = reviewed_by
        record.reviewed_at = datetime.now(timezone.utc)
        rule = LearnedQuoteRuleRepository(self.session).upsert_from_candidate(record)
        record.status = "approved"
        record.promoted_rule_id = rule.id
        self.session.commit()
        self.session.refresh(record)
        return record, rule

    def reject(
        self,
        candidate_id: int,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> HermesLearningCandidate | None:
        record = self.get(candidate_id)
        if record is None:
            return None
        record.status = "rejected"
        record.reviewed_by = reviewed_by
        record.review_note = review_note
        record.reviewed_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_learned_rule_status(
        self,
        rule_id: int,
        *,
        status: str,
        note: str | None = None,
    ) -> LearnedQuoteRule | None:
        rule = self.session.get(LearnedQuoteRule, rule_id)
        if rule is None:
            return None
        rule.status = status
        if note is not None:
            rule.note = note
        self.session.commit()
        self.session.refresh(rule)
        return rule

    def _candidate_data_from_task(self, task: ManualQuoteTask) -> dict[str, Any] | None:
        request_json = task.request_json or {}
        result_json = task.result_json or {}
        postal_code = normalize_postal_code(_string(request_json.get("postal_code")) or _string(result_json.get("postal_code")))
        postal_prefix = (
            _string(result_json.get("postal_prefix"))
            or extract_fsa(postal_code)
            or extract_fsa(_string(request_json.get("postal_code")))
        )
        city = normalize_city(_string(result_json.get("city")) or _string(request_json.get("city")))
        province = normalize_province(_string(result_json.get("province")) or _string(request_json.get("province")))
        if province is None and postal_code:
            province = _province_from_postal_initial(postal_code)

        billing_pallets = _int_value(result_json.get("billing_pallets"))
        if billing_pallets is None or (postal_code is None and postal_prefix is None):
            return None

        scope = "postal_prefix_city" if postal_prefix and city and province else "postal_prefix"
        total_price = Decimal(task.resolved_price_usd).quantize(Decimal("0.01"))
        base_price = _decimal_value(result_json.get("base_price_usd")) or total_price
        origin = _string(result_json.get("origin"))
        zone = _int_value(result_json.get("zone"))
        risk_tags = list(result_json.get("risk_tags") or task.risk_tags or [])
        conditions = quote_conditions_from_mapping(request_json)
        duplicate_key = "|".join(
            str(value or "")
            for value in (
                scope,
                postal_code,
                postal_prefix,
                city,
                province,
                origin,
                zone,
                billing_pallets,
                conditions["address_type"],
                int(bool(conditions["requires_liftgate"])),
                int(bool(conditions["requires_pallet_jack"])),
                int(bool(conditions["requires_appointment"])),
                conditions["detention_minutes"],
            )
        )

        return {
            "source_task_id": task.id,
            "quote_id": task.quote_id,
            "candidate_type": _candidate_type(risk_tags, origin, zone),
            "scope": scope,
            "postal_code": postal_code,
            "postal_prefix": postal_prefix,
            "city": city,
            "province": province,
            "origin": origin,
            "zone": zone,
            "billing_pallets": billing_pallets,
            "resolved_total_price_usd": total_price,
            "resolved_base_price_usd": base_price,
            "confidence": 62 if scope == "postal_prefix" else 68,
            "support_count": 1,
            "status": "pending_review",
            "duplicate_key": duplicate_key,
            "proposal_json": {
                "action": "approve_learned_exception_price",
                "scope": scope,
                "postal_code": postal_code,
                "postal_prefix": postal_prefix,
                "city": city,
                "province": province,
                "origin": origin,
                "zone": zone,
                "billing_pallets": billing_pallets,
                "conditions": conditions,
                "total_price_usd": f"{total_price:.2f}",
                "base_price_usd": f"{base_price:.2f}",
            },
            "evidence_json": {
                "request_json": request_json,
                "result_json": result_json,
                "resolved_note": task.resolved_note,
                "resolved_price_usd": f"{total_price:.2f}",
            },
            "risk_tags": risk_tags,
            "review_note": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "promoted_rule_id": None,
        }

    def _find_existing_by_duplicate_key(self, duplicate_key: str) -> HermesLearningCandidate | None:
        return self.session.scalars(
            select(HermesLearningCandidate).where(
                HermesLearningCandidate.duplicate_key == duplicate_key,
                HermesLearningCandidate.status == "pending_review",
            )
        ).first()


def hermes_candidate_to_dict(record: HermesLearningCandidate) -> dict[str, object]:
    return {
        "id": record.id,
        "source_task_id": record.source_task_id,
        "quote_id": record.quote_id,
        "candidate_type": record.candidate_type,
        "scope": record.scope,
        "postal_code": record.postal_code,
        "postal_prefix": record.postal_prefix,
        "city": record.city,
        "province": record.province,
        "origin": record.origin,
        "zone": record.zone,
        "billing_pallets": record.billing_pallets,
        "resolved_total_price_usd": _decimal_to_string(record.resolved_total_price_usd),
        "resolved_base_price_usd": _decimal_to_string(record.resolved_base_price_usd),
        "confidence": record.confidence,
        "support_count": record.support_count,
        "status": record.status,
        "duplicate_key": record.duplicate_key,
        "proposal_json": record.proposal_json,
        "evidence_json": record.evidence_json,
        "risk_tags": record.risk_tags,
        "review_note": record.review_note,
        "reviewed_by": record.reviewed_by,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "promoted_rule_id": record.promoted_rule_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _candidate_type(risk_tags: list[str], origin: str | None, zone: int | None) -> str:
    if "zone_price_not_found" in risk_tags:
        return "zone_price_matrix_gap"
    if "zone_not_found" in risk_tags or "postal_family_split_record_conflict" in risk_tags:
        return "postal_zone_override" if origin and zone is not None else "learned_exception_price"
    return "learned_exception_price"


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None
    return number if number >= 1 else None


def _decimal_value(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _province_from_postal_initial(postal_code: str) -> str | None:
    return {
        "A": "NL",
        "B": "NS",
        "C": "PE",
        "E": "NB",
        "G": "QC",
        "H": "QC",
        "J": "QC",
        "K": "ON",
        "L": "ON",
        "M": "ON",
        "N": "ON",
        "P": "ON",
        "R": "MB",
        "S": "SK",
        "T": "AB",
        "V": "BC",
        "X": "NT",
        "Y": "YT",
    }.get(postal_code[:1].upper())
