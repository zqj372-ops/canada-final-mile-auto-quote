from decimal import Decimal
from typing import Protocol

from packages.address_normalizer import extract_fsa
from packages.quote_engine.pallet_calculator import calculate_billing_pallets
from packages.quote_engine.pricing import money
from packages.quote_engine.zone_lookup import (
    get_province_from_postal_code,
    lookup_zone_by_postal_prefix_city_province,
    origin_label,
)
from packages.quote_engine.zone_models import (
    PostalCodeCityRecord,
    ZoneLookupRuleRecord,
    ZonePriceRecord,
    ZoneQuoteRequest,
    ZoneQuoteResult,
    ZoneQuoteSourceType,
)
from packages.quote_engine.zone_pricing import calculate_zone_price


class ZoneDataProvider(Protocol):
    def get_preferred_city(self, postal_code: str) -> PostalCodeCityRecord | None:
        ...

    def list_zone_rules(self, postal_prefix: str) -> list[ZoneLookupRuleRecord]:
        ...

    def get_zone_price(self, origin: str, zone: int, billing_pallets: int) -> ZonePriceRecord | None:
        ...


class ZoneQuoteEngine:
    def __init__(self, provider: ZoneDataProvider):
        self.provider = provider

    def quote(self, request: ZoneQuoteRequest) -> ZoneQuoteResult:
        postal_prefix = extract_fsa(request.postal_code)
        if not postal_prefix:
            return self._manual(request, "Postal prefix could not be extracted.", ("postal_prefix_missing",))

        preferred_record = self.provider.get_preferred_city(request.postal_code)
        preferred_city = preferred_record.preferred_city if preferred_record else None
        province = request.province or (preferred_record.province if preferred_record else None)
        province = province or get_province_from_postal_code(request.postal_code)
        city = request.city or preferred_city

        zone_rules = self.provider.list_zone_rules(postal_prefix)
        zone_decision = lookup_zone_by_postal_prefix_city_province(postal_prefix, city, province, zone_rules)
        if zone_decision.manual_required or zone_decision.origin is None or zone_decision.zone is None:
            return self._manual(
                request,
                zone_decision.matched_rule,
                zone_decision.risk_tags,
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
            )

        pallet_result = calculate_billing_pallets(
            cbm=request.cbm,
            weight_kg=request.weight_kg,
            piece_count=request.piece_count,
            packaging_type=request.packaging_type,
            longest_side_cm=request.longest_side_cm,
            explicit_pallet_count=request.explicit_pallet_count,
            is_stackable=request.is_stackable,
        )
        if pallet_result.manual_review_required or pallet_result.billing_pallets is None:
            return self._manual(
                request,
                pallet_result.internal_note or "Billing pallets require manual review.",
                pallet_result.risk_tags,
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                origin=zone_decision.origin,
                zone=zone_decision.zone,
            )

        price_record = self.provider.get_zone_price(
            zone_decision.origin,
            zone_decision.zone,
            pallet_result.billing_pallets,
        )
        if price_record is None:
            return self._manual(
                request,
                (
                    f"No zone matrix price for {zone_decision.origin} Zone {zone_decision.zone} "
                    f"+ {pallet_result.billing_pallets} pallets."
                ),
                ("zone_price_not_found",),
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                origin=zone_decision.origin,
                zone=zone_decision.zone,
                billing_pallets=pallet_result.billing_pallets,
            )

        pricing = calculate_zone_price(
            base_price_usd=money(price_record.base_price_usd),
            address_type=request.address_type,
            requires_liftgate=request.requires_liftgate,
            requires_pallet_jack=request.requires_pallet_jack,
            requires_appointment=request.requires_appointment,
            detention_minutes=request.detention_minutes,
        )
        risk_tags = list(zone_decision.risk_tags)
        risk_tags.extend(_request_risk_tags(request))
        matched_rule = (
            f"zone_matrix + {zone_decision.origin} + {province} + {city} + {postal_prefix} "
            f"+ Zone {zone_decision.zone} + {pallet_result.billing_pallets} pallets"
        )
        result = ZoneQuoteResult(
            source_type=ZoneQuoteSourceType.ZONE_MATRIX,
            confidence=zone_decision.confidence,
            postal_code=request.postal_code,
            preferred_city=preferred_city,
            postal_prefix=postal_prefix,
            city=city,
            province=province,
            origin=zone_decision.origin,
            zone=zone_decision.zone,
            billing_pallets=pallet_result.billing_pallets,
            base_price_usd=money(price_record.base_price_usd),
            fuel_usd=pricing.fuel_usd,
            accessorials=pricing.accessorials,
            total_price_usd=pricing.total_price_usd,
            risk_tags=sorted(set(risk_tags)),
            manual_review_required=False,
            matched_rule=matched_rule,
            internal_note="Base price came from zone_price_matrix. AI may explain but must not change price.",
        )
        result.sales_note = build_zone_sales_note(request, result)
        return result

    def _manual(
        self,
        request: ZoneQuoteRequest,
        matched_rule: str,
        risk_tags: tuple[str, ...] | list[str],
        *,
        preferred_city: str | None = None,
        postal_prefix: str | None = None,
        city: str | None = None,
        province: str | None = None,
        origin: str | None = None,
        zone: int | None = None,
        billing_pallets: int | None = None,
    ) -> ZoneQuoteResult:
        return ZoneQuoteResult(
            source_type=ZoneQuoteSourceType.MANUAL_REQUIRED,
            confidence=0,
            postal_code=request.postal_code,
            preferred_city=preferred_city,
            postal_prefix=postal_prefix,
            city=city or request.city,
            province=province or request.province,
            origin=origin,
            zone=zone,
            billing_pallets=billing_pallets,
            risk_tags=sorted(set(risk_tags)),
            manual_review_required=True,
            matched_rule=matched_rule,
            sales_note="Manual review required before sharing a price.",
            internal_note="Zone quote could not be completed from deterministic lookup tables.",
        )


def build_zone_sales_note(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> str:
    amount = _format_money(result.total_price_usd)
    address_type = {
        "commercial": "商业地址",
        "residential": "私人住宅地址",
        "private": "私人住宅地址",
        "rural_residential": "农村住宅地址",
    }[request.address_type.value]
    service_line = (
        "商业地址（不含住宅附加费）"
        if request.address_type.value == "commercial"
        else "私人地址（含住宅附加费 +50USD/票）"
    )
    cargo_parts = [
        request.packaging_type,
        f"{request.cbm} CBM",
        f"{request.weight_kg} KG",
        f"{request.piece_count}件",
    ]
    if request.longest_side_cm is not None:
        cargo_parts.append(f"最长边{request.longest_side_cm}CM")

    return "\n".join(
        [
            f"地址：{request.address_line or ''}".rstrip(),
            f"地址类型：{address_type}",
            f"货物：{' / '.join(cargo_parts)}",
            f"报价：${amount} USD {origin_label(result.origin)}派送（Zone {result.zone}）",
            "",
            "服务条款：",
            "- 送货到门口路边，不含其他任何操作",
            f"- {service_line}",
            "",
            "尾板费用：",
            "- 收货方无卸货平台需司机卸货至地面：+$50/票",
            "- 尾板承重500KG/板，>500KG及超长货物由收货人自卸",
            "- 需司机手叉车配合：另+$50USD",
            "- 免费等待30分钟，超过按$35USD/半小时计（不满半小时按半小时算）",
            "",
            "- 价格为预估，最终以供应商实测地址及卡车准入情况为准",
            "- 如下单后需填写对应单号引用此报价",
        ]
    )


def _request_risk_tags(request: ZoneQuoteRequest) -> list[str]:
    tags: list[str] = []
    if request.requires_liftgate:
        tags.append("liftgate_required")
    if request.requires_pallet_jack:
        tags.append("pallet_jack_required")
    if request.requires_appointment:
        tags.append("appointment_required")
    if request.address_type.value != "commercial":
        tags.append("residential")
    return tags


def _format_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    value = money(value)
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return f"{value:.2f}"
