"""Bind learned prices to their accessorial conditions.

Revision ID: 0016_learned_rule_conditions
Revises: 0015_ai_agent_model_assignments
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0016_learned_rule_conditions"
down_revision: str | None = "0015_ai_agent_model_assignments"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("learned_quote_rules", sa.Column("conditions_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("learned_quote_rules", "conditions_json")
