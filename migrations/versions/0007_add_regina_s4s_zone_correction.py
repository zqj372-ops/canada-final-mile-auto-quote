"""Add Regina S4S zone correction.

Revision ID: 0007_regina_s4s_zone_correction
Revises: 0006_wecom_aibot_credentials
Create Date: 2026-07-07
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0007_regina_s4s_zone_correction"
down_revision: str | None = "0006_wecom_aibot_credentials"
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
            'S4S',
            'REGINA',
            'SK',
            'calgary',
            5,
            'REGINA',
            10,
            TRUE,
            'manual_correction',
            'Regina S4S uses Calgary Zone 5; prevents fallback to S4M Zone 14.',
            NOW(),
            NOW()
        WHERE NOT EXISTS (
            SELECT 1
            FROM zone_lookup_rules
            WHERE postal_prefix = 'S4S'
              AND city = 'REGINA'
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
        WHERE postal_prefix = 'S4S'
          AND city = 'REGINA'
          AND province = 'SK'
          AND origin = 'calgary'
          AND zone = 5
          AND match_level = 'manual_correction'
        """
    )
