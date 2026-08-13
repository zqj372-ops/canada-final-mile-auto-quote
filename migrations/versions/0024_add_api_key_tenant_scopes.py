"""Add API key tenant and scope boundaries."""

from alembic import op
import sqlalchemy as sa


revision: str = "0024_api_key_tenant_scopes"
down_revision: str | None = "0023_repair_oversize_snapshot_indexes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default="default"),
    )
    op.add_column(
        "api_keys",
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_column("api_keys", "scopes")
    op.drop_column("api_keys", "tenant_id")
