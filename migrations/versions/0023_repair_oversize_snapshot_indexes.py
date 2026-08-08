"""Repair production schema divergence from the pre-0021 deployment.

Production applied the original 0022 (down_revision=0020, before the FCL
chain existed) and then reverted the oversize code.  Because its
alembic_version is already past 0021, ``alembic upgrade head`` will never
run 0021 on production.  This migration converges that database to the same
schema as a fresh install:

1. oversize indexes: drop the redundant unique (rule_id, version) index and
   create the model-declared status index (newer 0022 revisions already do);
2. FCL schema parity: create the fcl_rate_cards / fcl_quote_config_versions
   tables and the sales_quote_records columns 0021 would have added.

Every step checks the live schema first, so databases that already ran 0021
and a newer 0022 are untouched (idempotent).
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0023_repair_oversize_snapshot_indexes"
down_revision: str | None = "0022_add_oversize_pallet_rule_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "oversize_pallet_rule_versions"


def _existing_index_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def _existing_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # ---- 1. Oversize snapshot indexes --------------------------------
    existing = _existing_index_names(TABLE)
    redundant = "ix_oversize_pallet_rule_versions_rule_id_version"
    if redundant in existing:
        # The unique constraint already covers (rule_id, version); the extra
        # unique index only added write amplification.
        op.drop_index(redundant, table_name=TABLE)
    if "ix_oversize_pallet_rule_versions_status" not in existing:
        op.create_index(
            "ix_oversize_pallet_rule_versions_status",
            TABLE,
            ["status"],
        )

    # ---- 2. FCL schema parity (0021 skipped on production) ------------
    if "sales_quote_records" in _existing_tables():
        columns = _existing_columns("sales_quote_records")
        if "quote_type" not in columns:
            op.add_column(
                "sales_quote_records",
                sa.Column("quote_type", sa.String(length=32), nullable=False, server_default="final_mile"),
            )
        if "snapshot_json" not in columns:
            op.add_column("sales_quote_records", sa.Column("snapshot_json", sa.JSON(), nullable=True))
        if "ix_sales_quote_records_quote_type" not in _existing_index_names("sales_quote_records"):
            op.create_index("ix_sales_quote_records_quote_type", "sales_quote_records", ["quote_type"])

    if "fcl_rate_cards" not in _existing_tables():
        op.create_table(
            "fcl_rate_cards",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("pol", sa.String(length=64), nullable=False),
            sa.Column("pod", sa.String(length=64), nullable=False),
            sa.Column("container_type", sa.String(length=32), nullable=False),
            sa.Column("carrier", sa.String(length=128), nullable=True),
            sa.Column("service", sa.String(length=128), nullable=True),
            sa.Column("service_scope", sa.String(length=32), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("etd_date", sa.Date(), nullable=True),
            sa.Column("vessel_voyage", sa.String(length=128), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("source", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("fee_lines", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        for column_name in ("pol", "pod", "container_type", "carrier", "service", "service_scope", "etd_date", "priority", "status", "enabled"):
            op.create_index(f"ix_fcl_rate_cards_{column_name}", "fcl_rate_cards", [column_name])

    if "fcl_quote_config_versions" not in _existing_tables():
        op.create_table(
            "fcl_quote_config_versions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("version", sa.Integer(), nullable=False, unique=True),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("published_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_fcl_quote_config_versions_version", "fcl_quote_config_versions", ["version"], unique=True)


def downgrade() -> None:
    if "fcl_quote_config_versions" in _existing_tables():
        op.drop_index("ix_fcl_quote_config_versions_version", table_name="fcl_quote_config_versions")
        op.drop_table("fcl_quote_config_versions")
    if "fcl_rate_cards" in _existing_tables():
        op.drop_table("fcl_rate_cards")
    if "sales_quote_records" in _existing_tables():
        if "ix_sales_quote_records_quote_type" in _existing_index_names("sales_quote_records"):
            op.drop_index("ix_sales_quote_records_quote_type", table_name="sales_quote_records")
        columns = _existing_columns("sales_quote_records")
        if "snapshot_json" in columns:
            op.drop_column("sales_quote_records", "snapshot_json")
        if "quote_type" in columns:
            op.drop_column("sales_quote_records", "quote_type")
    existing = _existing_index_names(TABLE)
    if "ix_oversize_pallet_rule_versions_status" in existing:
        op.drop_index("ix_oversize_pallet_rule_versions_status", table_name=TABLE)
    if "ix_oversize_pallet_rule_versions_rule_id_version" not in existing:
        op.create_index(
            "ix_oversize_pallet_rule_versions_rule_id_version",
            TABLE,
            ["rule_id", "version"],
            unique=True,
        )
