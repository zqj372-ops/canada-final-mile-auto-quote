from decimal import Decimal
from typing import Protocol

from packages.address_normalizer import extract_fsa
from packages.quote_engine.pallet_calculator import calculate_billing_pallets
from packages.quote_engine.pricing import money
from packages.quote_engine.risk_tags import RURAL_FSA_SECONDARY_CONFIRMATION_TAG, rural_fsa_risk_tags
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_lookup import (
    ORIGIN_BY_PROVINCE,
    get_province_from_postal_code,
    lookup_zone,
    lookup_zone_by_city_province,
    normalize_origin,
    origin_label,
)
from packages.quote_engine.zone_models import (
    CityAliasRecord,
    PostalCodeCityRecord,
    PostalZoneOverrideRecord,
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

    def get_postal_zone_override(self, postal_code: str) -> PostalZoneOverrideRecord | None:
        ...

    def list_city_aliases(self, province: str | None) -> list[CityAliasRecord]:
        ...

    def list_zone_rules(self, postal_prefix: str) -> list[ZoneLookupRuleRecord]:
        ...

    def list_city_zone_rules(self, city: str, province: str | None) -> list[ZoneLookupRuleRecord]:
        ...

    def get_zone_price(self, origin: str, zone: int, billing_pallets: int) -> ZonePriceRecord | None:
        ...


class ZoneQuoteEngine:
    def __init__(self, provider: ZoneDataProvider, pricing_config: ZonePricingConfig | None = None):
        self.provider = provider
        self.pricing_config = pricing_config or ZonePricingConfig()

    def quote(self, request: ZoneQuoteRequest) -> ZoneQuoteResult:
        postal_prefix = extract_fsa(request.postal_code)
        if not postal_prefix:
            return self._manual(
                request,
                "无法从邮编中识别加拿大 FSA/邮编前缀。",
                ("postal_prefix_missing",),
                matched_by="postal_prefix_missing",
                candidate_count=0,
                match_trace={"postal_code": request.postal_code, "matched_by": "postal_prefix_missing"},
            )

        preferred_record = self.provider.get_preferred_city(request.postal_code)
        preferred_city = preferred_record.preferred_city if preferred_record else None
        province = get_province_from_postal_code(request.postal_code)
        province = province or (preferred_record.province if preferred_record else None) or request.province
        city = preferred_city or request.city

        pallet_result = calculate_billing_pallets(
            cbm=request.cbm,
            weight_kg=request.weight_kg,
            piece_count=request.piece_count,
            packaging_type=request.packaging_type,
            longest_side_cm=request.longest_side_cm,
            explicit_pallet_count=request.explicit_pallet_count,
            is_stackable=request.is_stackable,
        )
        zone_rules = self.provider.list_zone_rules(postal_prefix)
        zone_decision = lookup_zone(
            postal_code=request.postal_code,
            postal_prefix=postal_prefix,
            input_city=request.city,
            preferred_city=preferred_city,
            province=province,
            rules=zone_rules,
            aliases=self.provider.list_city_aliases(province),
            override=self.provider.get_postal_zone_override(request.postal_code),
        )
        expected_origin = ORIGIN_BY_PROVINCE.get(province or "")
        origin_needs_repair = (
            not zone_decision.manual_required
            and expected_origin is not None
            and (
                "stale_origin_overridden" in zone_decision.risk_tags
                or (
                    zone_decision.origin is not None
                    and normalize_origin(zone_decision.origin) != expected_origin
                )
            )
        )
        can_use_city_fallback = (
            zone_decision.manual_required
            and zone_decision.matched_by in {"zone_not_found", "province_not_found", "city_not_found"}
        )
        if (can_use_city_fallback or origin_needs_repair) and city and province:
            city_zone_rules = self.provider.list_city_zone_rules(city, province)
            city_zone_decision = lookup_zone_by_city_province(
                city=city,
                province=province,
                rules=city_zone_rules,
                requested_postal_prefix=postal_prefix,
            )
            if not city_zone_decision.manual_required or zone_decision.manual_required:
                zone_decision = city_zone_decision

        stale_origin = "stale_origin_overridden" in zone_decision.risk_tags
        origin_mismatch = (
            zone_decision.origin is not None
            and expected_origin is not None
            and normalize_origin(zone_decision.origin) != expected_origin
        )
        if not zone_decision.manual_required and expected_origin and (stale_origin or origin_mismatch):
            rejected_origin = zone_decision.origin
            rejected_zone = zone_decision.zone
            # ponytail: never reuse a Zone number across the Toronto and Calgary matrices.
            return self._manual(
                request,
                (
                    f"始发仓与 Zone 规则来源不一致：{province} 应从 {expected_origin} 起运，"
                    f"已拒绝 {rejected_origin or '未知始发仓'} Zone {rejected_zone or '未知'}。"
                ),
                [*zone_decision.risk_tags, *pallet_result.risk_tags, "origin_matrix_mismatch"],
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                billing_pallets=pallet_result.billing_pallets,
                pallet_breakdown=pallet_result.components,
                matched_by="origin_matrix_guard",
                candidate_count=zone_decision.candidate_count,
                match_trace={
                    **zone_decision.match_trace,
                    "expected_origin": expected_origin,
                    "rejected_origin": rejected_origin,
                    "rejected_zone": rejected_zone,
                    "rejected_matched_by": zone_decision.matched_by,
                    "matched_by": "origin_matrix_guard",
                },
                internal_note="已在价格矩阵查询前阻止跨始发仓复用 Zone，需人工确认正确分区。",
            )
        # FSA character order is not geographic distance. If neither the exact
        # FSA nor a same-city/province anchor is available, the quote must stay
        # manual instead of borrowing a price from an alphabetically nearby FSA.
        if zone_decision.manual_required or zone_decision.origin is None or zone_decision.zone is None:
            return self._manual(
                request,
                zone_decision.matched_rule,
                [*zone_decision.risk_tags, *pallet_result.risk_tags],
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                billing_pallets=pallet_result.billing_pallets,
                pallet_breakdown=pallet_result.components,
                internal_note=_manual_note_with_pallets(pallet_result.billing_pallets),
                zone_decision=zone_decision,
            )

        if pallet_result.manual_review_required or pallet_result.billing_pallets is None:
            return self._manual(
                request,
                pallet_result.internal_note or "计费托数需要人工确认。",
                pallet_result.risk_tags,
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                origin=zone_decision.origin,
                zone=zone_decision.zone,
                pallet_breakdown=pallet_result.components,
                zone_decision=zone_decision,
            )

        if not self.pricing_config.zone_price_enabled_for(zone_decision.origin, zone_decision.zone):
            return self._manual(
                request,
                f"分区价格已关闭：{zone_decision.origin} Zone {zone_decision.zone}。",
                [*zone_decision.risk_tags, *pallet_result.risk_tags, "zone_price_disabled"],
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                origin=zone_decision.origin,
                zone=zone_decision.zone,
                billing_pallets=pallet_result.billing_pallets,
                pallet_breakdown=pallet_result.components,
                matched_by="zone_price_disabled",
                candidate_count=zone_decision.candidate_count,
                match_trace={
                    **zone_decision.match_trace,
                    "matched_by": "zone_price_disabled",
                    "zone_price_enabled": False,
                },
                internal_note="该始发仓 + Zone 已在价格配置中关闭，保留矩阵数据但禁止自动放价。",
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
                    f"Zone 价格矩阵缺少价格：{zone_decision.origin} Zone {zone_decision.zone} "
                    f"+ {pallet_result.billing_pallets} 托。"
                ),
                ("zone_price_not_found",),
                preferred_city=preferred_city,
                postal_prefix=postal_prefix,
                city=city,
                province=province,
                origin=zone_decision.origin,
                zone=zone_decision.zone,
                billing_pallets=pallet_result.billing_pallets,
                pallet_breakdown=pallet_result.components,
                internal_note=_manual_note_with_pallets(pallet_result.billing_pallets),
                zone_decision=zone_decision,
            )

        pricing = calculate_zone_price(
            base_price_usd=money(price_record.base_price_usd),
            address_type=request.address_type,
            origin=zone_decision.origin,
            zone=zone_decision.zone,
            requires_liftgate=request.requires_liftgate,
            requires_pallet_jack=request.requires_pallet_jack,
            requires_appointment=request.requires_appointment,
            detention_minutes=request.detention_minutes,
            config=self.pricing_config,
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
            pallet_breakdown=pallet_result.components,
            base_price_usd=money(price_record.base_price_usd),
            fuel_usd=pricing.fuel_usd,
            accessorials=pricing.accessorials,
            total_price_usd=pricing.total_price_usd,
            risk_tags=sorted(set(risk_tags)),
            manual_review_required=False,
            matched_rule=matched_rule,
            matched_by=zone_decision.matched_by,
            candidate_count=zone_decision.candidate_count,
            match_trace=zone_decision.match_trace,
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
        pallet_breakdown: dict[str, int] | None = None,
        internal_note: str | None = None,
        matched_by: str | None = None,
        candidate_count: int = 0,
        match_trace: dict[str, object] | None = None,
        zone_decision: object | None = None,
    ) -> ZoneQuoteResult:
        if zone_decision is not None:
            matched_by = getattr(zone_decision, "matched_by", matched_by)
            candidate_count = getattr(zone_decision, "candidate_count", candidate_count)
            match_trace = getattr(zone_decision, "match_trace", match_trace)
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
            pallet_breakdown=pallet_breakdown or {},
            risk_tags=sorted(set([*risk_tags, *rural_fsa_risk_tags(request.postal_code)])),
            manual_review_required=True,
            matched_rule=matched_rule,
            matched_by=matched_by,
            candidate_count=candidate_count,
            match_trace=match_trace or {},
            sales_note="需要人工复核后才能向客户发送报价。",
            internal_note=internal_note or "确定性 Zone 查表报价未能完成，不能自动生成价格。",
        )


def build_zone_sales_note(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> str:
    amount = _format_money(result.total_price_usd)
    density = _format_density(request.weight_kg, request.cbm)
    cargo_line = f"共{request.piece_count}件，{request.cbm} CBM，{request.weight_kg} KG"
    if result.billing_pallets is not None:
        cargo_line += f"，计费{result.billing_pallets}托"
    if density:
        cargo_line += f"，密度{density} KG/CBM"
    if request.longest_side_cm is not None:
        cargo_line += f"，最长边{request.longest_side_cm}CM"

    rural_confirmation_lines = (
        ["二次确认：该地址为乡村邮编，完整地址、卡车准入及可能附加费需再次核实。"]
        if RURAL_FSA_SECONDARY_CONFIRMATION_TAG in result.risk_tags
        else []
    )
    return "\n".join(
        [
            "加拿大尾端派送报价：",
            f"目的地：{_destination_line(request, result)}",
            f"货物总计：{cargo_line}",
            f"报价：USD {amount}（{origin_label(result.origin)}派送）",
            *rural_confirmation_lines,
            "注：不带尾板，自卸货",
            "- 送货到门口路边，不含其他操作",
            "- 无卸货平台需尾板 +50USD/票",
            "- 需手叉车配合 +50USD/票",
            "- 免费等待30分钟，超时35USD/半小时",
            "- 价格以供应商实测地址及卡车准入情况为准",
            "- 下单引用单号，未引用加收50人民币/票服务费",
        ]
    )


def _destination_line(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> str:
    parts = [
        request.address_line,
        result.city or request.city,
        result.province or request.province,
        result.postal_code or request.postal_code,
    ]
    return ", ".join(str(part) for part in parts if part)


def _request_risk_tags(request: ZoneQuoteRequest) -> list[str]:
    tags = rural_fsa_risk_tags(request.postal_code)
    if request.requires_liftgate:
        tags.append("liftgate_required")
    if request.requires_pallet_jack:
        tags.append("pallet_jack_required")
    if request.requires_appointment:
        tags.append("appointment_required")
    if request.address_type.value != "commercial":
        tags.append("residential")
    return tags


def _manual_note_with_pallets(billing_pallets: int | None) -> str:
    if billing_pallets is None:
        return "确定性 Zone 查表报价未能完成，且计费托数需要人工确认，不能自动生成价格。"
    return f"已按托数规则估算计费托数为 {billing_pallets} 托；但价格表/Zone 未命中，不能自动生成金额。"


def _format_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    value = money(value)
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return f"{value:.2f}"


def _format_density(weight_kg: Decimal, cbm: Decimal) -> str:
    if cbm <= 0:
        return ""
    density = weight_kg / cbm
    return f"{density.quantize(Decimal('0.1'))}"
