"""Add zone matching overrides and city aliases.

Revision ID: 0005_zone_match_aliases
Revises: 0004_add_learned_quote_rules
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_zone_match_aliases"
down_revision: str | None = "0004_add_learned_quote_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("postal_code_city_lookup", sa.Column("fsa", sa.String(length=3), nullable=True))
    op.add_column("postal_code_city_lookup", sa.Column("official_city", sa.String(length=100), nullable=True))
    op.add_column("postal_code_city_lookup", sa.Column("municipality", sa.String(length=100), nullable=True))
    op.add_column("postal_code_city_lookup", sa.Column("latitude", sa.Numeric(10, 6), nullable=True))
    op.add_column("postal_code_city_lookup", sa.Column("longitude", sa.Numeric(10, 6), nullable=True))
    op.add_column("postal_code_city_lookup", sa.Column("source", sa.Text(), nullable=True))
    op.create_index("ix_postal_code_city_lookup_fsa", "postal_code_city_lookup", ["fsa"])

    op.add_column("zone_lookup_rules", sa.Column("canonical_city", sa.String(length=100), nullable=True))
    op.add_column("zone_lookup_rules", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("zone_lookup_rules", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_zone_lookup_rules_canonical_city", "zone_lookup_rules", ["canonical_city"])
    op.create_index("ix_zone_lookup_rules_priority", "zone_lookup_rules", ["priority"])
    op.create_index("ix_zone_lookup_rules_active", "zone_lookup_rules", ["active"])
    op.execute("UPDATE zone_lookup_rules SET canonical_city = UPPER(city) WHERE canonical_city IS NULL")

    op.create_table(
        "postal_zone_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("postal_code", sa.String(length=10), nullable=False),
        sa.Column("postal_prefix", sa.String(length=3), nullable=False),
        sa.Column("province", sa.String(length=10), nullable=False),
        sa.Column("canonical_city", sa.String(length=100), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("zone", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("postal_code"),
    )
    op.create_index("ix_postal_zone_overrides_postal_code", "postal_zone_overrides", ["postal_code"])
    op.create_index("ix_postal_zone_overrides_postal_prefix", "postal_zone_overrides", ["postal_prefix"])
    op.create_index("ix_postal_zone_overrides_province", "postal_zone_overrides", ["province"])
    op.create_index("ix_postal_zone_overrides_canonical_city", "postal_zone_overrides", ["canonical_city"])
    op.create_index("ix_postal_zone_overrides_origin", "postal_zone_overrides", ["origin"])
    op.create_index("ix_postal_zone_overrides_zone", "postal_zone_overrides", ["zone"])
    op.create_index("ix_postal_zone_overrides_active", "postal_zone_overrides", ["active"])

    op.create_table(
        "city_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("province", sa.String(length=10), nullable=False),
        sa.Column("alias_city", sa.String(length=100), nullable=False),
        sa.Column("canonical_city", sa.String(length=100), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("province", "alias_city", name="uq_city_aliases_province_alias"),
    )
    op.create_index("ix_city_aliases_province", "city_aliases", ["province"])
    op.create_index("ix_city_aliases_alias_city", "city_aliases", ["alias_city"])
    op.create_index("ix_city_aliases_canonical_city", "city_aliases", ["canonical_city"])
    op.create_index("ix_city_aliases_active", "city_aliases", ["active"])


def downgrade() -> None:
    op.drop_table("city_aliases")
    op.drop_table("postal_zone_overrides")
    op.drop_index("ix_zone_lookup_rules_active", table_name="zone_lookup_rules")
    op.drop_index("ix_zone_lookup_rules_priority", table_name="zone_lookup_rules")
    op.drop_index("ix_zone_lookup_rules_canonical_city", table_name="zone_lookup_rules")
    op.drop_column("zone_lookup_rules", "active")
    op.drop_column("zone_lookup_rules", "priority")
    op.drop_column("zone_lookup_rules", "canonical_city")
    op.drop_index("ix_postal_code_city_lookup_fsa", table_name="postal_code_city_lookup")
    op.drop_column("postal_code_city_lookup", "source")
    op.drop_column("postal_code_city_lookup", "longitude")
    op.drop_column("postal_code_city_lookup", "latitude")
    op.drop_column("postal_code_city_lookup", "municipality")
    op.drop_column("postal_code_city_lookup", "official_city")
    op.drop_column("postal_code_city_lookup", "fsa")
