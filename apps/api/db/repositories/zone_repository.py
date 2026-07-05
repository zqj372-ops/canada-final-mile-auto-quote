from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from packages.address_normalizer import extract_fsa, normalize_postal_code
from packages.quote_engine.zone_lookup import normalize_origin
from packages.quote_engine.zone_models import PostalCodeCityRecord, ZoneLookupRuleRecord, ZonePriceRecord


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
        )

    def list_zone_rules(self, postal_prefix: str) -> list[ZoneLookupRuleRecord]:
        prefix = extract_fsa(postal_prefix) or postal_prefix.upper().replace(" ", "")[:3]
        records = self.session.scalars(
            select(ZoneLookupRule).where(ZoneLookupRule.postal_prefix == prefix)
        ).all()
        return [
            ZoneLookupRuleRecord(
                postal_prefix=record.postal_prefix,
                city=record.city,
                province=record.province,
                origin=normalize_origin(record.origin) or record.origin,
                zone=record.zone,
                match_level=record.match_level,
                note=record.note,
            )
            for record in records
        ]

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
