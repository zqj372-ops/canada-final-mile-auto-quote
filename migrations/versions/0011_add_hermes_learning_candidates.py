"""Add Hermes learning candidates.

Revision ID: 0011_add_hermes_learning_candidates
Revises: 0010_edmonton_zone9
Create Date: 2026-07-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_add_hermes_learning_candidates"
down_revision: str | None = "0010_edmonton_zone9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hermes_learning_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_task_id", sa.Integer(), nullable=True),
        sa.Column("quote_id", sa.String(length=64), nullable=True),
        sa.Column("candidate_type", sa.String(length=64), nullable=False, server_default="learned_exception_price"),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("postal_code", sa.String(length=10), nullable=True),
        sa.Column("postal_prefix", sa.String(length=3), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("province", sa.String(length=10), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=True),
        sa.Column("zone", sa.Integer(), nullable=True),
        sa.Column("billing_pallets", sa.Integer(), nullable=False),
        sa.Column("resolved_total_price_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("resolved_base_price_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_review"),
        sa.Column("duplicate_key", sa.String(length=255), nullable=False),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("risk_tags", sa.JSON(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_rule_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column_name in (
        "source_task_id",
        "quote_id",
        "candidate_type",
        "scope",
        "postal_code",
        "postal_prefix",
        "city",
        "province",
        "origin",
        "zone",
        "billing_pallets",
        "status",
        "duplicate_key",
        "promoted_rule_id",
    ):
        op.create_index(
            f"ix_hermes_learning_candidates_{column_name}",
            "hermes_learning_candidates",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("hermes_learning_candidates")
