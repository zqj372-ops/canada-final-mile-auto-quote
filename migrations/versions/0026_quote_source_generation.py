"""Bind quote release manifests to a database-maintained source generation."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0026_quote_source_generation"
down_revision: str | None = "0025_add_quote_release_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_TABLES = (
    "postal_code_city_lookup",
    "postal_zone_overrides",
    "city_aliases",
    "zone_lookup_rules",
    "zone_price_matrix",
    "quote_rule_config",
)


def upgrade() -> None:
    op.create_table(
        "quote_source_generation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(sa.text("INSERT INTO quote_source_generation (id, generation) VALUES (1, 0)"))
    op.add_column(
        "quote_release_manifest",
        sa.Column("source_generation", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute(sa.text("UPDATE quote_release_manifest SET active = FALSE WHERE active = TRUE"))
    if op.get_bind().dialect.name == "postgresql":
        _create_postgresql_triggers()
    elif op.get_bind().dialect.name == "sqlite":
        _create_sqlite_triggers()
    else:
        raise RuntimeError("quote source generation supports PostgreSQL and SQLite only")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in SOURCE_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS quote_source_generation_{table} ON {table}"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS quote_source_generation_bump()"))
    elif dialect == "sqlite":
        for table in SOURCE_TABLES:
            for operation in ("insert", "update", "delete"):
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS quote_source_generation_{table}_{operation}"))
    op.drop_column("quote_release_manifest", "source_generation")
    op.drop_table("quote_source_generation")


def _create_postgresql_triggers() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION quote_source_generation_bump()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                UPDATE quote_source_generation
                SET generation = generation + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1;
                RETURN NULL;
            END;
            $$
            """
        )
    )
    for table in SOURCE_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER quote_source_generation_{table}
                AFTER INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION quote_source_generation_bump()
                """
            )
        )


def _create_sqlite_triggers() -> None:
    for table in SOURCE_TABLES:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER quote_source_generation_{table}_{operation.lower()}
                    AFTER {operation} ON {table}
                    BEGIN
                        UPDATE quote_source_generation
                        SET generation = generation + 1, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1;
                    END
                    """
                )
            )
