"""Add personal, revocable quote skill authorizations without changing existing accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0026_quote_skill_grants"
down_revision = "0025_learning_candidate_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote_skill_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credential_hash", sa.String(64), unique=True),
        sa.Column("credential_expires_at", sa.DateTime(timezone=True)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_quote_skill_grants_user_id", "quote_skill_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_quote_skill_grants_user_id", table_name="quote_skill_grants")
    op.drop_table("quote_skill_grants")
