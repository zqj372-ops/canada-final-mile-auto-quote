from collections.abc import Mapping

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.db.models import ZoneLookupRule
from packages.address_normalizer import extract_fsa, normalize_city, normalize_province
from packages.quote_engine.zone_lookup import (
    ORIGIN_BY_PROVINCE,
    get_province_from_strict_fsa,
    normalize_origin,
)


class ZoneCityRuleRepository:
    """Admin-facing CRUD for the city/FSA rules used by Zone lookup."""

    def __init__(self, session: Session):
        self.session = session

    def list_rules(
        self,
        *,
        origin: str | None = None,
        zone: int | None = None,
        search: str | None = None,
        include_inactive: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, object]:
        criteria = list(
            self._criteria(
                origin=origin,
                zone=zone,
                search=search,
                include_inactive=include_inactive,
            )
        )
        query = select(ZoneLookupRule)
        count_query = select(func.count(ZoneLookupRule.id))
        city_count_query = select(
            func.count(func.distinct(func.coalesce(ZoneLookupRule.canonical_city, ZoneLookupRule.city)))
        )
        prefix_count_query = select(func.count(func.distinct(ZoneLookupRule.postal_prefix)))
        for criterion in criteria:
            query = query.where(criterion)
            count_query = count_query.where(criterion)
            city_count_query = city_count_query.where(criterion)
            prefix_count_query = prefix_count_query.where(criterion)

        records = self.session.scalars(
            query.order_by(
                ZoneLookupRule.province.asc(),
                func.coalesce(ZoneLookupRule.canonical_city, ZoneLookupRule.city).asc(),
                ZoneLookupRule.postal_prefix.asc(),
                ZoneLookupRule.priority.asc(),
                ZoneLookupRule.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "records": [self.to_dict(record) for record in records],
            "total": int(self.session.scalar(count_query) or 0),
            "city_count": int(self.session.scalar(city_count_query) or 0),
            "postal_prefix_count": int(self.session.scalar(prefix_count_query) or 0),
        }

    def create_rule(self, values: Mapping[str, object]) -> ZoneLookupRule:
        normalized = self._normalize_values(values)
        self._ensure_unique(normalized)
        record = ZoneLookupRule(**normalized)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_rule(
        self,
        record_id: int,
        values: Mapping[str, object],
    ) -> ZoneLookupRule | None:
        record = self.session.get(ZoneLookupRule, record_id)
        if record is None:
            return None
        current = {
            "postal_prefix": record.postal_prefix,
            "city": record.city,
            "province": record.province,
            "origin": record.origin,
            "zone": record.zone,
            "canonical_city": record.canonical_city,
            "priority": record.priority,
            "match_level": record.match_level,
            "note": record.note,
        }
        normalized = self._normalize_values({**current, **values})
        self._ensure_unique(normalized, exclude_id=record.id)
        for key, value in normalized.items():
            setattr(record, key, value)
        record.active = True
        self.session.commit()
        self.session.refresh(record)
        return record

    def deactivate_rule(self, record_id: int) -> ZoneLookupRule | None:
        record = self.session.get(ZoneLookupRule, record_id)
        if record is None:
            return None
        record.active = False
        self.session.commit()
        self.session.refresh(record)
        return record

    def to_dict(self, record: ZoneLookupRule) -> dict[str, object]:
        return {
            "id": record.id,
            "postal_prefix": record.postal_prefix,
            "city": record.city,
            "province": record.province,
            "origin": normalize_origin(record.origin) or record.origin,
            "zone": record.zone,
            "canonical_city": record.canonical_city,
            "priority": record.priority,
            "active": record.active,
            "match_level": record.match_level,
            "note": record.note,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _criteria(
        self,
        *,
        origin: str | None,
        zone: int | None,
        search: str | None,
        include_inactive: bool,
    ):
        normalized_origin = normalize_origin(origin)
        if normalized_origin:
            yield ZoneLookupRule.origin == normalized_origin
        if zone is not None:
            yield ZoneLookupRule.zone == zone
        if not include_inactive:
            yield ZoneLookupRule.active.is_(True)
        normalized_search = (search or "").strip()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            yield or_(
                ZoneLookupRule.city.ilike(pattern),
                ZoneLookupRule.canonical_city.ilike(pattern),
                ZoneLookupRule.postal_prefix.ilike(pattern),
                ZoneLookupRule.province.ilike(pattern),
            )

    def _normalize_values(self, values: Mapping[str, object]) -> dict[str, object]:
        raw_prefix = str(values.get("postal_prefix") or "").strip().upper()
        postal_prefix = extract_fsa(raw_prefix)
        inferred_province = get_province_from_strict_fsa(postal_prefix)
        if postal_prefix is None or inferred_province is None:
            raise ValueError("邮编前缀必须是有效的加拿大 FSA，例如 L5T。")

        city = normalize_city(str(values.get("city") or ""))
        if city is None:
            raise ValueError("城市不能为空。")
        city = city.upper()

        province = normalize_province(str(values.get("province") or ""))
        if province is None:
            raise ValueError("省份无效，请使用 ON、AB、BC 等加拿大省份代码。")
        if inferred_province != province:
            raise ValueError(f"邮编前缀 {postal_prefix} 属于 {inferred_province}，不能配置为 {province}。")

        origin = normalize_origin(str(values.get("origin") or ""))
        if origin is None:
            raise ValueError("始发仓不能为空。")
        expected_origin = ORIGIN_BY_PROVINCE.get(province)
        if expected_origin and origin != expected_origin:
            raise ValueError(f"{province} 的始发仓应为 {expected_origin}，不能配置为 {origin}。")

        try:
            zone = int(values.get("zone") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Zone 必须是正整数。") from exc
        if zone < 1:
            raise ValueError("Zone 必须是正整数。")

        canonical_city = normalize_city(str(values.get("canonical_city") or city))
        canonical_city = (canonical_city or city).upper()
        try:
            priority = int(values.get("priority") or 100)
        except (TypeError, ValueError) as exc:
            raise ValueError("优先级必须是 1 至 1000 的整数。") from exc
        if priority < 1 or priority > 1000:
            raise ValueError("优先级必须是 1 至 1000 的整数。")

        match_level = str(values.get("match_level") or "admin_city_config").strip() or "admin_city_config"
        note = str(values.get("note") or "").strip() or None
        return {
            "postal_prefix": postal_prefix,
            "city": city,
            "province": province,
            "origin": origin,
            "zone": zone,
            "canonical_city": canonical_city,
            "priority": priority,
            "match_level": match_level,
            "note": note,
            "active": True,
        }

    def _ensure_unique(
        self,
        values: Mapping[str, object],
        *,
        exclude_id: int | None = None,
    ) -> None:
        query = select(ZoneLookupRule).where(
            ZoneLookupRule.active.is_(True),
            ZoneLookupRule.postal_prefix == values["postal_prefix"],
            ZoneLookupRule.province == values["province"],
            func.upper(func.coalesce(ZoneLookupRule.canonical_city, ZoneLookupRule.city))
            == values["canonical_city"],
        )
        if exclude_id is not None:
            query = query.where(ZoneLookupRule.id != exclude_id)
        duplicate = self.session.scalars(query).first()
        if duplicate is None:
            return
        raise ValueError(
            "该城市与邮编前缀已有有效分区配置："
            f"{duplicate.origin} Zone {duplicate.zone}。请直接编辑原规则。"
        )
