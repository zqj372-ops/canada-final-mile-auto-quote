"""Add Hermes diagnostic queue.

Revision ID: 0014_add_hermes_diagnostic_queue
Revises: 0013_add_users_and_sales_quote_records
Create Date: 2026-07-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0014_add_hermes_diagnostic_queue"
down_revision: str | None = "0013_add_users_and_sales_quote_records"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "hermes_diagnostic_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("quote_id", sa.String(length=64), nullable=False),
        sa.Column("quote_status", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("diagnostic_package_json", sa.JSON(), nullable=False),
        sa.Column("agent_suggestion_json", sa.JSON(), nullable=True),
        sa.Column("agent_error", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("recommend_manual_review", sa.Boolean(), nullable=True),
        sa.Column("recommend_learning_candidate", sa.Boolean(), nullable=True),
        sa.Column("learning_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in [
        "quote_id",
        "quote_status",
        "source_type",
        "status",
        "suggested_action",
        "learning_candidate_id",
    ]:
        op.create_index(
            f"ix_hermes_diagnostic_queue_{column_name}",
            "hermes_diagnostic_queue",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("hermes_diagnostic_queue")
