from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


SOURCE_TABLES = (
    "postal_code_city_lookup",
    "postal_zone_overrides",
    "city_aliases",
    "zone_lookup_rules",
    "zone_price_matrix",
    "quote_rule_config",
)


def ensure_source_generation_row(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text(
                "INSERT INTO quote_source_generation (id, generation) VALUES (1, 0) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
    elif connection.dialect.name == "sqlite":
        connection.execute(
            text("INSERT OR IGNORE INTO quote_source_generation (id, generation) VALUES (1, 0)")
        )
    else:
        raise RuntimeError("quote source generation supports PostgreSQL and SQLite only")


def install_source_generation_triggers(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text(
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
            connection.execute(
                text(
                    f"CREATE TRIGGER quote_source_generation_{table} "
                    f"AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH STATEMENT "
                    "EXECUTE FUNCTION quote_source_generation_bump()"
                )
            )
    elif connection.dialect.name == "sqlite":
        for table in SOURCE_TABLES:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                connection.execute(
                    text(
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
    else:
        raise RuntimeError("quote source generation supports PostgreSQL and SQLite only")
