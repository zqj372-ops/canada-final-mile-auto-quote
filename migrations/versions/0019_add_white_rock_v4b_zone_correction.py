"""Add the White Rock V4B Zone correction.

Revision ID: 0019_white_rock_v4b_zone
Revises: 0018_v3j0a7_burnaby_postal
Create Date: 2026-07-27
"""

from __future__ import annotations

from alembic import op


revision: str = "0019_white_rock_v4b_zone"
down_revision: str | None = "0018_v3j0a7_burnaby_postal"
branch_labels: str | None = None
depends_on: str | None = None


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
            'V4B',
            'WHITE ROCK',
            'BC',
            'calgary',
            5,
            'WHITE ROCK',
            10,
            TRUE,
            'manual_correction',
            'White Rock V4B uses Calgary Zone 5; replaces the invalid B4P/BC Toronto Zone 12 legacy anchor.',
            NOW(),
            NOW()
        WHERE NOT EXISTS (
            SELECT 1
            FROM zone_lookup_rules
            WHERE postal_prefix = 'V4B'
              AND city = 'WHITE ROCK'
              AND province = 'BC'
              AND origin = 'calgary'
              AND zone = 5
              AND active = TRUE
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM zone_lookup_rules
        WHERE postal_prefix = 'V4B'
          AND city = 'WHITE ROCK'
          AND province = 'BC'
          AND origin = 'calgary'
          AND zone = 5
          AND match_level = 'manual_correction'
          AND note = 'White Rock V4B uses Calgary Zone 5; replaces the invalid B4P/BC Toronto Zone 12 legacy anchor.'
        """
    )
