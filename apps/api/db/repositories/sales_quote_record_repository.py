from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import SalesQuoteRecord
from apps.api.services.quote_issue_labels import risk_tag_labels


class SalesQuoteRecordRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_record(
        self,
        *,
        actor: CurrentActor,
        quote_id: str | None,
        status: str,
        customer_message: str,
        customer_reply: str | None,
        request_json: dict[str, object],
        result_json: dict[str, object],
    ) -> SalesQuoteRecord:
        record = SalesQuoteRecord(
            quote_id=quote_id,
            actor_user_id=actor.user_id,
            actor_api_key_id=actor.api_key_id,
            actor_name=actor.name,
            actor_role=actor.role,
            status=status,
            customer_message=customer_message,
            customer_reply=customer_reply,
            request_json=request_json,
            result_json=result_json,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_records(
        self,
        *,
        actor: CurrentActor,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SalesQuoteRecord]:
        safe_limit = max(1, min(limit, 200))
        query = select(SalesQuoteRecord)
        if actor.role == "sales":
            if actor.user_id is not None:
                query = query.where(SalesQuoteRecord.actor_user_id == actor.user_id)
            elif actor.api_key_id is not None:
                query = query.where(SalesQuoteRecord.actor_api_key_id == actor.api_key_id)
            else:
                query = query.where(SalesQuoteRecord.actor_role == "sales")
        if status:
            query = query.where(SalesQuoteRecord.status == status)
        return list(
            self.session.scalars(
                query.order_by(SalesQuoteRecord.created_at.desc(), SalesQuoteRecord.id.desc()).limit(safe_limit)
            )
        )


def sales_quote_record_to_dict(record: SalesQuoteRecord) -> dict[str, object]:
    result_json = record.result_json or {}
    quote_result = _object_or_empty(result_json.get("quote_result"))
    extraction = _object_or_empty(result_json.get("extraction"))
    missing_fields = _string_list(result_json.get("missing_fields"))
    risk_tags = _string_list(quote_result.get("risk_tags"))
    return {
        "id": record.id,
        "quote_id": record.quote_id,
        "actor_user_id": record.actor_user_id,
        "actor_api_key_id": record.actor_api_key_id,
        "actor_name": record.actor_name,
        "actor_role": record.actor_role,
        "status": record.status,
        "customer_message": record.customer_message,
        "customer_reply": record.customer_reply,
        "destination": _destination(quote_result, extraction),
        "cargo_summary": _cargo_summary(extraction),
        "total_price_usd": quote_result.get("total_price_usd"),
        "currency_code": "USD",
        "zone": quote_result.get("zone"),
        "billing_pallets": quote_result.get("billing_pallets"),
        "confidence": quote_result.get("confidence") or extraction.get("confidence") or 0,
        "source_type": quote_result.get("source_type") or "manual_required",
        "postal_code": quote_result.get("postal_code") or extraction.get("postal_code"),
        "city": quote_result.get("city") or extraction.get("city"),
        "province": quote_result.get("province") or extraction.get("province"),
        "risk_tags": risk_tags,
        "risk_tag_labels": risk_tag_labels(risk_tags),
        "missing_fields": missing_fields,
        "manual_reason": _manual_reason(record.status, quote_result, missing_fields),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "request_json": record.request_json,
        "result_json": result_json,
    }


def _object_or_empty(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _destination(quote_result: dict[str, object], extraction: dict[str, object]) -> str:
    parts = [
        extraction.get("address_line"),
        quote_result.get("preferred_city") or quote_result.get("city") or extraction.get("city"),
        quote_result.get("province") or extraction.get("province"),
        quote_result.get("postal_code") or extraction.get("postal_code"),
    ]
    return ", ".join(str(part) for part in parts if part) or "目的地待确认"


def _cargo_summary(extraction: dict[str, object]) -> str:
    pieces = extraction.get("piece_count")
    cbm = extraction.get("cbm")
    weight = extraction.get("weight_kg")
    return " / ".join(
        [
            f"{pieces} 件" if pieces else "件数待确认",
            f"{cbm} CBM" if cbm else "CBM 待确认",
            f"{weight} KG" if weight else "重量待确认",
        ]
    )


def _manual_reason(status: str, quote_result: dict[str, object], missing_fields: list[str]) -> str | None:
    if status != "manual_required":
        return None
    if missing_fields:
        return f"缺少 {', '.join(missing_fields)}"
    matched_rule = quote_result.get("matched_rule")
    return str(matched_rule) if matched_rule else "需要人工确认"
