"""Repair oversize snapshot indexes on databases that applied the original 0022.

The original 0022 (deployed to production before the code was reverted)
created a redundant unique index on (rule_id, version) alongside the unique
constraint, and did not create the status index the model declares.  Newer
0022 revisions already match the model, so this migration is idempotent:
each step checks the live schema before changing it.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0023_repair_oversize_snapshot_indexes"
down_revision: str | None = "0022_add_oversize_pallet_rule_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "oversize_pallet_rule_versions"


def _existing_index_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    existing = _existing_index_names()
    redundant = "ix_oversize_pallet_rule_versions_rule_id_version"
    if redundant in existing:
        # The unique constraint already covers (rule_id, version); the extra
        # unique index only added write amplification.
        op.drop_index(redundant, table_name=TABLE)
    if "ix_oversize_pallet_rule_versions_status" not in existing:
        op.create_index(
            "ix_oversize_pallet_rule_versions_status",
            TABLE,
            ["status"],
        )


def downgrade() -> None:
    existing = _existing_index_names()
    if "ix_oversize_pallet_rule_versions_status" in existing:
        op.drop_index("ix_oversize_pallet_rule_versions_status", table_name=TABLE)
    if "ix_oversize_pallet_rule_versions_rule_id_version" not in existing:
        op.create_index(
            "ix_oversize_pallet_rule_versions_rule_id_version",
            TABLE,
            ["rule_id", "version"],
            unique=True,
        )
