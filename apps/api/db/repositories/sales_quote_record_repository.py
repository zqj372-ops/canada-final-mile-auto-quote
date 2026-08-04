from datetime import UTC, datetime
from decimal import Decimal

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
        quote_type: str = "final_mile",
        quote_id: str | None,
        status: str,
        customer_message: str,
        customer_reply: str | None,
        request_json: dict[str, object],
        result_json: dict[str, object],
        snapshot_json: dict[str, object] | None = None,
    ) -> SalesQuoteRecord:
        record = SalesQuoteRecord(
            quote_type=quote_type,
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
            snapshot_json=snapshot_json,
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

    def get_record(self, record_id: int) -> SalesQuoteRecord | None:
        return self.session.get(SalesQuoteRecord, record_id)

    def get_latest_record_by_quote_id(self, quote_id: str) -> SalesQuoteRecord | None:
        return self.session.scalars(
            select(SalesQuoteRecord)
            .where(SalesQuoteRecord.quote_id == quote_id)
            .order_by(SalesQuoteRecord.created_at.desc(), SalesQuoteRecord.id.desc())
            .limit(1)
        ).first()

    def apply_manual_price(
        self,
        *,
        record: SalesQuoteRecord,
        actor: CurrentActor,
        total_price_usd: Decimal,
        override_note: str,
        customer_reply: str | None,
    ) -> SalesQuoteRecord:
        result_json = dict(record.result_json or {})
        quote_result = _object_or_empty(result_json.get("quote_result")).copy()
        previous_total = quote_result.get("total_price_usd")
        price_text = str(total_price_usd.quantize(Decimal("0.01")))

        quote_result.update(
            {
                "source_type": "manual_override",
                "manual_review_required": False,
                "total_price_usd": price_text,
                "converted_total": price_text,
                "confidence": max(int(quote_result.get("confidence") or 0), 100),
                "matched_rule": "manual_override",
                "internal_note": f"Manual price override by {actor.name}: {override_note}",
            }
        )
        if getattr(record, "quote_type", None) == "fcl":
            settlement_currency = quote_result.get("settlement_currency") or "USD"
            quote_result["settlement_currency"] = settlement_currency
            quote_result["totals_by_currency"] = {settlement_currency: price_text}
            quote_result["manual_reasons"] = []
            quote_result["manual_review_required"] = False
            result_json["missing_fields"] = []
        risk_tags = _string_list(quote_result.get("risk_tags"))
        if "manual_price_override" not in risk_tags:
            risk_tags.append("manual_price_override")
        quote_result["risk_tags"] = risk_tags

        result_json["quote_result"] = quote_result
        result_json["manual_review_required"] = False
        result_json["customer_reply"] = customer_reply or _build_manual_customer_reply(record, price_text)
        result_json["manual_override"] = {
            "total_price_usd": price_text,
            "previous_total_price_usd": previous_total,
            "override_note": override_note,
            "actor_name": actor.name,
            "actor_role": actor.role,
            "updated_at": datetime.now(UTC).isoformat(),
            "reminder": "人工确认价只更新本次报价记录，不修改 Zone 价格矩阵。",
        }

        record.status = "quoted"
        record.customer_reply = str(result_json["customer_reply"])
        record.result_json = result_json
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record


def sales_quote_record_to_dict(record: SalesQuoteRecord) -> dict[str, object]:
    result_json = _public_json(record.result_json or {})
    quote_result = _object_or_empty(result_json.get("quote_result"))
    extraction = _object_or_empty(result_json.get("extraction"))
    missing_fields = _string_list(result_json.get("missing_fields"))
    risk_tags = _string_list(quote_result.get("risk_tags"))
    quote_type = getattr(record, "quote_type", None) or "final_mile"
    if quote_type == "fcl":
        return _fcl_record_to_dict(record, result_json)
    return {
        "id": record.id,
        "quote_type": quote_type,
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
        "request_json": _public_json(record.request_json or {}),
        "result_json": result_json,
    }


def _fcl_record_to_dict(record: SalesQuoteRecord, result_json: dict[str, object]) -> dict[str, object]:
    quote_result = _object_or_empty(result_json.get("quote_result"))
    extraction = _object_or_empty(result_json.get("extraction"))
    cargo = _object_or_empty(quote_result.get("cargo_calculation"))
    totals = _object_or_empty(quote_result.get("totals_by_currency"))
    settlement_currency = quote_result.get("settlement_currency")
    converted_total = quote_result.get("converted_total")
    manual_reasons = _string_list(quote_result.get("manual_reasons"))
    return {
        "id": record.id,
        "quote_type": "fcl",
        "quote_id": record.quote_id,
        "actor_user_id": record.actor_user_id,
        "actor_api_key_id": record.actor_api_key_id,
        "actor_name": record.actor_name,
        "actor_role": record.actor_role,
        "status": record.status,
        "customer_message": record.customer_message,
        "customer_reply": record.customer_reply,
        "destination": f"POL {quote_result.get('normalized_input', {}).get('pol') or extraction.get('pol') or '待确认'} → POD {quote_result.get('normalized_input', {}).get('pod') or extraction.get('pod') or '待确认'}",
        "cargo_summary": _fcl_cargo_summary(cargo),
        "total_price_usd": converted_total if settlement_currency else None,
        "currency_code": settlement_currency or "MULTI",
        "totals_by_currency": totals,
        "zone": None,
        "billing_pallets": None,
        "confidence": quote_result.get("normalized_input", {}).get("confidence") or extraction.get("confidence") or 0,
        "source_type": quote_result.get("source_type") or "manual_required",
        "postal_code": None,
        "city": None,
        "province": None,
        "risk_tags": ["fcl", *manual_reasons] if manual_reasons else ["fcl"],
        "risk_tag_labels": [],
        "missing_fields": _string_list(result_json.get("missing_fields")),
        "manual_reason": "；".join(manual_reasons) if record.status == "manual_required" else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "request_json": _public_json(record.request_json or {}),
        "result_json": result_json,
    }


def _object_or_empty(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


_INTERNAL_KEYS = {
    "cost_price",
    "cost_unit_price",
    "vendor",
    "supplier",
    "internal_note",
    "internal_notes",
    "api_key",
    "password",
    "secret",
    "token",
}


def _public_json(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _public_json(item)
            for key, item in value.items()
            if str(key).lower() not in _INTERNAL_KEYS
        }
    if isinstance(value, list):
        return [_public_json(item) for item in value]
    return value


def _fcl_cargo_summary(cargo: dict[str, object]) -> str:
    pieces = cargo.get("piece_count")
    weight = cargo.get("total_weight_kg")
    volume = cargo.get("total_volume_cbm")
    return " / ".join(
        [
            f"{pieces} 件" if pieces is not None else "件数待确认",
            f"{weight} KG" if weight is not None else "重量待确认",
            f"{volume} CBM" if volume is not None else "体积待确认",
        ]
    )


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


def _build_manual_customer_reply(record: SalesQuoteRecord, price_text: str) -> str:
    return "\n".join(
        [
            "加拿大尾端派送报价如下：",
            f"目的地：{_destination(_object_or_empty(record.result_json.get('quote_result')), _object_or_empty(record.result_json.get('extraction')))}",
            f"报价合计：USD {price_text}",
            "注：不带尾板，自卸货",
            "- 送货到门口路边，不含其他操作",
            "- 无卸货平台需尾板 +50USD/票",
            "- 需手叉车配合 +50USD/票",
            "- 免费等待30分钟，超时35USD/半小时",
            "- 价格以供应商实测地址及卡车准入情况为准",
            "- 下单引用单号，未引用加收50人民币/票服务费",
        ]
    )
