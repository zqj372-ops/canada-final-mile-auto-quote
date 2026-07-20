"""Add the missing V3J 0A7 Burnaby postal lookup.

Revision ID: 0018_v3j0a7_burnaby_postal
Revises: 0017_v3x0l7_surrey_postal
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op


revision: str = "0018_v3j0a7_burnaby_postal"
down_revision: str | None = "0017_v3x0l7_surrey_postal"
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
            'V3J 0A7',
            'Burnaby',
            'BC',
            'V3J',
            'Burnaby',
            'manual_postal_correction_20260720'
        )
        ON CONFLICT (postal_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM postal_code_city_lookup
        WHERE postal_code = 'V3J 0A7'
          AND source = 'manual_postal_correction_20260720'
        """
    )
