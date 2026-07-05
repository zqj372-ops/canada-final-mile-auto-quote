from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VendorRateRule(Base):
    __tablename__ = "vendor_rate_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    origin_warehouse: Mapped[str | None] = mapped_column(String(128))
    vendor_name: Mapped[str | None] = mapped_column(String(128))
    province: Mapped[str | None] = mapped_column(String(8), index=True)
    city: Mapped[str | None] = mapped_column(String(128), index=True)
    fsa: Mapped[str | None] = mapped_column(String(3), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), index=True)
    address_fingerprint: Mapped[str | None] = mapped_column(Text, index=True)
    pallet_min: Mapped[int] = mapped_column(Integer, nullable=False)
    pallet_max: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_min_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    weight_max_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    base_cost_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fuel_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0)
    appointment_fee_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    liftgate_fee_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    residential_fee_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    limited_access_fee_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    remote_fee_cad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

