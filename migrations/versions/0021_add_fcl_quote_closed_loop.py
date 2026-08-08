"""Add the FCL quote records, rate cards, and published config versions."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_fcl_quote_closed_loop"
down_revision: str | None = "0020_zone_reference_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_quote_records",
        sa.Column("quote_type", sa.String(length=32), nullable=False, server_default="final_mile"),
    )
    op.create_index("ix_sales_quote_records_quote_type", "sales_quote_records", ["quote_type"])
    op.add_column("sales_quote_records", sa.Column("snapshot_json", sa.JSON(), nullable=True))

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
    op.drop_index("ix_fcl_quote_config_versions_version", table_name="fcl_quote_config_versions")
    op.drop_table("fcl_quote_config_versions")
    op.drop_table("fcl_rate_cards")
    op.drop_column("sales_quote_records", "snapshot_json")
    op.drop_index("ix_sales_quote_records_quote_type", table_name="sales_quote_records")
    op.drop_column("sales_quote_records", "quote_type")
