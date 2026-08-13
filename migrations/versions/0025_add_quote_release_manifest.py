"""Add the database-owned quote release manifest."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0025_add_quote_release_manifest"
down_revision: str | None = "0024_api_key_tenant_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quote_release_manifest",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=128), nullable=False),
        sa.Column("service_version", sa.String(length=128), nullable=False),
        sa.Column("rule_version", sa.String(length=128), nullable=False),
        sa.Column("data_version", sa.String(length=128), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("test_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("release_id", name="uq_quote_release_manifest_release_id"),
    )
    op.create_index("ix_quote_release_manifest_release_id", "quote_release_manifest", ["release_id"])
    op.create_index("ix_quote_release_manifest_active", "quote_release_manifest", ["active"])


def downgrade() -> None:
    op.drop_index("ix_quote_release_manifest_active", table_name="quote_release_manifest")
    op.drop_index("ix_quote_release_manifest_release_id", table_name="quote_release_manifest")
    op.drop_table("quote_release_manifest")
