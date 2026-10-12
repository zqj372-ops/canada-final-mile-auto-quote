"""Add tenant-bound M2M quote records and idempotent operations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_add_m2m_quote_records"
down_revision: str | None = "0023_repair_oversize_snapshot_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    record_columns = [
        sa.Column("record_ref", sa.String(64)), sa.Column("scope_kind", sa.String(16), nullable=False, server_default="legacy"),
        sa.Column("tenant_id", sa.String(128)), sa.Column("application_id", sa.String(128)), sa.Column("service_caller_id", sa.String(128)),
        sa.Column("source_actor_type", sa.String(16)), sa.Column("source_actor_id", sa.String(128)), sa.Column("source_request_id", sa.String(136)),
        sa.Column("preview_id", sa.String(64)), sa.Column("preview_input_hash", sa.String(71)), sa.Column("preview_result_hash", sa.String(71)),
        sa.Column("source_refs_hash", sa.String(71)), sa.Column("source_schema_version", sa.String(64)), sa.Column("record_version", sa.Integer(), nullable=False, server_default="1"),
    ]
    for column in record_columns: op.add_column("sales_quote_records", column)
    for name in ("record_ref", "scope_kind", "tenant_id", "application_id", "source_actor_id"): op.create_index(f"ix_sales_quote_records_{name}", "sales_quote_records", [name], unique=name == "record_ref")
    task_columns = [
        sa.Column("task_ref", sa.String(64)), sa.Column("sales_record_id", sa.Integer(), sa.ForeignKey("sales_quote_records.id")),
        sa.Column("scope_kind", sa.String(16), nullable=False, server_default="legacy"), sa.Column("tenant_id", sa.String(128)), sa.Column("application_id", sa.String(128)),
        sa.Column("created_by_actor_type", sa.String(16)), sa.Column("created_by_actor_id", sa.String(128)), sa.Column("task_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("learning_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
    ]
    for column in task_columns: op.add_column("manual_quote_tasks", column)
    for name in ("task_ref", "sales_record_id", "scope_kind", "tenant_id", "application_id", "created_by_actor_id"): op.create_index(f"ix_manual_quote_tasks_{name}", "manual_quote_tasks", [name], unique=name == "task_ref")
    op.create_table("m2m_quote_operations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("operation_ref", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False), sa.Column("application_id", sa.String(128), nullable=False),
        sa.Column("source_actor_type", sa.String(16), nullable=False), sa.Column("source_actor_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("state", sa.String(32), nullable=False), sa.Column("record_ref", sa.String(64)), sa.Column("task_ref", sa.String(64)), sa.Column("response_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "application_id", "source_actor_type", "source_actor_id", "action", "idempotency_key", name="uq_m2m_quote_operation_idempotency"))
    for name in ("operation_ref", "tenant_id", "application_id", "source_actor_id", "state", "record_ref", "task_ref"): op.create_index(f"ix_m2m_quote_operations_{name}", "m2m_quote_operations", [name], unique=name == "operation_ref")
    op.create_table("m2m_quote_documents",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("document_ref", sa.String(64), nullable=False),
        sa.Column("record_ref", sa.String(64), nullable=False), sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False), sa.Column("application_id", sa.String(128), nullable=False),
        sa.Column("source_actor_type", sa.String(16), nullable=False), sa.Column("source_actor_id", sa.String(128), nullable=False),
        sa.Column("document_kind", sa.String(32), nullable=False), sa.Column("formal", sa.Boolean(), nullable=False),
        sa.Column("watermark", sa.String(128)), sa.Column("media_type", sa.String(64), nullable=False, server_default="application/pdf"),
        sa.Column("content_sha256", sa.String(71), nullable=False), sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False), sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)), sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("source_snapshot_hash", sa.String(71)), sa.Column("terms_hash", sa.String(71)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "application_id", "source_actor_type", "source_actor_id", "record_ref", "record_version", "document_kind", name="uq_m2m_quote_document_snapshot"))
    for name in ("document_ref", "record_ref", "tenant_id", "application_id", "source_actor_id"): op.create_index(f"ix_m2m_quote_documents_{name}", "m2m_quote_documents", [name], unique=name == "document_ref")


def downgrade() -> None:
    op.drop_table("m2m_quote_documents")
    op.drop_table("m2m_quote_operations")
    for name in reversed(("task_ref", "sales_record_id", "scope_kind", "tenant_id", "application_id", "created_by_actor_id")): op.drop_index(f"ix_manual_quote_tasks_{name}", table_name="manual_quote_tasks")
    for name in reversed(("task_ref", "sales_record_id", "scope_kind", "tenant_id", "application_id", "created_by_actor_type", "created_by_actor_id", "task_version", "learning_eligible")): op.drop_column("manual_quote_tasks", name)
    for name in reversed(("record_ref", "scope_kind", "tenant_id", "application_id", "source_actor_id")): op.drop_index(f"ix_sales_quote_records_{name}", table_name="sales_quote_records")
    for name in reversed(("record_ref", "scope_kind", "tenant_id", "application_id", "service_caller_id", "source_actor_type", "source_actor_id", "source_request_id", "preview_id", "preview_input_hash", "preview_result_hash", "source_refs_hash", "source_schema_version", "record_version")): op.drop_column("sales_quote_records", name)
