from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.db.models import HermesLearningCandidate, LearnedQuoteRule
from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.learning_policy import quote_conditions_match, valid_price_terms
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


class LearnedQuoteRuleRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_from_candidate(self, candidate: HermesLearningCandidate) -> LearnedQuoteRule:
        """Participates in the caller's approval transaction; never commits."""
        data = {
            "source_task_id": candidate.source_task_id, "quote_id": candidate.quote_id,
            "scope": candidate.scope, "postal_code": candidate.postal_code,
            "postal_prefix": candidate.postal_prefix, "city": candidate.city,
            "province": candidate.province, "origin": candidate.origin, "zone": candidate.zone,
            "billing_pallets": candidate.billing_pallets,
            "conditions_json": {**candidate.proposal_json["conditions"],
                                "price_terms": candidate.proposal_json["price_terms"]},
            "total_price_usd": candidate.resolved_total_price_usd,
            "base_price_usd": None, "confidence": 0, "status": "active",
            "usage_count": 0, "note": candidate.review_note,
        }
        record = self.session.get(LearnedQuoteRule, candidate.promoted_rule_id) if candidate.promoted_rule_id else None
        if record is None:
            record = LearnedQuoteRule(**data)
            self.session.add(record)
        else:
            for key, value in data.items():
                if key != "usage_count":
                    setattr(record, key, value)
        self.session.flush()
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
                    LearnedQuoteRule.scope == "exact_address",
                    LearnedQuoteRule.postal_code == postal_code,
                )
            )
        )
        scored = [
            (score, record)
            for record in records
            if quote_conditions_match(record.conditions_json, request)
            and (score := _match_score(record, postal_code, postal_prefix, city, province)) > 0
        ]
        if not scored:
            return None

        # Multiple live prices for identical conditions are not resolved by recency.
        if len({record.total_price_usd for _, record in scored}) > 1:
            return None
        scored.sort(key=lambda item: (item[0], item[1].updated_at or item[1].created_at), reverse=True)
        return scored[0][1], scored[0][0]

    def find_match(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> LearnedQuoteRule | None:
        candidate = self.find_best_candidate(request, result)
        if candidate is None:
            return None
        record, _score = candidate
        self.mark_used(record)
        return record

    def mark_used(self, record: LearnedQuoteRule, *, commit: bool = True) -> LearnedQuoteRule:
        record.usage_count += 1
        record.last_used_at = datetime.now(timezone.utc)
        if commit:
            self.session.commit()
            self.session.refresh(record)
        else:
            self.session.flush()
        return record

    def count_active(self) -> int:
        return sum(1 for rule in self.session.scalars(select(LearnedQuoteRule).where(
            LearnedQuoteRule.status == "active", LearnedQuoteRule.scope == "exact_address"
        )) if valid_price_terms((rule.conditions_json or {}).get("price_terms")))

    def list_recent(self, limit: int = 10) -> list[LearnedQuoteRule]:
        safe_limit = max(1, min(limit, 50))
        return list(
            self.session.scalars(
                select(LearnedQuoteRule)
                .order_by(LearnedQuoteRule.updated_at.desc(), LearnedQuoteRule.id.desc())
                .limit(safe_limit)
            )
        )


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
        "conditions_json": record.conditions_json,
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


def _match_score(record: LearnedQuoteRule, postal_code: str | None,
                 postal_prefix: str | None, city: str | None, province: str | None) -> int:
    return 100 if (record.scope == "exact_address" and record.postal_code == postal_code
                   and record.city == city and record.province == province) else 0
