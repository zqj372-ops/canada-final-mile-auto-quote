from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from apps.api.db.models import VendorRateRule
from packages.address_normalizer import extract_fsa
from packages.quote_engine.matching import fingerprint_address
from packages.quote_engine.models import RateRule, ShipmentInput, SourceType


class RateRuleRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_candidate_rules(self, shipment: ShipmentInput) -> list[RateRule]:
        stmt = select(VendorRateRule).where(
            VendorRateRule.status == "active",
            VendorRateRule.pallet_min <= shipment.pallet_count,
            VendorRateRule.pallet_max >= shipment.pallet_count,
            self._origin_matches(shipment.origin_warehouse),
            self._province_matches(shipment.province),
            self._weight_matches(shipment),
            self._candidate_scope(shipment),
        )

        records = self.session.scalars(stmt).all()
        return [self._to_rate_rule(record) for record in records]

    def _origin_matches(self, origin_warehouse: str | None):
        if not origin_warehouse:
            return VendorRateRule.origin_warehouse.is_(None)
        return or_(
            VendorRateRule.origin_warehouse.is_(None),
            func.lower(VendorRateRule.origin_warehouse) == origin_warehouse.lower(),
        )

    def _province_matches(self, province: str | None):
        if not province:
            return VendorRateRule.province.is_(None)
        return or_(VendorRateRule.province.is_(None), VendorRateRule.province == province)

    def _weight_matches(self, shipment: ShipmentInput):
        if shipment.weight_kg is None:
            return True
        return and_(
            or_(VendorRateRule.weight_min_kg.is_(None), VendorRateRule.weight_min_kg <= shipment.weight_kg),
            or_(VendorRateRule.weight_max_kg.is_(None), VendorRateRule.weight_max_kg >= shipment.weight_kg),
        )

    def _candidate_scope(self, shipment: ShipmentInput):
        address_fingerprint = fingerprint_address(shipment.address_line)
        postal_code = shipment.postal_code
        fsa = extract_fsa(postal_code)
        conditions = []

        if address_fingerprint:
            conditions.append(
                and_(
                    VendorRateRule.source_type == SourceType.HISTORY_EXACT_ADDRESS.value,
                    VendorRateRule.address_fingerprint == address_fingerprint,
                )
            )
        if postal_code:
            conditions.append(
                and_(
                    VendorRateRule.source_type == SourceType.POSTAL_CODE.value,
                    VendorRateRule.postal_code == postal_code,
                )
            )
        if fsa:
            conditions.append(and_(VendorRateRule.source_type == SourceType.FSA.value, VendorRateRule.fsa == fsa))
        if shipment.city and shipment.province:
            conditions.append(
                and_(
                    VendorRateRule.source_type == SourceType.CITY.value,
                    VendorRateRule.city == shipment.city,
                    VendorRateRule.province == shipment.province,
                )
            )

        conditions.append(VendorRateRule.source_type == SourceType.RATE_CARD.value)
        return or_(*conditions)

    def _to_rate_rule(self, record: VendorRateRule) -> RateRule:
        return RateRule(
            rule_id=record.rule_id,
            source_type=SourceType(record.source_type),
            origin_warehouse=record.origin_warehouse,
            vendor_name=record.vendor_name,
            province=record.province,
            city=record.city,
            fsa=record.fsa,
            postal_code=record.postal_code,
            address_fingerprint=record.address_fingerprint,
            pallet_min=record.pallet_min,
            pallet_max=record.pallet_max,
            weight_min_kg=record.weight_min_kg,
            weight_max_kg=record.weight_max_kg,
            base_cost_cad=record.base_cost_cad,
            fuel_percent=record.fuel_percent,
            appointment_fee_cad=record.appointment_fee_cad,
            liftgate_fee_cad=record.liftgate_fee_cad,
            residential_fee_cad=record.residential_fee_cad,
            limited_access_fee_cad=record.limited_access_fee_cad,
            remote_fee_cad=record.remote_fee_cad,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            status=record.status,
        )

