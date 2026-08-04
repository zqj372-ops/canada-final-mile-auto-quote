"""Add the name-only customer directory and nullable quote link."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0023_customers"
down_revision: str | None = "0022_quote_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customers_name", "customers", ["name"])
    op.create_index("ix_customers_normalized_name", "customers", ["normalized_name"])
    op.create_index("ix_customers_created_by_user_id", "customers", ["created_by_user_id"])
    op.add_column("sales_quote_records", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_sales_quote_records_customer_id", "sales_quote_records", "customers", ["customer_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_sales_quote_records_customer_id", "sales_quote_records", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_sales_quote_records_customer_id", table_name="sales_quote_records")
    op.drop_constraint("fk_sales_quote_records_customer_id", "sales_quote_records", type_="foreignkey")
    op.drop_column("sales_quote_records", "customer_id")
    op.drop_index("ix_customers_created_by_user_id", table_name="customers")
    op.drop_index("ix_customers_normalized_name", table_name="customers")
    op.drop_index("ix_customers_name", table_name="customers")
    op.drop_table("customers")
