"""Add learned quote rules.

Revision ID: 0004_add_learned_quote_rules
Revises: 0003_add_search_api_configs
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_add_learned_quote_rules"
down_revision: str | None = "0003_add_search_api_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learned_quote_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_task_id", sa.Integer(), nullable=True),
        sa.Column("quote_id", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("postal_code", sa.String(length=10), nullable=True),
        sa.Column("postal_prefix", sa.String(length=3), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("province", sa.String(length=10), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=True),
        sa.Column("zone", sa.Integer(), nullable=True),
        sa.Column("billing_pallets", sa.Integer(), nullable=False),
        sa.Column("total_price_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("base_price_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_learned_quote_rules_source_task_id", "learned_quote_rules", ["source_task_id"])
    op.create_index("ix_learned_quote_rules_quote_id", "learned_quote_rules", ["quote_id"])
    op.create_index("ix_learned_quote_rules_scope", "learned_quote_rules", ["scope"])
    op.create_index("ix_learned_quote_rules_postal_code", "learned_quote_rules", ["postal_code"])
    op.create_index("ix_learned_quote_rules_postal_prefix", "learned_quote_rules", ["postal_prefix"])
    op.create_index("ix_learned_quote_rules_city", "learned_quote_rules", ["city"])
    op.create_index("ix_learned_quote_rules_province", "learned_quote_rules", ["province"])
    op.create_index("ix_learned_quote_rules_origin", "learned_quote_rules", ["origin"])
    op.create_index("ix_learned_quote_rules_zone", "learned_quote_rules", ["zone"])
    op.create_index("ix_learned_quote_rules_billing_pallets", "learned_quote_rules", ["billing_pallets"])
    op.create_index("ix_learned_quote_rules_status", "learned_quote_rules", ["status"])


def downgrade() -> None:
    op.drop_table("learned_quote_rules")
