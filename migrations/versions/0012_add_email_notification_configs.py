"""Add email notification configs.

Revision ID: 0012_email_notification_configs
Revises: 0011_add_hermes_learning_candidates
Create Date: 2026-07-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_email_notification_configs"
down_revision: str | None = "0011_add_hermes_learning_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_notification_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("smtp_host", sa.String(length=255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("from_email", sa.String(length=255), nullable=False),
        sa.Column("from_name", sa.String(length=128), nullable=True),
        sa.Column("recipient_emails", sa.JSON(), nullable=False),
        sa.Column("use_tls", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("use_ssl", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_notification_configs_purpose", "email_notification_configs", ["purpose"])
    op.create_index("ix_email_notification_configs_enabled", "email_notification_configs", ["enabled"])
    op.create_index("ix_email_notification_configs_is_default", "email_notification_configs", ["is_default"])


def downgrade() -> None:
    op.drop_table("email_notification_configs")
