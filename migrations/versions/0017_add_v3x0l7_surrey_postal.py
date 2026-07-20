"""Add the missing V3X 0L7 Surrey postal lookup.

Revision ID: 0017_v3x0l7_surrey_postal
Revises: 0016_learned_rule_conditions
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op


revision: str = "0017_v3x0l7_surrey_postal"
down_revision: str | None = "0016_learned_rule_conditions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO postal_code_city_lookup (
            postal_code,
            preferred_city,
            province,
            fsa,
            official_city,
            source
        )
        VALUES (
            'V3X 0L7',
            'Surrey',
            'BC',
            'V3X',
            'Surrey',
            'manual_postal_correction_20260720'
        )
        ON CONFLICT (postal_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM postal_code_city_lookup
        WHERE postal_code = 'V3X 0L7'
          AND source = 'manual_postal_correction_20260720'
        """
    )
