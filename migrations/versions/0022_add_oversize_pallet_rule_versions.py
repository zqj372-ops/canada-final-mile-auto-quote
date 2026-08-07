"""Add immutable published oversize pallet rule snapshots."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0022_add_oversize_pallet_rule_versions"
down_revision: str | None = "0021_fcl_quote_closed_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# This is an immutable migration snapshot.  It deliberately does not import
# the application's current default so a later code change cannot rewrite the
# historical row when an old database is upgraded.
_INITIAL_CONFIG_JSON = (
    '{"rule_id":"NA_OVERSIZE_TEMP_V1","standard_pallet_length_cm":"121.92","standard_pallet_width_cm":"101.60","standard_pallet_area_cm2":"12387.072","mild_oversize_length_cm":"135","mild_oversize_width_cm":"110","expansion_trigger_length_cm":"150","expansion_trigger_width_cm":"122","expansion_grace_cm":"5","area_tolerance_ratio":"0.02","weight_basis_kg":"500","normal_board_height_cm":"180","high_board_height_cm":"210","unit_auto_weight_max_kg":"1000","footprint_surcharge":"25","medium_oversize_surcharge":"50","high_board_surcharge":"50","heavy_surcharge":"75","customer_piece_tolerance_absolute":2,"customer_piece_tolerance_ratio":"0.05","weight_tolerance_absolute_kg":"50","weight_tolerance_ratio":"0.05","volume_tolerance_absolute_cbm":"0.5","volume_tolerance_ratio":"0.10","max_auto_vehicles":3,"packing_node_limit":10000,"vehicle_profiles":[{"code":"26_non_cdl","label":"26尺非CDL","length_cm":"762","width_cm":"243.84","height_cm":"243.84","volume_cbm":"45.3","payload_kg":"4536","common_pallet_limit":12,"tight_pallet_limit":14,"comparable_base_price":null},{"code":"26_cdl","label":"26尺CDL","length_cm":"762","width_cm":"243.84","height_cm":"243.84","volume_cbm":"45.3","payload_kg":"7711","common_pallet_limit":12,"tight_pallet_limit":14,"comparable_base_price":null},{"code":"53_dry_van","label":"53尺干货车","length_cm":"1600.2","width_cm":"250.19","height_cm":"279.4","volume_cbm":"110.4","payload_kg":"19958","common_pallet_limit":26,"tight_pallet_limit":30,"comparable_base_price":null}]}'
)


def upgrade() -> None:
    op.create_table(
        "oversize_pallet_rule_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("published_by", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="published"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "rule_id",
            "version",
            name="uq_oversize_pallet_rule_versions_rule_version",
        ),
        sa.CheckConstraint(
            "status = 'published'",
            name="ck_oversize_pallet_rule_versions_published_status",
        ),
        sa.CheckConstraint(
            "config_json IS NOT NULL",
            name="ck_oversize_pallet_rule_versions_config_not_null",
        ),
        sa.CheckConstraint(
            "length(CAST(config_json AS TEXT)) > 2 AND CAST(config_json AS TEXT) <> 'null'",
            name="ck_oversize_pallet_rule_versions_config_not_empty",
        ),
    )
    op.create_index(
        "ix_oversize_pallet_rule_versions_rule_id",
        "oversize_pallet_rule_versions",
        ["rule_id"],
    )
    op.create_index(
        "ix_oversize_pallet_rule_versions_version",
        "oversize_pallet_rule_versions",
        ["version"],
    )
    op.create_index(
        "ix_oversize_pallet_rule_versions_status",
        "oversize_pallet_rule_versions",
        ["status"],
    )

    config_json = _INITIAL_CONFIG_JSON
    if op.get_bind().dialect.name == "postgresql":
        # PostgreSQL does not implicitly cast a TEXT bind parameter to JSON;
        # keep the explicit cast while retaining offline SQL generation.
        op.execute(
            sa.text(
                "INSERT INTO oversize_pallet_rule_versions "
                "(rule_id, version, config_json, published_by, status) "
                "VALUES (:rule_id, :version, CAST(:config_json AS JSON), :published_by, :status)"
            ).bindparams(
                sa.bindparam("rule_id", "NA_OVERSIZE_TEMP_V1", type_=sa.String(length=128)),
                sa.bindparam("version", 1, type_=sa.Integer()),
                sa.bindparam("config_json", config_json, type_=sa.Text()),
                sa.bindparam("published_by", "migration:0022", type_=sa.String(length=128)),
                sa.bindparam("status", "published", type_=sa.String(length=32)),
            )
        )
    else:
        # Text lets Alembic render the deterministic JSON literal in offline
        # SQL mode; the target column remains JSON in the created table.
        snapshot_table = sa.table(
            "oversize_pallet_rule_versions",
            sa.column("rule_id", sa.String(length=128)),
            sa.column("version", sa.Integer()),
            sa.column("config_json", sa.Text()),
            sa.column("published_by", sa.String(length=128)),
            sa.column("status", sa.String(length=32)),
        )
        op.bulk_insert(
            snapshot_table,
            [
                {
                    "rule_id": "NA_OVERSIZE_TEMP_V1",
                    "version": 1,
                    "config_json": config_json,
                    "published_by": "migration:0022",
                    "status": "published",
                }
            ],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_oversize_pallet_rule_versions_status",
        table_name="oversize_pallet_rule_versions",
    )
    op.drop_index(
        "ix_oversize_pallet_rule_versions_version",
        table_name="oversize_pallet_rule_versions",
    )
    op.drop_index(
        "ix_oversize_pallet_rule_versions_rule_id",
        table_name="oversize_pallet_rule_versions",
    )
    op.drop_table("oversize_pallet_rule_versions")
