from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.db.models import CityAlias, PostalCodeCityLookup, PostalZoneOverride, ZoneLookupRule, ZonePriceMatrix
from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.zone_lookup import normalize_origin
from packages.quote_engine.zone_models import (
    CityAliasRecord,
    PostalCodeCityRecord,
    PostalZoneOverrideRecord,
    ZoneLookupRuleRecord,
    ZonePriceRecord,
)


class ZoneRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_preferred_city(self, postal_code: str) -> PostalCodeCityRecord | None:
        normalized = normalize_postal_code(postal_code)
        if normalized is None:
            return None
        record = self.session.get(PostalCodeCityLookup, normalized)
        if record is None:
            return None
        return PostalCodeCityRecord(
            postal_code=record.postal_code,
            preferred_city=record.preferred_city,
            province=record.province,
            fsa=record.fsa,
            official_city=record.official_city,
            municipality=record.municipality,
            latitude=record.latitude,
            longitude=record.longitude,
            source=record.source,
        )

    def get_postal_zone_override(self, postal_code: str) -> PostalZoneOverrideRecord | None:
        normalized = normalize_postal_code(postal_code)
        if normalized is None:
            return None
        record = self.session.scalars(
            select(PostalZoneOverride).where(
                PostalZoneOverride.postal_code == normalized,
                PostalZoneOverride.active.is_(True),
            )
        ).first()
        if record is None:
            return None
        return PostalZoneOverrideRecord(
            postal_code=record.postal_code,
            postal_prefix=record.postal_prefix,
            province=record.province,
            canonical_city=record.canonical_city,
            origin=normalize_origin(record.origin) or record.origin,
            zone=record.zone,
            confidence=record.confidence,
            source=record.source,
            note=record.note,
        )

    def list_city_aliases(self, province: str | None) -> list[CityAliasRecord]:
        normalized_province = normalize_province(province)
        query = select(CityAlias).where(CityAlias.active.is_(True))
        if normalized_province:
            query = query.where(CityAlias.province == normalized_province)
        records = self.session.scalars(query).all()
        return [
            CityAliasRecord(
                province=record.province,
                alias_city=record.alias_city,
                canonical_city=record.canonical_city,
                alias_type=record.alias_type,
            )
            for record in records
        ]

    def resolve_city_alias(self, city: str | None, province: str | None) -> str | None:
        normalized_city = normalize_city(city)
        normalized_province = normalize_province(province)
        if normalized_city is None or normalized_province is None:
            return normalized_city
        record = self.session.scalars(
            select(CityAlias).where(
                CityAlias.alias_city == normalized_city.upper(),
                CityAlias.province == normalized_province,
                CityAlias.active.is_(True),
            )
        ).first()
        if record is None:
            return normalized_city
        return record.canonical_city

    def list_zone_rules(self, postal_prefix: str) -> list[ZoneLookupRuleRecord]:
        prefix = extract_fsa(postal_prefix) or postal_prefix.upper().replace(" ", "")[:3]
        records = self.session.scalars(
            select(ZoneLookupRule)
            .where(ZoneLookupRule.postal_prefix == prefix, ZoneLookupRule.active.is_(True))
            .order_by(ZoneLookupRule.priority.asc(), ZoneLookupRule.id.asc())
        ).all()
        return [self._rule_record(record) for record in records]

    def list_city_zone_rules(self, city: str, province: str | None) -> list[ZoneLookupRuleRecord]:
        normalized_city = self.resolve_city_alias(city, province)
        if normalized_city is None:
            return []
        city_key = normalized_city.upper()
        query = (
            select(ZoneLookupRule)
            .where(
                ZoneLookupRule.active.is_(True),
                or_(ZoneLookupRule.canonical_city == city_key, ZoneLookupRule.city == city_key),
            )
            .order_by(ZoneLookupRule.priority.asc(), ZoneLookupRule.id.asc())
        )
        if province:
            normalized_province = normalize_province(province)
            if normalized_province:
                query = query.where(ZoneLookupRule.province == normalized_province)
        records = self.session.scalars(query).all()
        return [self._rule_record(record) for record in records]

    def list_postal_family_zone_rules(self, postal_prefix: str, province: str | None) -> list[ZoneLookupRuleRecord]:
        prefix = extract_fsa(postal_prefix) or postal_prefix.upper().replace(" ", "")[:3]
        family = prefix[:2] if len(prefix) >= 2 else prefix[:1]
        if not family:
            return []
        query = (
            select(ZoneLookupRule)
            .where(
                ZoneLookupRule.active.is_(True),
                ZoneLookupRule.postal_prefix.like(f"{family}%"),
            )
            .order_by(ZoneLookupRule.priority.asc(), ZoneLookupRule.postal_prefix.asc(), ZoneLookupRule.id.asc())
        )
        normalized_province = normalize_province(province)
        if normalized_province:
            query = query.where(ZoneLookupRule.province == normalized_province)
        records = self.session.scalars(query).all()
        return [self._rule_record(record) for record in records]

    def _rule_record(self, record: ZoneLookupRule) -> ZoneLookupRuleRecord:
        return ZoneLookupRuleRecord(
            postal_prefix=record.postal_prefix,
            city=record.city,
            province=record.province,
            origin=normalize_origin(record.origin) or record.origin,
            zone=record.zone,
            canonical_city=record.canonical_city,
            priority=record.priority,
            active=record.active,
            match_level=record.match_level,
            note=record.note,
        )

    def get_zone_price(self, origin: str, zone: int, billing_pallets: int) -> ZonePriceRecord | None:
        normalized_origin = normalize_origin(origin)
        if normalized_origin is None:
            return None
        record = self.session.scalars(
            select(ZonePriceMatrix).where(
                ZonePriceMatrix.origin == normalized_origin,
                ZonePriceMatrix.zone == zone,
                ZonePriceMatrix.billing_pallets == billing_pallets,
            )
        ).first()
        if record is None:
            return None
        return ZonePriceRecord(
            origin=record.origin,
            zone=record.zone,
            billing_pallets=record.billing_pallets,
            base_price_usd=record.base_price_usd,
            source=record.source,
            last_updated=record.last_updated,
        )
