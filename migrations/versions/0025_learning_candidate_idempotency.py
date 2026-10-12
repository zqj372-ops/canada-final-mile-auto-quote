"""Protect new learning candidates; retain all legacy evidence unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0025_learning_candidate_idempotency"
down_revision = "0024_add_m2m_quote_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_learning_candidate_v2_key", "hermes_learning_candidates",
                    ["duplicate_key"], unique=True,
                    sqlite_where=sa.text("duplicate_key LIKE 'v2:%'"),
                    postgresql_where=sa.text("duplicate_key LIKE 'v2:%'"))


def downgrade() -> None:
    op.drop_index("uq_learning_candidate_v2_key", table_name="hermes_learning_candidates")
