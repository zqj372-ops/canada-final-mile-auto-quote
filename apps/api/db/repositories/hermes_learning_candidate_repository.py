from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from apps.api.db.models import HermesLearningCandidate, LearnedQuoteRule, ManualQuoteTask
from apps.api.db.repositories.learned_quote_rule_repository import (
    LearnedQuoteRuleRepository,
)
from packages.quote_engine.learning_policy import quote_conditions_from_mapping, valid_price_terms
from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province


class LearningReviewConflict(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class HermesLearningCandidateRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_from_manual_task(self, task: ManualQuoteTask, *, commit: bool = True) -> HermesLearningCandidate | None:
        if task.scope_kind not in {None, "legacy"} or task.learning_eligible is False:
            return None
        data = self._candidate_data_from_task(task)
        if data is None:
            return None
        statement = select(HermesLearningCandidate).where(
            HermesLearningCandidate.duplicate_key == data["duplicate_key"]
        ).with_for_update().execution_options(populate_existing=True)
        record = self.session.scalar(statement)
        if record is None:
            if task.status != "resolved":
                return None
            try:
                with self.session.begin_nested():
                    record = HermesLearningCandidate(**data)
                    self.session.add(record)
                    self.session.flush()
            except IntegrityError:
                record = self.session.scalar(statement)
                if record is None:
                    raise
        evidence = dict(record.evidence_json or {})
        cases = list(evidence.get("cases", []))
        entry = {"task_id": task.id, "quote_id": task.quote_id, "status": task.status,
                 "resolved_price_usd": str(data["resolved_total_price_usd"]),
                 "resolved_note": task.resolved_note,
                 "request_json": task.request_json, "result_json": task.result_json}
        previous = next((item for item in cases if item["task_id"] == task.id), None)
        if previous != entry:
            if previous is not None:
                evidence["revisions"] = [*evidence.get("revisions", []), previous]
            cases = [item for item in cases if item["task_id"] != task.id] + [entry]
        active = [item for item in cases if item["status"] == "resolved"]
        prices = {item["resolved_price_usd"] for item in active}
        proposal = dict(record.proposal_json)
        proposal["price_conflict"] = len(prices) > 1
        proposal["evidence_version"] = _digest(cases)
        record.support_count = len(active)
        price_changed = len(prices) == 1 and Decimal(next(iter(prices))) != record.resolved_total_price_usd
        source_withdrawn = record.source_task_id == task.id and task.status != "resolved"
        if not active or len(prices) > 1 or price_changed or source_withdrawn:
            if record.promoted_rule_id:
                rule = self.session.get(LearnedQuoteRule, record.promoted_rule_id)
                if rule is not None:
                    rule.status = "disabled"
            record.status = "pending_review"
            proposal.pop("price_terms", None)
        if previous is None and record.status == "rejected" and task.status == "resolved":
            record.status = "pending_review"
        if active and not any(item["task_id"] == record.source_task_id for item in active):
            record.source_task_id = active[0]["task_id"]
            record.quote_id = active[0]["quote_id"]
        if len(prices) == 1:
            record.resolved_total_price_usd = Decimal(next(iter(prices)))
            proposal["total_price_usd"] = str(record.resolved_total_price_usd)
        record.proposal_json = proposal
        primary = next((item for item in cases if item["task_id"] == record.source_task_id), None)
        if primary is not None:
            evidence.update({key: primary[key] for key in (
                "request_json", "result_json", "resolved_note", "resolved_price_usd",
            )})
        record.evidence_json = {**evidence, "cases": cases}
        record.risk_tags = sorted(set(data["risk_tags"] + (["learning_price_conflict"] if len(prices) > 1 else [])))
        if commit:
            self.session.commit()
            self.session.refresh(record)
        else:
            self.session.flush()
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

    def _locked(self, candidate_id: int) -> HermesLearningCandidate | None:
        return self.session.scalar(select(HermesLearningCandidate).where(
            HermesLearningCandidate.id == candidate_id
        ).with_for_update().execution_options(populate_existing=True))

    def approve(self, candidate_id: int, *, reviewed_by: str | None = None,
                review_note: str | None = None, price_terms: dict[str, object],
                expected_evidence_version: str | None = None) -> tuple[HermesLearningCandidate, LearnedQuoteRule] | None:
        try:
            record = self._locked(candidate_id)
            if record is None:
                return None
            proposal = dict(record.proposal_json)
            if not expected_evidence_version or expected_evidence_version != proposal.get("evidence_version"):
                raise LearningReviewConflict("候选证据已变化或属于旧版记录，请刷新并重新核对。")
            if record.status == "approved":
                rule = self.session.get(LearnedQuoteRule, record.promoted_rule_id)
                if rule is None:
                    raise LearningReviewConflict("已批准候选缺少发布规则，请核查。")
                return record, rule
            if record.status != "pending_review":
                raise LearningReviewConflict("只有待审核候选可以批准。")
            if record.scope != "exact_address" or not proposal.get("conditions", {}).get("address_line"):
                raise LearningReviewConflict("缺少完整地址或属于旧版宽范围候选，不能自动复用。")
            if record.support_count < 1 or proposal.get("price_conflict"):
                raise LearningReviewConflict("人工记录金额冲突或没有有效确认，请先核实原人工单。")
            if not valid_price_terms(price_terms):
                raise LearningReviewConflict("批准需填写供应商、价格来源以及当前有效的起止时间。")
            record.review_note = review_note
            record.reviewed_by = reviewed_by
            record.reviewed_at = datetime.now(timezone.utc)
            record.proposal_json = {**proposal, "price_terms": price_terms}
            rule = LearnedQuoteRuleRepository(self.session).upsert_from_candidate(record)
            record.status = "approved"
            record.promoted_rule_id = rule.id
            self.session.commit()
            self.session.refresh(record)
            return record, rule
        except Exception:
            self.session.rollback()
            raise

    def reject(self, candidate_id: int, *, reviewed_by: str | None = None,
               review_note: str | None = None) -> HermesLearningCandidate | None:
        record = self._locked(candidate_id)
        if record is None:
            return None
        if record.status == "approved":
            raise LearningReviewConflict("已发布候选不能改为拒绝；请禁用对应学习规则。")
        if record.status == "rejected":
            return record
        record.status = "rejected"
        record.reviewed_by = reviewed_by
        record.review_note = review_note
        record.reviewed_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_learned_rule_status(self, rule_id: int, *, status: str,
                                  note: str | None = None) -> LearnedQuoteRule | None:
        if status == "active":
            raise LearningReviewConflict("重新启用价格需重新审核来源、适用条件及有效期。")
        # Approval and manual-task updates lock candidate before rule. Keep the
        # same order here to avoid deadlocks with concurrent review/revocation.
        candidates = list(self.session.scalars(select(HermesLearningCandidate).where(
            HermesLearningCandidate.promoted_rule_id == rule_id
        ).order_by(HermesLearningCandidate.id).with_for_update().execution_options(populate_existing=True)))
        rule = self.session.scalar(select(LearnedQuoteRule).where(
            LearnedQuoteRule.id == rule_id).with_for_update().execution_options(populate_existing=True))
        if rule is None:
            return None
        rule.status = status
        if note is not None:
            rule.note = note
        for candidate in candidates:
            if candidate.status == "approved":
                candidate.status = "pending_review"
                candidate.proposal_json = {key: value for key, value in candidate.proposal_json.items() if key != "price_terms"}
        self.session.commit()
        self.session.refresh(rule)
        return rule

    def _candidate_data_from_task(self, task: ManualQuoteTask) -> dict[str, Any] | None:
        if task.resolved_price_usd is None:
            return None
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

        try:
            conditions = quote_conditions_from_mapping(request_json)
        except (ValidationError, ValueError):
            return None
        scope = "exact_address" if conditions["address_line"] and postal_code else "manual_only"
        total_price = Decimal(task.resolved_price_usd).quantize(Decimal("0.01"))
        base_price = None
        origin = _string(result_json.get("origin"))
        zone = _int_value(result_json.get("zone"))
        risk_tags = list(result_json.get("risk_tags") or task.risk_tags or [])
        duplicate_key = "v2:" + _digest([scope, postal_code, city, province, origin, zone, billing_pallets, conditions])

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
            "confidence": 0,
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
                "base_price_usd": None,
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
