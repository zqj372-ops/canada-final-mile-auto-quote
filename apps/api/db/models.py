from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="sales", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime] = mapped_column(
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
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    fsa: Mapped[str | None] = mapped_column(String(3), index=True)
    official_city: Mapped[str | None] = mapped_column(String(100))
    municipality: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    source: Mapped[str | None] = mapped_column(Text)
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
    canonical_city: Mapped[str | None] = mapped_column(String(100), index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100", index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
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


class PostalZoneOverride(Base):
    __tablename__ = "postal_zone_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, index=True)
    postal_prefix: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    province: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    canonical_city: Mapped[str | None] = mapped_column(String(100), index=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    source: Mapped[str | None] = mapped_column(Text)
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


class CityAlias(Base):
    __tablename__ = "city_aliases"
    __table_args__ = (
        UniqueConstraint("province", "alias_city", name="uq_city_aliases_province_alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    alias_city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    alias_type: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    source: Mapped[str | None] = mapped_column(Text)
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


class FCLRateCard(Base):
    __tablename__ = "fcl_rate_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pod: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    container_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    carrier: Mapped[str | None] = mapped_column(String(128), index=True)
    service: Mapped[str | None] = mapped_column(String(128), index=True)
    service_scope: Mapped[str | None] = mapped_column(String(32), index=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    etd_date: Mapped[date | None] = mapped_column(Date, index=True)
    vessel_voyage: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100", index=True)
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", server_default="draft", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    fee_lines: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
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


class FCLQuoteConfigVersion(Base):
    __tablename__ = "fcl_quote_config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    config_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


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


class SalesQuoteRecord(Base):
    __tablename__ = "sales_quote_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_type: Mapped[str] = mapped_column(String(32), nullable=False, default="final_mile", index=True)
    quote_id: Mapped[str | None] = mapped_column(String(64), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    actor_api_key_id: Mapped[int | None] = mapped_column(Integer, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(128), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    workflow_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_until: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action_by: Mapped[str | None] = mapped_column(String(128))
    last_action_role: Mapped[str | None] = mapped_column(String(32))
    sent_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    customer_message: Mapped[str] = mapped_column(Text, nullable=False)
    customer_reply: Mapped[str | None] = mapped_column(Text)
    request_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ManualQuoteTask(Base):
    __tablename__ = "manual_quote_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sales_quote_record_id: Mapped[int | None] = mapped_column(ForeignKey("sales_quote_records.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    request_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128))
    resolved_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    resolved_note: Mapped[str | None] = mapped_column(Text)
    fee_items: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    totals_by_currency: Mapped[dict[str, object] | None] = mapped_column(JSON)
    settlement_currency: Mapped[str | None] = mapped_column(String(8))
    converted_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    valid_until: Mapped[date | None] = mapped_column(Date)
    public_note: Mapped[str | None] = mapped_column(Text)
    customer_terms: Mapped[list[str] | None] = mapped_column(JSON)
    customer_reply: Mapped[str | None] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)
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


class QuoteWorkflowEvent(Base):
    __tablename__ = "quote_workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("sales_quote_records.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[int | None] = mapped_column(Integer)
    actor_name: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    public_note: Mapped[str | None] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


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


class AIAgentModelAssignment(Base):
    __tablename__ = "ai_agent_model_assignments"

    agent_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    ai_model_config_id: Mapped[int] = mapped_column(
        ForeignKey("ai_model_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    webhook_url_encrypted: Mapped[str | None] = mapped_column(Text)
    bot_id: Mapped[str | None] = mapped_column(String(128))
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
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


class EmailNotificationConfig(Base):
    __tablename__ = "email_notification_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    username: Mapped[str | None] = mapped_column(String(255))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(128))
    recipient_emails: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="general", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
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


class SearchApiConfig(Base):
    __tablename__ = "search_api_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="tavily")
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="general", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
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


class LearnedQuoteRule(Base):
    __tablename__ = "learned_quote_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_task_id: Mapped[int | None] = mapped_column(Integer, index=True)
    quote_id: Mapped[str | None] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    postal_prefix: Mapped[str | None] = mapped_column(String(3), index=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    province: Mapped[str | None] = mapped_column(String(10), index=True)
    origin: Mapped[str | None] = mapped_column(String(32), index=True)
    zone: Mapped[int | None] = mapped_column(Integer, index=True)
    billing_pallets: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conditions_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    total_price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    base_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HermesLearningCandidate(Base):
    __tablename__ = "hermes_learning_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_task_id: Mapped[int | None] = mapped_column(Integer, index=True)
    quote_id: Mapped[str | None] = mapped_column(String(64), index=True)
    candidate_type: Mapped[str] = mapped_column(String(64), nullable=False, default="learned_exception_price", index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    postal_prefix: Mapped[str | None] = mapped_column(String(3), index=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    province: Mapped[str | None] = mapped_column(String(10), index=True)
    origin: Mapped[str | None] = mapped_column(String(32), index=True)
    zone: Mapped[int | None] = mapped_column(Integer, index=True)
    billing_pallets: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    resolved_total_price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    resolved_base_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", index=True)
    duplicate_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    proposal_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    risk_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_rule_id: Mapped[int | None] = mapped_column(Integer, index=True)
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


class HermesDiagnosticQueue(Base):
    __tablename__ = "hermes_diagnostic_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quote_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    diagnostic_package_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    agent_suggestion_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    agent_error: Mapped[str | None] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(String(64), index=True)
    confidence: Mapped[int | None] = mapped_column(Integer)
    recommend_manual_review: Mapped[bool | None] = mapped_column(Boolean)
    recommend_learning_candidate: Mapped[bool | None] = mapped_column(Boolean)
    learning_candidate_id: Mapped[int | None] = mapped_column(Integer, index=True)
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


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
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
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
