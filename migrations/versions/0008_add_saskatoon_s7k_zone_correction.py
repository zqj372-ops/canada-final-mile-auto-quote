"""Add Saskatoon S7K zone correction.

Revision ID: 0008_saskatoon_s7k_fix
Revises: 0007_regina_s4s_zone_correction
Create Date: 2026-07-07
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0008_saskatoon_s7k_fix"
down_revision: str | None = "0007_regina_s4s_zone_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
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
            'S7K',
            'SASKATOON',
            'SK',
            'calgary',
            5,
            'SASKATOON',
            10,
            TRUE,
            'manual_correction',
            'Saskatoon S7K uses Calgary Zone 5; prevents fallback to stale S7H Toronto Zone 14.',
            NOW(),
            NOW()
        WHERE NOT EXISTS (
            SELECT 1
            FROM zone_lookup_rules
            WHERE postal_prefix = 'S7K'
              AND city = 'SASKATOON'
              AND province = 'SK'
              AND origin = 'calgary'
              AND zone = 5
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM zone_lookup_rules
        WHERE postal_prefix = 'S7K'
          AND city = 'SASKATOON'
          AND province = 'SK'
          AND origin = 'calgary'
          AND zone = 5
          AND match_level = 'manual_correction'
        """
    )
