from decimal import Decimal

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from apps.api.db.models import ZonePriceMatrix
from packages.quote_engine.zone_lookup import normalize_origin


class ZonePriceMatrixRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_prices(
        self,
        *,
        origin: str | None = None,
        zone: int | None = None,
        billing_pallets: int | None = None,
        limit: int = 2000,
        offset: int = 0,
    ) -> dict[str, object]:
        query = select(ZonePriceMatrix)
        count_query = select(func.count(ZonePriceMatrix.id))

        for criterion in self._criteria(origin=origin, zone=zone, billing_pallets=billing_pallets):
            query = query.where(criterion)
            count_query = count_query.where(criterion)

        records = self.session.scalars(
            query.order_by(
                ZonePriceMatrix.origin.asc(),
                ZonePriceMatrix.zone.asc(),
                ZonePriceMatrix.billing_pallets.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()

        return {
            "records": [self.to_dict(record) for record in records],
            "total": int(self.session.scalar(count_query) or 0),
            "origins": self._distinct_strings(ZonePriceMatrix.origin),
            "zones": self._distinct_ints(ZonePriceMatrix.zone),
            "billing_pallets": self._distinct_ints(ZonePriceMatrix.billing_pallets),
        }

    def upsert_price(
        self,
        *,
        origin: str,
        zone: int,
        billing_pallets: int,
        base_price_usd: Decimal,
        source: str | None = None,
        last_updated: str | None = None,
    ) -> ZonePriceMatrix:
        normalized_origin = normalize_origin(origin)
        if normalized_origin is None:
            raise ValueError("origin is required.")

        record = self.session.scalars(
            select(ZonePriceMatrix).where(
                ZonePriceMatrix.origin == normalized_origin,
                ZonePriceMatrix.zone == zone,
                ZonePriceMatrix.billing_pallets == billing_pallets,
            )
        ).first()
        if record is None:
            record = ZonePriceMatrix(
                origin=normalized_origin,
                zone=zone,
                billing_pallets=billing_pallets,
                base_price_usd=base_price_usd,
                source=source,
                last_updated=last_updated,
            )
            self.session.add(record)
        else:
            record.base_price_usd = base_price_usd
            record.source = source
            record.last_updated = last_updated

        self.session.commit()
        self.session.refresh(record)
        return record

    def update_price(
        self,
        record_id: int,
        *,
        base_price_usd: Decimal | None = None,
        source: str | None = None,
        last_updated: str | None = None,
    ) -> ZonePriceMatrix | None:
        record = self.session.get(ZonePriceMatrix, record_id)
        if record is None:
            return None
        if base_price_usd is not None:
            record.base_price_usd = base_price_usd
        if source is not None:
            record.source = source
        if last_updated is not None:
            record.last_updated = last_updated
        self.session.commit()
        self.session.refresh(record)
        return record

    def to_dict(self, record: ZonePriceMatrix) -> dict[str, object]:
        return {
            "id": record.id,
            "origin": record.origin,
            "zone": record.zone,
            "billing_pallets": record.billing_pallets,
            "base_price_usd": record.base_price_usd,
            "source": record.source,
            "last_updated": record.last_updated,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _criteria(self, *, origin: str | None, zone: int | None, billing_pallets: int | None):
        normalized_origin = normalize_origin(origin)
        if normalized_origin:
            yield ZonePriceMatrix.origin == normalized_origin
        if zone is not None:
            yield ZonePriceMatrix.zone == zone
        if billing_pallets is not None:
            yield ZonePriceMatrix.billing_pallets == billing_pallets

    def _distinct_strings(self, column) -> list[str]:
        return [
            str(value)
            for value in self.session.scalars(select(distinct(column)).order_by(column.asc())).all()
            if value is not None
        ]

    def _distinct_ints(self, column) -> list[int]:
        return [
            int(value)
            for value in self.session.scalars(select(distinct(column)).order_by(column.asc())).all()
            if value is not None
        ]
