from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.db.models import HermesLearningCandidate, LearnedQuoteRule, ManualQuoteTask
from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


class LearnedQuoteRuleRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_from_manual_task(self, task: ManualQuoteTask) -> LearnedQuoteRule | None:
        if task.status != "resolved" or task.resolved_price_usd is None:
            return None

        data = self._learning_data_from_task(task)
        if data is None:
            return None

        record = self._find_existing(data)
        if record is None:
            record = LearnedQuoteRule(**data)
            self.session.add(record)
        else:
            record.source_task_id = data["source_task_id"]
            record.quote_id = data["quote_id"]
            record.total_price_usd = data["total_price_usd"]
            record.base_price_usd = data["base_price_usd"]
            record.origin = data["origin"]
            record.zone = data["zone"]
            record.confidence = max(record.confidence, data["confidence"])
            record.status = "active"
            record.note = data["note"]
        self.session.commit()
        self.session.refresh(record)
        return record

    def upsert_from_candidate(self, candidate: HermesLearningCandidate) -> LearnedQuoteRule:
        data = {
            "source_task_id": candidate.source_task_id,
            "quote_id": candidate.quote_id,
            "scope": candidate.scope,
            "postal_code": candidate.postal_code,
            "postal_prefix": candidate.postal_prefix,
            "city": candidate.city,
            "province": candidate.province,
            "origin": candidate.origin,
            "zone": candidate.zone,
            "billing_pallets": candidate.billing_pallets,
            "total_price_usd": candidate.resolved_total_price_usd,
            "base_price_usd": candidate.resolved_base_price_usd or candidate.resolved_total_price_usd,
            "confidence": candidate.confidence,
            "status": "active",
            "usage_count": 0,
            "note": candidate.review_note or f"Approved from Hermes candidate {candidate.id}.",
        }
        record = self._find_existing(data)
        if record is None:
            record = LearnedQuoteRule(**data)
            self.session.add(record)
        else:
            record.source_task_id = data["source_task_id"]
            record.quote_id = data["quote_id"]
            record.total_price_usd = data["total_price_usd"]
            record.base_price_usd = data["base_price_usd"]
            record.origin = data["origin"]
            record.zone = data["zone"]
            record.confidence = max(record.confidence, data["confidence"])
            record.status = "active"
            record.note = data["note"]
        self.session.commit()
        self.session.refresh(record)
        return record

    def find_best_candidate(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> tuple[LearnedQuoteRule, int] | None:
        billing_pallets = result.billing_pallets
        if billing_pallets is None:
            return None

        postal_code = normalize_postal_code(request.postal_code)
        postal_prefix = result.postal_prefix or extract_fsa(request.postal_code)
        city = normalize_city(result.city or request.city)
        province = normalize_province(result.province or request.province)

        records = list(
            self.session.scalars(
                select(LearnedQuoteRule).where(
                    LearnedQuoteRule.status == "active",
                    LearnedQuoteRule.billing_pallets == billing_pallets,
                )
            )
        )
        scored = [
            (score, record)
            for record in records
            if (score := _match_score(record, postal_code, postal_prefix, city, province)) > 0
        ]
        if not scored:
            return None

        scored.sort(key=lambda item: (item[0], item[1].confidence, item[1].updated_at or item[1].created_at), reverse=True)
        return scored[0][1], scored[0][0]

    def find_match(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> LearnedQuoteRule | None:
        candidate = self.find_best_candidate(request, result)
        if candidate is None:
            return None
        record, _score = candidate
        self.mark_used(record)
        return record

    def mark_used(self, record: LearnedQuoteRule) -> LearnedQuoteRule:
        record.usage_count += 1
        record.last_used_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record

    def count_active(self) -> int:
        return self.session.scalar(select(func.count(LearnedQuoteRule.id)).where(LearnedQuoteRule.status == "active")) or 0

    def list_recent(self, limit: int = 10) -> list[LearnedQuoteRule]:
        safe_limit = max(1, min(limit, 50))
        return list(
            self.session.scalars(
                select(LearnedQuoteRule)
                .order_by(LearnedQuoteRule.updated_at.desc(), LearnedQuoteRule.id.desc())
                .limit(safe_limit)
            )
        )

    def _learning_data_from_task(self, task: ManualQuoteTask) -> dict[str, Any] | None:
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

        return {
            "source_task_id": task.id,
            "quote_id": task.quote_id,
            "scope": scope,
            "postal_code": postal_code,
            "postal_prefix": postal_prefix,
            "city": city,
            "province": province,
            "origin": _string(result_json.get("origin")),
            "zone": _int_value(result_json.get("zone")),
            "billing_pallets": billing_pallets,
            "total_price_usd": total_price,
            "base_price_usd": base_price,
            "confidence": 62 if scope == "postal_prefix" else 68,
            "status": "active",
            "usage_count": 0,
            "note": task.resolved_note or "Learned from resolved manual quote task.",
        }

    def _find_existing(self, data: dict[str, Any]) -> LearnedQuoteRule | None:
        query = select(LearnedQuoteRule).where(
            LearnedQuoteRule.scope == data["scope"],
            LearnedQuoteRule.billing_pallets == data["billing_pallets"],
            LearnedQuoteRule.status == "active",
        )
        for field in ("postal_code", "postal_prefix", "city", "province"):
            column = getattr(LearnedQuoteRule, field)
            value = data[field]
            query = query.where(column == value if value is not None else column.is_(None))
        return self.session.scalars(query).first()


def learned_quote_rule_to_dict(record: LearnedQuoteRule) -> dict[str, object]:
    return {
        "id": record.id,
        "source_task_id": record.source_task_id,
        "quote_id": record.quote_id,
        "scope": record.scope,
        "postal_code": record.postal_code,
        "postal_prefix": record.postal_prefix,
        "city": record.city,
        "province": record.province,
        "origin": record.origin,
        "zone": record.zone,
        "billing_pallets": record.billing_pallets,
        "total_price_usd": f"{record.total_price_usd:.2f}",
        "base_price_usd": f"{record.base_price_usd:.2f}" if record.base_price_usd is not None else None,
        "confidence": record.confidence,
        "status": record.status,
        "usage_count": record.usage_count,
        "note": record.note,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
    }


def _match_score(
    record: LearnedQuoteRule,
    postal_code: str | None,
    postal_prefix: str | None,
    city: str | None,
    province: str | None,
) -> int:
    if record.postal_code and postal_code and record.postal_code == postal_code:
        return 100
    if record.postal_prefix and postal_prefix and record.postal_prefix == postal_prefix:
        if record.city and city and record.city == city and record.province == province:
            return 90
        if record.city is None and record.province and record.province == province:
            return 80
    return 0


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
