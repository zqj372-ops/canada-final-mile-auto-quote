"""Add WeCom AIBot long connection credentials.

Revision ID: 0006_wecom_aibot_credentials
Revises: 0005_zone_match_aliases
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_wecom_aibot_credentials"
down_revision: str | None = "0005_zone_match_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wecom_bot_configs", sa.Column("bot_id", sa.String(length=128), nullable=True))
    op.add_column("wecom_bot_configs", sa.Column("secret_encrypted", sa.Text(), nullable=True))
    op.alter_column("wecom_bot_configs", "webhook_url_encrypted", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("wecom_bot_configs", "webhook_url_encrypted", existing_type=sa.Text(), nullable=False)
    op.drop_column("wecom_bot_configs", "secret_encrypted")
    op.drop_column("wecom_bot_configs", "bot_id")
