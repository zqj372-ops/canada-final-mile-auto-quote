"""Add Edmonton AB zone corrections.

Revision ID: 0010_edmonton_zone9
Revises: 0009_widen_alembic_version
Create Date: 2026-07-07
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0010_edmonton_zone9"
down_revision: str | None = "0009_widen_alembic_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EDMONTON_FSAS = (
    "T5A",
    "T5B",
    "T5C",
    "T5E",
    "T5G",
    "T5H",
    "T5J",
    "T5K",
    "T5L",
    "T5M",
    "T5N",
    "T5P",
    "T5R",
    "T5S",
    "T5T",
    "T5V",
    "T5W",
    "T5X",
    "T5Y",
    "T5Z",
    "T6A",
    "T6B",
    "T6C",
    "T6E",
    "T6G",
    "T6H",
    "T6J",
    "T6K",
    "T6L",
    "T6M",
    "T6N",
    "T6P",
    "T6R",
    "T6S",
    "T6T",
    "T6V",
    "T6W",
    "T6X",
    "T6Y",
)


def upgrade() -> None:
    values = ", ".join(f"('{fsa}')" for fsa in EDMONTON_FSAS)
    op.execute(
        f"""
        INSERT INTO zone_lookup_rules (
            postal_prefix,
            city,
            province,
            origin,
            zone,
            canonical_city,
            priority,
            active,
            match_level,
            note,
            created_at,
            updated_at
        )
        SELECT
            fsa.postal_prefix,
            'EDMONTON',
            'AB',
            'calgary',
            9,
            'EDMONTON',
            10,
            TRUE,
            'manual_correction',
            'Edmonton AB city FSA correction uses Calgary Zone 9; prevents missing T6/T5 anchors.',
            NOW(),
            NOW()
        FROM (VALUES {values}) AS fsa(postal_prefix)
        WHERE NOT EXISTS (
            SELECT 1
            FROM zone_lookup_rules existing
            WHERE existing.postal_prefix = fsa.postal_prefix
              AND existing.city = 'EDMONTON'
              AND existing.province = 'AB'
              AND existing.origin = 'calgary'
              AND existing.zone = 9
        )
        """
    )


def downgrade() -> None:
    values = ", ".join(f"'{fsa}'" for fsa in EDMONTON_FSAS)
    op.execute(
        f"""
        DELETE FROM zone_lookup_rules
        WHERE postal_prefix IN ({values})
          AND city = 'EDMONTON'
          AND province = 'AB'
          AND origin = 'calgary'
          AND zone = 9
          AND match_level = 'manual_correction'
        """
    )
