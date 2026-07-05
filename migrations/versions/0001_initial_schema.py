"""Initial application schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vendor_rate_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("origin_warehouse", sa.String(length=128), nullable=True),
        sa.Column("vendor_name", sa.String(length=128), nullable=True),
        sa.Column("province", sa.String(length=8), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("fsa", sa.String(length=3), nullable=True),
        sa.Column("postal_code", sa.String(length=16), nullable=True),
        sa.Column("address_fingerprint", sa.Text(), nullable=True),
        sa.Column("pallet_min", sa.Integer(), nullable=False),
        sa.Column("pallet_max", sa.Integer(), nullable=False),
        sa.Column("weight_min_kg", sa.Numeric(12, 2), nullable=True),
        sa.Column("weight_max_kg", sa.Numeric(12, 2), nullable=True),
        sa.Column("base_cost_cad", sa.Numeric(12, 2), nullable=False),
        sa.Column("fuel_percent", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("appointment_fee_cad", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("liftgate_fee_cad", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("residential_fee_cad", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("limited_access_fee_cad", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("remote_fee_cad", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("rule_id"),
    )
    op.create_index("ix_vendor_rate_rules_rule_id", "vendor_rate_rules", ["rule_id"])
    op.create_index("ix_vendor_rate_rules_source_type", "vendor_rate_rules", ["source_type"])
    op.create_index("ix_vendor_rate_rules_province", "vendor_rate_rules", ["province"])
    op.create_index("ix_vendor_rate_rules_city", "vendor_rate_rules", ["city"])
    op.create_index("ix_vendor_rate_rules_fsa", "vendor_rate_rules", ["fsa"])
    op.create_index("ix_vendor_rate_rules_postal_code", "vendor_rate_rules", ["postal_code"])
    op.create_index("ix_vendor_rate_rules_address_fingerprint", "vendor_rate_rules", ["address_fingerprint"])
    op.create_index("ix_vendor_rate_rules_status", "vendor_rate_rules", ["status"])

    op.create_table(
        "postal_code_city_lookup",
        sa.Column("postal_code", sa.String(length=10), primary_key=True),
        sa.Column("preferred_city", sa.String(length=100), nullable=False),
        sa.Column("province", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_postal_code_city_lookup_province", "postal_code_city_lookup", ["province"])

    op.create_table(
        "zone_lookup_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("postal_prefix", sa.String(length=3), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("province", sa.String(length=10), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("zone", sa.Integer(), nullable=False),
        sa.Column("match_level", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_zone_lookup_rules_postal_prefix", "zone_lookup_rules", ["postal_prefix"])
    op.create_index("ix_zone_lookup_rules_city", "zone_lookup_rules", ["city"])
    op.create_index("ix_zone_lookup_rules_province", "zone_lookup_rules", ["province"])
    op.create_index("ix_zone_lookup_rules_origin", "zone_lookup_rules", ["origin"])

    op.create_table(
        "zone_price_matrix",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("zone", sa.Integer(), nullable=False),
        sa.Column("billing_pallets", sa.Integer(), nullable=False),
        sa.Column("base_price_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("last_updated", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("origin", "zone", "billing_pallets", name="uq_zone_price_matrix_lookup"),
    )
    op.create_index("ix_zone_price_matrix_origin", "zone_price_matrix", ["origin"])
    op.create_index("ix_zone_price_matrix_zone", "zone_price_matrix", ["zone"])
    op.create_index("ix_zone_price_matrix_billing_pallets", "zone_price_matrix", ["billing_pallets"])

    op.create_table(
        "quote_rule_config",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "quote_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_id", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("postal_code", sa.String(length=10), nullable=True),
        sa.Column("postal_prefix", sa.String(length=3), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("province", sa.String(length=10), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=True),
        sa.Column("zone", sa.Integer(), nullable=True),
        sa.Column("billing_pallets", sa.Integer(), nullable=True),
        sa.Column("base_price_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_price_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False),
        sa.Column("risk_tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quote_audit_logs_quote_id", "quote_audit_logs", ["quote_id"])
    op.create_index("ix_quote_audit_logs_source_type", "quote_audit_logs", ["source_type"])
    op.create_index("ix_quote_audit_logs_postal_code", "quote_audit_logs", ["postal_code"])
    op.create_index("ix_quote_audit_logs_postal_prefix", "quote_audit_logs", ["postal_prefix"])
    op.create_index("ix_quote_audit_logs_city", "quote_audit_logs", ["city"])
    op.create_index("ix_quote_audit_logs_province", "quote_audit_logs", ["province"])
    op.create_index("ix_quote_audit_logs_origin", "quote_audit_logs", ["origin"])
    op.create_index("ix_quote_audit_logs_zone", "quote_audit_logs", ["zone"])
    op.create_index("ix_quote_audit_logs_manual_review_required", "quote_audit_logs", ["manual_review_required"])

    op.create_table(
        "manual_quote_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_tags", sa.JSON(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("assigned_to", sa.String(length=128), nullable=True),
        sa.Column("resolved_price_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("resolved_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_manual_quote_tasks_quote_id", "manual_quote_tasks", ["quote_id"])
    op.create_index("ix_manual_quote_tasks_status", "manual_quote_tasks", ["status"])

    op.create_table(
        "ai_model_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="openai"),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="800"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_model_configs_is_default", "ai_model_configs", ["is_default"])
    op.create_index("ix_ai_model_configs_enabled", "ai_model_configs", ["enabled"])
    op.create_index("ix_ai_model_configs_purpose", "ai_model_configs", ["purpose"])

    op.create_table(
        "wecom_bot_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("webhook_url_encrypted", sa.Text(), nullable=False),
        sa.Column("bot_type", sa.String(length=32), nullable=False, server_default="group_webhook"),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mention_all_on_manual_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wecom_bot_configs_purpose", "wecom_bot_configs", ["purpose"])
    op.create_index("ix_wecom_bot_configs_enabled", "wecom_bot_configs", ["enabled"])
    op.create_index("ix_wecom_bot_configs_is_default", "wecom_bot_configs", ["is_default"])


def downgrade() -> None:
    op.drop_table("wecom_bot_configs")
    op.drop_table("ai_model_configs")
    op.drop_table("manual_quote_tasks")
    op.drop_table("quote_audit_logs")
    op.drop_table("quote_rule_config")
    op.drop_table("zone_price_matrix")
    op.drop_table("zone_lookup_rules")
    op.drop_table("postal_code_city_lookup")
    op.drop_table("vendor_rate_rules")
