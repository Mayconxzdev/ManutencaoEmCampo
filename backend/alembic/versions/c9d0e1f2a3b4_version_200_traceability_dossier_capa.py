"""version 2.0.0 traceability dossier and capa

Revision ID: c9d0e1f2a3b4
Revises: b6c7d8e9f0a1
Create Date: 2026-07-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _add_columns(bind, table: str, columns: list[sa.Column]) -> None:
    present = _columns(bind, table)
    missing = [column for column in columns if column.name not in present]
    if not missing:
        return
    with op.batch_alter_table(table) as batch:
        for column in missing:
            batch.add_column(column)


def _index(name: str, table: str, columns: list[str]) -> None:
    try:
        op.create_index(name, table, columns, unique=False)
    except Exception:
        pass


def upgrade() -> None:
    bind = op.get_bind()
    if "maintenance_evidences" in _tables(bind):
        _add_columns(bind, "maintenance_evidences", [
            sa.Column("uploader_name", sa.String(length=100), nullable=True),
            sa.Column("uploader_operator_id", sa.String(length=36), nullable=True),
            sa.Column("device_id", sa.String(length=100), nullable=True),
            sa.Column("captured_at", sa.DateTime(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=True),
            sa.Column("source", sa.String(length=30), nullable=True, server_default="web"),
            sa.Column("original_filename", sa.String(length=255), nullable=True),
            sa.Column("mime_type", sa.String(length=120), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("dossier_status", sa.String(length=30), nullable=True, server_default="pending"),
            sa.Column("dossier_path", sa.String(length=1000), nullable=True),
            sa.Column("dossier_synced_at", sa.DateTime(), nullable=True),
        ])
        _index("ix_maintenance_evidences_dossier_status", "maintenance_evidences", ["dossier_status"])
        # Dados anteriores permanecem íntegros e são identificados como legado,
        # sem forjar uma autoria que não foi registrada na época.
        op.execute("UPDATE maintenance_evidences SET received_at = uploaded_at WHERE received_at IS NULL")
        op.execute("UPDATE maintenance_evidences SET source = 'legacy' WHERE source IS NULL OR trim(source) = ''")
        op.execute("UPDATE maintenance_evidences SET dossier_status = 'pending' WHERE dossier_status IS NULL OR trim(dossier_status) = ''")

    if "quality_nonconformities" not in _tables(bind):
        op.create_table(
            "quality_nonconformities",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("code", sa.String(length=40), nullable=False, unique=True),
            sa.Column("asset_id", sa.String(length=36), nullable=True),
            sa.Column("order_id", sa.String(length=36), nullable=True),
            sa.Column("issue_id", sa.String(length=36), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("requirement_reference", sa.String(length=500), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
            sa.Column("detected_at", sa.DateTime(), nullable=False),
            sa.Column("detected_by_name", sa.String(length=100), nullable=True),
            sa.Column("detected_by_operator_id", sa.String(length=36), nullable=True),
            sa.Column("device_id", sa.String(length=100), nullable=True),
            sa.Column("containment_action", sa.Text(), nullable=True),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column("corrective_action", sa.Text(), nullable=True),
            sa.Column("action_owner_name", sa.String(length=100), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("effectiveness_review", sa.Text(), nullable=True),
            sa.Column("effectiveness_verified_at", sa.DateTime(), nullable=True),
            sa.Column("effectiveness_verified_by", sa.String(length=100), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("closed_by", sa.String(length=100), nullable=True),
            sa.Column("reopened_at", sa.DateTime(), nullable=True),
            sa.Column("reopen_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
            sa.ForeignKeyConstraint(["order_id"], ["maintenance_orders.id"]),
            sa.ForeignKeyConstraint(["issue_id"], ["maintenance_issues.id"]),
            sa.ForeignKeyConstraint(["detected_by_operator_id"], ["operators.id"]),
        )
    for name, columns in [
        ("ix_quality_nonconformities_code", ["code"]),
        ("ix_quality_nonconformities_asset_id", ["asset_id"]),
        ("ix_quality_nonconformities_order_id", ["order_id"]),
        ("ix_quality_nonconformities_issue_id", ["issue_id"]),
        ("ix_quality_nonconformities_status", ["status"]),
    ]:
        _index(name, "quality_nonconformities", columns)

    if "dossier_sync_jobs" not in _tables(bind):
        op.create_table(
            "dossier_sync_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("order_id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_at", sa.DateTime(), nullable=False),
            sa.Column("requested_by", sa.String(length=100), nullable=True),
            sa.Column("requested_by_operator_id", sa.String(length=36), nullable=True),
            sa.Column("device_id", sa.String(length=100), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("target_path", sa.String(length=1000), nullable=True),
            sa.Column("manifest_hash", sa.String(length=64), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["order_id"], ["maintenance_orders.id"]),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
            sa.ForeignKeyConstraint(["requested_by_operator_id"], ["operators.id"]),
        )
    for name, columns in [
        ("ix_dossier_sync_jobs_order_id", ["order_id"]),
        ("ix_dossier_sync_jobs_asset_id", ["asset_id"]),
        ("ix_dossier_sync_jobs_status", ["status"]),
    ]:
        _index(name, "dossier_sync_jobs", columns)


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("ix_dossier_sync_jobs_status", "ix_dossier_sync_jobs_asset_id", "ix_dossier_sync_jobs_order_id"):
        try:
            op.drop_index(name, table_name="dossier_sync_jobs")
        except Exception:
            pass
    if "dossier_sync_jobs" in _tables(bind):
        op.drop_table("dossier_sync_jobs")
    for name in ("ix_quality_nonconformities_status", "ix_quality_nonconformities_issue_id", "ix_quality_nonconformities_order_id", "ix_quality_nonconformities_asset_id", "ix_quality_nonconformities_code"):
        try:
            op.drop_index(name, table_name="quality_nonconformities")
        except Exception:
            pass
    if "quality_nonconformities" in _tables(bind):
        op.drop_table("quality_nonconformities")
    # A remoção das colunas não é feita no downgrade: apagar metadados de
    # rastreabilidade ao voltar de versão seria uma operação destrutiva.
