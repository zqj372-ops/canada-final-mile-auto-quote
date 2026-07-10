"""Add per-agent AI model assignments.

Revision ID: 0015_ai_agent_model_assignments
Revises: 0014_add_hermes_diagnostic_queue
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0015_ai_agent_model_assignments"
down_revision: str | None = "0014_add_hermes_diagnostic_queue"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_model_assignments",
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column("ai_model_config_id", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ai_model_config_id"],
            ["ai_model_configs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("agent_key"),
    )
    op.create_index(
        "ix_ai_agent_model_assignments_ai_model_config_id",
        "ai_agent_model_assignments",
        ["ai_model_config_id"],
    )


def downgrade() -> None:
    op.drop_table("ai_agent_model_assignments")
