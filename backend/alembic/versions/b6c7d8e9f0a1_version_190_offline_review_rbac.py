"""version 1.9.0 offline review rbac

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _cols(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _add_missing_columns(bind, table: str, columns: list[sa.Column]) -> None:
    existing = _cols(bind, table)
    missing = [c for c in columns if c.name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table) as batch_op:
        for column in missing:
            batch_op.add_column(column)


def upgrade() -> None:
    bind = op.get_bind()

    if "operators" in _tables(bind):
        _add_missing_columns(bind, "operators", [
            sa.Column("role", sa.String(length=30), nullable=True, server_default="operator"),
            sa.Column("pin_hash", sa.String(length=255), nullable=True),
        ])
        try:
            op.create_index("ix_operators_role", "operators", ["role"], unique=False)
        except Exception:
            pass
        op.execute("UPDATE operators SET role = 'operator' WHERE role IS NULL OR trim(role) = ''")

    if "audit_logs" in _tables(bind):
        _add_missing_columns(bind, "audit_logs", [
            sa.Column("request_id", sa.String(length=100), nullable=True),
            sa.Column("route", sa.String(length=255), nullable=True),
            sa.Column("method", sa.String(length=12), nullable=True),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("client_host", sa.String(length=100), nullable=True),
            sa.Column("app_version", sa.String(length=30), nullable=True),
        ])

    if "offline_sync_operations" not in _tables(bind):
        op.create_table(
            "offline_sync_operations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("client_op_id", sa.String(length=120), nullable=False),
            sa.Column("operation_type", sa.String(length=50), nullable=False),
            sa.Column("order_id", sa.String(length=36), nullable=True),
            sa.Column("entity_name", sa.String(length=80), nullable=True),
            sa.Column("entity_id", sa.String(length=80), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("response_json", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("operator_name", sa.String(length=100), nullable=True),
            sa.Column("selected_user_id", sa.String(length=36), nullable=True),
            sa.Column("device_id", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["order_id"], ["maintenance_orders.id"]),
            sa.ForeignKeyConstraint(["selected_user_id"], ["operators.id"]),
            sa.UniqueConstraint("client_op_id", name="uq_offline_sync_operations_client_op_id"),
        )
        op.create_index("ix_offline_sync_operations_client_op_id", "offline_sync_operations", ["client_op_id"])
        op.create_index("ix_offline_sync_operations_status", "offline_sync_operations", ["status"])
        op.create_index("ix_offline_sync_operations_operation_type", "offline_sync_operations", ["operation_type"])
        op.create_index("ix_offline_sync_operations_order_id", "offline_sync_operations", ["order_id"])
        op.create_index("ix_offline_sync_operations_device_id", "offline_sync_operations", ["device_id"])

    if "document_ocr_jobs" not in _tables(bind):
        op.create_table(
            "document_ocr_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("source_kind", sa.String(length=40), nullable=False),
            sa.Column("source_id", sa.String(length=36), nullable=True),
            sa.Column("file_path", sa.String(length=1000), nullable=False),
            sa.Column("file_hash", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("method", sa.String(length=50), nullable=True),
            sa.Column("extracted_text", sa.Text(), nullable=True),
            sa.Column("needs_review", sa.Boolean(), nullable=True, server_default="1"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_document_ocr_jobs_source_kind", "document_ocr_jobs", ["source_kind"])
        op.create_index("ix_document_ocr_jobs_source_id", "document_ocr_jobs", ["source_id"])
        op.create_index("ix_document_ocr_jobs_status", "document_ocr_jobs", ["status"])
        op.create_index("ix_document_ocr_jobs_file_hash", "document_ocr_jobs", ["file_hash"])

    if "system_backup_runs" not in _tables(bind):
        op.create_table(
            "system_backup_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("database_path", sa.String(length=1000), nullable=True),
            sa.Column("backup_path", sa.String(length=1000), nullable=True),
            sa.Column("backup_sha256", sa.String(length=64), nullable=True),
            sa.Column("restore_test_ok", sa.Boolean(), nullable=True, server_default="0"),
            sa.Column("report_json", sa.Text(), nullable=True),
            sa.Column("executed_by", sa.String(length=100), nullable=True),
        )
        op.create_index("ix_system_backup_runs_created_at", "system_backup_runs", ["created_at"])
        op.create_index("ix_system_backup_runs_status", "system_backup_runs", ["status"])

    if "semantic_document_chunks" not in _tables(bind):
        op.create_table(
            "semantic_document_chunks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("source_kind", sa.String(length=40), nullable=False),
            sa.Column("source_id", sa.String(length=36), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("text_hash", sa.String(length=64), nullable=False),
            sa.Column("vector_json", sa.Text(), nullable=True),
            sa.Column("embedding_model", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source_kind", "source_id", "chunk_index", name="uq_semantic_document_chunks_source_chunk"),
        )
        op.create_index("ix_semantic_document_chunks_source_kind", "semantic_document_chunks", ["source_kind"])
        op.create_index("ix_semantic_document_chunks_source_id", "semantic_document_chunks", ["source_id"])
        op.create_index("ix_semantic_document_chunks_text_hash", "semantic_document_chunks", ["text_hash"])

    try:
        op.execute("insert or replace into quality_config(key, value, updated_at) values ('version', '1.9.0', datetime('now'))")
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    for index_name, table_name in [
        ("ix_semantic_document_chunks_text_hash", "semantic_document_chunks"),
        ("ix_semantic_document_chunks_source_id", "semantic_document_chunks"),
        ("ix_semantic_document_chunks_source_kind", "semantic_document_chunks"),
        ("ix_system_backup_runs_status", "system_backup_runs"),
        ("ix_system_backup_runs_created_at", "system_backup_runs"),
        ("ix_document_ocr_jobs_file_hash", "document_ocr_jobs"),
        ("ix_document_ocr_jobs_status", "document_ocr_jobs"),
        ("ix_document_ocr_jobs_source_id", "document_ocr_jobs"),
        ("ix_document_ocr_jobs_source_kind", "document_ocr_jobs"),
        ("ix_offline_sync_operations_device_id", "offline_sync_operations"),
        ("ix_offline_sync_operations_order_id", "offline_sync_operations"),
        ("ix_offline_sync_operations_operation_type", "offline_sync_operations"),
        ("ix_offline_sync_operations_status", "offline_sync_operations"),
        ("ix_offline_sync_operations_client_op_id", "offline_sync_operations"),
    ]:
        try:
            op.drop_index(index_name, table_name=table_name)
        except Exception:
            pass
    for table in ["semantic_document_chunks", "system_backup_runs", "document_ocr_jobs", "offline_sync_operations"]:
        try:
            op.drop_table(table)
        except Exception:
            pass
    try:
        op.drop_index("ix_operators_role", table_name="operators")
    except Exception:
        pass
    try:
        op.execute("update quality_config set value = '1.8.0', updated_at = datetime('now') where key = 'version'")
    except Exception:
        pass
