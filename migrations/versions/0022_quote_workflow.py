"""Add the sales quote workflow aggregate and manual resolution contract."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0022_quote_workflow"
down_revision: str | None = "0021_fcl_quote_closed_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, column in (
        ("workflow_status", sa.Column("workflow_status", sa.String(32), nullable=False, server_default="pending_review")),
        ("revision", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")),
        ("valid_until", sa.Column("valid_until", sa.Date(), nullable=True)),
        ("sent_at", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True)),
        ("closed_at", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_action_by", sa.Column("last_action_by", sa.String(128), nullable=True)),
        ("last_action_role", sa.Column("last_action_role", sa.String(32), nullable=True)),
        ("sent_snapshot_json", sa.Column("sent_snapshot_json", sa.JSON(), nullable=True)),
    ):
        op.add_column("sales_quote_records", column)
    op.create_index("ix_sales_quote_records_workflow_status", "sales_quote_records", ["workflow_status"])
    op.add_column("manual_quote_tasks", sa.Column("sales_quote_record_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_manual_quote_tasks_sales_record", "manual_quote_tasks", "sales_quote_records", ["sales_quote_record_id"], ["id"], ondelete="SET NULL")
    for name, column in (
        ("fee_items", sa.Column("fee_items", sa.JSON(), nullable=True)),
        ("totals_by_currency", sa.Column("totals_by_currency", sa.JSON(), nullable=True)),
        ("settlement_currency", sa.Column("settlement_currency", sa.String(8), nullable=True)),
        ("converted_total", sa.Column("converted_total", sa.Numeric(18, 4), nullable=True)),
        ("valid_until", sa.Column("valid_until", sa.Date(), nullable=True)),
        ("public_note", sa.Column("public_note", sa.Text(), nullable=True)),
        ("customer_terms", sa.Column("customer_terms", sa.JSON(), nullable=True)),
        ("customer_reply", sa.Column("customer_reply", sa.Text(), nullable=True)),
        ("internal_note", sa.Column("internal_note", sa.Text(), nullable=True)),
    ):
        op.add_column("manual_quote_tasks", column)
    op.create_table(
        "quote_workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("sales_quote_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(128), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("public_note", sa.Text(), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quote_workflow_events_record_id", "quote_workflow_events", ["record_id"])
    op.create_index("ix_quote_workflow_events_event_type", "quote_workflow_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_quote_workflow_events_event_type", table_name="quote_workflow_events")
    op.drop_index("ix_quote_workflow_events_record_id", table_name="quote_workflow_events")
    op.drop_table("quote_workflow_events")
    for name in ("internal_note", "customer_reply", "customer_terms", "public_note", "valid_until", "converted_total", "settlement_currency", "totals_by_currency", "fee_items"):
        op.drop_column("manual_quote_tasks", name)
    op.drop_constraint("fk_manual_quote_tasks_sales_record", "manual_quote_tasks", type_="foreignkey")
    op.drop_column("manual_quote_tasks", "sales_quote_record_id")
    op.drop_index("ix_sales_quote_records_workflow_status", table_name="sales_quote_records")
    for name in ("sent_snapshot_json", "last_action_role", "last_action_by", "closed_at", "sent_at", "valid_until", "revision", "workflow_status"):
        op.drop_column("sales_quote_records", name)
