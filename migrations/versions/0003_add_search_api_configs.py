"""Add search API configs.

Revision ID: 0003_add_search_api_configs
Revises: 0002_add_api_keys
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_add_search_api_configs"
down_revision: str | None = "0002_add_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_api_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="tavily"),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_search_api_configs_purpose", "search_api_configs", ["purpose"])
    op.create_index("ix_search_api_configs_enabled", "search_api_configs", ["enabled"])
    op.create_index("ix_search_api_configs_is_default", "search_api_configs", ["is_default"])


def downgrade() -> None:
    op.drop_table("search_api_configs")
