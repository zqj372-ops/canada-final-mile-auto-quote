from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, Numeric, String, Text, UniqueConstraint, func
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


class PostalCodeCityLookup(Base):
    __tablename__ = "postal_code_city_lookup"

    postal_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    preferred_city: Mapped[str] = mapped_column(String(100), nullable=False)
    province: Mapped[str | None] = mapped_column(String(10), index=True)
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


class ZoneLookupRule(Base):
    __tablename__ = "zone_lookup_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    postal_prefix: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    province: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone: Mapped[int] = mapped_column(Integer, nullable=False)
    match_level: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
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


class ZonePriceMatrix(Base):
    __tablename__ = "zone_price_matrix"
    __table_args__ = (
        UniqueConstraint("origin", "zone", "billing_pallets", name="uq_zone_price_matrix_lookup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    billing_pallets: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    base_price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    last_updated: Mapped[str | None] = mapped_column(String(64))
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


class QuoteRuleConfig(Base):
    __tablename__ = "quote_rule_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
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


class QuoteAuditLog(Base):
    __tablename__ = "quote_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    postal_prefix: Mapped[str | None] = mapped_column(String(3), index=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    province: Mapped[str | None] = mapped_column(String(10), index=True)
    origin: Mapped[str | None] = mapped_column(String(32), index=True)
    zone: Mapped[int | None] = mapped_column(Integer, index=True)
    billing_pallets: Mapped[int | None] = mapped_column(Integer)
    base_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    manual_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    risk_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ManualQuoteTask(Base):
    __tablename__ = "manual_quote_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    request_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128))
    resolved_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    resolved_note: Mapped[str | None] = mapped_column(Text)
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


class AIModelConfig(Base):
    __tablename__ = "ai_model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai")
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="general", index=True)
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


class WeComBotConfig(Base):
    __tablename__ = "wecom_bot_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    webhook_url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    bot_type: Mapped[str] = mapped_column(String(32), nullable=False, default="group_webhook")
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="general", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    mention_all_on_manual_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
