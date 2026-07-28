"""Quarantine invalid Zone rows and add audit-backed exact rules.

Revision ID: 0020_zone_reference_integrity
Revises: 0019_white_rock_v4b_zone
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0020_zone_reference_integrity"
down_revision: str | None = "0019_white_rock_v4b_zone"
branch_labels: str | None = None
depends_on: str | None = None


ZONE_INTEGRITY_EXPRESSION = """
postal_prefix = upper(postal_prefix)
AND postal_prefix = trim(postal_prefix)
AND city = upper(city)
AND city = trim(city)
AND province = upper(province)
AND province = trim(province)
AND origin = lower(origin)
AND origin = trim(origin)
AND zone > 0
AND
upper(trim(postal_prefix)) ~ '^[ABCEGHJKLMNPRSTVXY][0-9][ABCEGHJKLMNPRSTVWXYZ]$'
AND
CASE upper(trim(postal_prefix))
    WHEN 'X0A' THEN 'NU'
    WHEN 'X0B' THEN 'NU'
    WHEN 'X0C' THEN 'NU'
    WHEN 'X0E' THEN 'NT'
    WHEN 'X0G' THEN 'NT'
    WHEN 'X1A' THEN 'NT'
    ELSE CASE substr(upper(trim(postal_prefix)), 1, 1)
        WHEN 'A' THEN 'NL'
        WHEN 'B' THEN 'NS'
        WHEN 'C' THEN 'PE'
        WHEN 'E' THEN 'NB'
        WHEN 'G' THEN 'QC'
        WHEN 'H' THEN 'QC'
        WHEN 'J' THEN 'QC'
        WHEN 'K' THEN 'ON'
        WHEN 'L' THEN 'ON'
        WHEN 'M' THEN 'ON'
        WHEN 'N' THEN 'ON'
        WHEN 'P' THEN 'ON'
        WHEN 'R' THEN 'MB'
        WHEN 'S' THEN 'SK'
        WHEN 'T' THEN 'AB'
        WHEN 'V' THEN 'BC'
        WHEN 'Y' THEN 'YT'
        ELSE '__INVALID__'
    END
END = upper(trim(province))
AND
CASE upper(trim(province))
    WHEN 'BC' THEN lower(trim(origin)) = 'calgary'
    WHEN 'AB' THEN lower(trim(origin)) = 'calgary'
    WHEN 'SK' THEN lower(trim(origin)) = 'calgary'
    WHEN 'MB' THEN lower(trim(origin)) = 'calgary'
    WHEN 'ON' THEN lower(trim(origin)) = 'toronto'
    WHEN 'QC' THEN lower(trim(origin)) = 'toronto'
    WHEN 'NB' THEN lower(trim(origin)) = 'toronto'
    WHEN 'NS' THEN lower(trim(origin)) = 'toronto'
    WHEN 'PE' THEN lower(trim(origin)) = 'toronto'
    WHEN 'NL' THEN lower(trim(origin)) = 'toronto'
    WHEN 'NT' THEN TRUE
    WHEN 'NU' THEN TRUE
    WHEN 'YT' THEN TRUE
    ELSE FALSE
END
"""

ACTIVE_ZONE_INTEGRITY_CHECK = f"NOT active OR ({ZONE_INTEGRITY_EXPRESSION})"

CONFIRMED_RULES_SQL = """
VALUES
    ('V4C', 'DELTA', 'BC', 'calgary', 5, 'manual_correction',
     '2026-07-28 approved correction: V4C DELTA -> Calgary Zone 5; cross-checked with V4G/V4L successful audits.'),
    ('V4G', 'DELTA', 'BC', 'calgary', 5, 'production_audit_correction',
     '2026-07-28 successful quote audit: V4G DELTA -> Calgary Zone 5.'),
    ('V1X', 'KELOWNA', 'BC', 'calgary', 7, 'production_audit_correction',
     '2026-07-28 successful quote audit: V1X KELOWNA -> Calgary Zone 7.'),
    ('T9K', 'FORT MCMURRAY', 'AB', 'calgary', 5, 'production_audit_correction',
     '2026-07-28 successful quote audit: T9K FORT MCMURRAY -> Calgary Zone 5.'),
    ('R2C', 'WINNIPEG', 'MB', 'calgary', 12, 'production_audit_correction',
     '2026-07-28 successful quote audit: R2C WINNIPEG -> Calgary Zone 12.'),
    ('R2P', 'WINNIPEG', 'MB', 'calgary', 5, 'production_audit_correction',
     '2026-07-28 successful quote audit: R2P WINNIPEG -> Calgary Zone 5.'),
    ('R3T', 'WINNIPEG', 'MB', 'calgary', 5, 'production_audit_correction',
     '2026-07-28 successful quote audit: R3T WINNIPEG -> Calgary Zone 5.'),
    ('N9G', 'WINDSOR', 'ON', 'toronto', 6, 'production_audit_correction',
     '2026-07-28 successful quote audit: N9G WINDSOR -> Toronto Zone 6.')
"""


def upgrade() -> None:
    op.create_table(
        "zone_rule_integrity_0020_backup",
        sa.Column("rule_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("previous_active", sa.Boolean(), nullable=True),
        sa.Column("previous_note", sa.Text(), nullable=True),
        sa.Column("previous_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("inserted_by_migration", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.execute(
        f"""
        INSERT INTO zone_rule_integrity_0020_backup (
            rule_id,
            previous_active,
            previous_note,
            previous_updated_at,
            action,
            inserted_by_migration
        )
        SELECT
            id,
            active,
            note,
            updated_at,
            'integrity_quarantine',
            FALSE
        FROM zone_lookup_rules
        WHERE active = TRUE
          AND NOT ({ZONE_INTEGRITY_EXPRESSION})
        """
    )
    op.execute(
        """
        UPDATE zone_lookup_rules existing
        SET
            active = FALSE,
            note = concat_ws(
                ' | ',
                nullif(existing.note, ''),
                '[0020] Disabled: unrelated province/origin dirty record.'
            ),
            updated_at = NOW()
        FROM zone_rule_integrity_0020_backup backup
        WHERE existing.id = backup.rule_id
          AND backup.action = 'integrity_quarantine'
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY
                        upper(postal_prefix),
                        upper(city),
                        upper(province),
                        lower(origin),
                        zone
                    ORDER BY priority ASC, id ASC
                ) AS row_number
            FROM zone_lookup_rules
            WHERE active = TRUE
        )
        INSERT INTO zone_rule_integrity_0020_backup (
            rule_id,
            previous_active,
            previous_note,
            previous_updated_at,
            action,
            inserted_by_migration
        )
        SELECT
            existing.id,
            existing.active,
            existing.note,
            existing.updated_at,
            'duplicate_quarantine',
            FALSE
        FROM zone_lookup_rules existing
        JOIN ranked ON ranked.id = existing.id
        WHERE ranked.row_number > 1
        ON CONFLICT (rule_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE zone_lookup_rules existing
        SET
            active = FALSE,
            note = concat_ws(
                ' | ',
                nullif(existing.note, ''),
                '[0020] Disabled: duplicate active Zone business key.'
            ),
            updated_at = NOW()
        FROM zone_rule_integrity_0020_backup backup
        WHERE existing.id = backup.rule_id
          AND backup.action = 'duplicate_quarantine'
        """
    )

    op.create_check_constraint(
        "ck_zone_lookup_rules_active_integrity",
        "zone_lookup_rules",
        ACTIVE_ZONE_INTEGRITY_CHECK,
    )
    op.create_index(
        "uq_zone_lookup_rules_active_business_key",
        "zone_lookup_rules",
        [
            sa.text("upper(postal_prefix)"),
            sa.text("upper(city)"),
            sa.text("upper(province)"),
            sa.text("lower(origin)"),
            "zone",
        ],
        unique=True,
        postgresql_where=sa.text("active = TRUE"),
    )

    op.execute(
        f"""
        WITH confirmed(
            postal_prefix, city, province, origin, zone, match_level, note
        ) AS ({CONFIRMED_RULES_SQL})
        INSERT INTO zone_rule_integrity_0020_backup (
            rule_id,
            previous_active,
            previous_note,
            previous_updated_at,
            action,
            inserted_by_migration
        )
        SELECT
            existing.id,
            existing.active,
            existing.note,
            existing.updated_at,
            'conflict_quarantine',
            FALSE
        FROM zone_lookup_rules existing
        JOIN confirmed
          ON existing.postal_prefix = confirmed.postal_prefix
         AND existing.city = confirmed.city
         AND existing.province = confirmed.province
        WHERE existing.active = TRUE
          AND (
              lower(existing.origin) <> confirmed.origin
              OR existing.zone <> confirmed.zone
          )
        ON CONFLICT (rule_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE zone_lookup_rules existing
        SET
            active = FALSE,
            note = concat_ws(
                ' | ',
                nullif(existing.note, ''),
                '[0020] Superseded by confirmed exact rule.'
            ),
            updated_at = NOW()
        FROM zone_rule_integrity_0020_backup backup
        WHERE existing.id = backup.rule_id
          AND backup.action = 'conflict_quarantine'
        """
    )

    op.execute(
        f"""
        WITH confirmed(
            postal_prefix, city, province, origin, zone, match_level, note
        ) AS ({CONFIRMED_RULES_SQL}),
        candidates AS (
            SELECT DISTINCT ON (
                confirmed.postal_prefix,
                confirmed.city,
                confirmed.province,
                confirmed.origin,
                confirmed.zone
            )
                existing.id,
                existing.active,
                existing.note,
                existing.updated_at
            FROM zone_lookup_rules existing
            JOIN confirmed
              ON existing.postal_prefix = confirmed.postal_prefix
             AND existing.city = confirmed.city
             AND existing.province = confirmed.province
             AND lower(existing.origin) = confirmed.origin
             AND existing.zone = confirmed.zone
            WHERE existing.active = FALSE
              AND NOT EXISTS (
                  SELECT 1
                  FROM zone_rule_integrity_0020_backup backup
                  WHERE backup.rule_id = existing.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM zone_lookup_rules active_exact
                  WHERE active_exact.postal_prefix = confirmed.postal_prefix
                    AND active_exact.city = confirmed.city
                    AND active_exact.province = confirmed.province
                    AND lower(active_exact.origin) = confirmed.origin
                    AND active_exact.zone = confirmed.zone
                    AND active_exact.active = TRUE
              )
            ORDER BY
                confirmed.postal_prefix,
                confirmed.city,
                confirmed.province,
                confirmed.origin,
                confirmed.zone,
                existing.priority ASC,
                existing.id ASC
        )
        INSERT INTO zone_rule_integrity_0020_backup (
            rule_id,
            previous_active,
            previous_note,
            previous_updated_at,
            action,
            inserted_by_migration
        )
        SELECT
            candidates.id,
            candidates.active,
            candidates.note,
            candidates.updated_at,
            'exact_reactivated',
            FALSE
        FROM candidates
        ON CONFLICT (rule_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE zone_lookup_rules existing
        SET active = TRUE, updated_at = NOW()
        FROM zone_rule_integrity_0020_backup backup
        WHERE existing.id = backup.rule_id
          AND backup.action = 'exact_reactivated'
        """
    )

    op.execute(
        f"""
        WITH confirmed(
            postal_prefix, city, province, origin, zone, match_level, note
        ) AS ({CONFIRMED_RULES_SQL}),
        inserted AS (
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
                confirmed.postal_prefix,
                confirmed.city,
                confirmed.province,
                confirmed.origin,
                confirmed.zone,
                confirmed.city,
                10,
                TRUE,
                confirmed.match_level,
                confirmed.note,
                NOW(),
                NOW()
            FROM confirmed
            WHERE NOT EXISTS (
                SELECT 1
                FROM zone_lookup_rules existing
                WHERE existing.postal_prefix = confirmed.postal_prefix
                  AND existing.city = confirmed.city
                  AND existing.province = confirmed.province
                  AND lower(existing.origin) = confirmed.origin
                  AND existing.zone = confirmed.zone
                  AND existing.active = TRUE
            )
            RETURNING id
        )
        INSERT INTO zone_rule_integrity_0020_backup (
            rule_id,
            previous_active,
            previous_note,
            previous_updated_at,
            action,
            inserted_by_migration
        )
        SELECT id, NULL, NULL, NULL, 'inserted', TRUE
        FROM inserted
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_zone_lookup_rules_active_business_key",
        table_name="zone_lookup_rules",
    )
    op.drop_constraint(
        "ck_zone_lookup_rules_active_integrity",
        "zone_lookup_rules",
        type_="check",
    )
    op.execute(
        """
        DELETE FROM zone_lookup_rules existing
        USING zone_rule_integrity_0020_backup backup
        WHERE existing.id = backup.rule_id
          AND backup.inserted_by_migration = TRUE
        """
    )
    op.execute(
        """
        UPDATE zone_lookup_rules existing
        SET
            active = backup.previous_active,
            note = backup.previous_note,
            updated_at = backup.previous_updated_at
        FROM zone_rule_integrity_0020_backup backup
        WHERE existing.id = backup.rule_id
          AND backup.inserted_by_migration = FALSE
        """
    )
    op.drop_table("zone_rule_integrity_0020_backup")
