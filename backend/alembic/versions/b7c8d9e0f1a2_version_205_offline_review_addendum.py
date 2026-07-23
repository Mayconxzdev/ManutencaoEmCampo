"""Pending review, correction addendum and team-execution traceability.

Revision ID: b7c8d9e0f1a2
Revises: a7b8c9d0e1f2
Create Date: 2026-07-15
"""
from alembic import op


revision = "b7c8d9e0f1a2"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE maintenance_orders ADD COLUMN performed_by_participants_json TEXT")
    op.execute("ALTER TABLE maintenance_orders ADD COLUMN dossier_folder_name VARCHAR(255)")
    op.execute("ALTER TABLE work_order_corrections ADD COLUMN document_path VARCHAR(500)")
    op.execute("ALTER TABLE work_order_corrections ADD COLUMN document_sha256 VARCHAR(64)")
    op.execute("ALTER TABLE work_order_corrections ADD COLUMN document_revision INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_maintenance_orders_execution_review ON maintenance_orders (execution_status, needs_review, started_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_work_order_corrections_order_revision ON work_order_corrections (order_id, document_revision)")


def downgrade() -> None:
    # SQLite em produção não remove colunas sem recriar tabelas. Preservar os
    # dados auditáveis é mais seguro que uma reversão destrutiva.
    pass
