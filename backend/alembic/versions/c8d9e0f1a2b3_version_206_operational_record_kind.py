"""separate operational records from demos and abandoned tests

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-15
"""
from alembic import op


def _columns() -> set[str]:
    return {row[1] for row in op.get_bind().exec_driver_sql("PRAGMA table_info(maintenance_orders)").fetchall()}


revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite não permite adicionar uma coluna NOT NULL sem default de maneira
    # segura; o default preserva todos os registros anteriores como oficiais
    # até que uma pessoa os classifique conscientemente como teste.
    columns = _columns()
    if "record_kind" not in columns:
        op.execute("ALTER TABLE maintenance_orders ADD COLUMN record_kind VARCHAR(30) NOT NULL DEFAULT 'official'")
    if "record_kind_reason" not in columns:
        op.execute("ALTER TABLE maintenance_orders ADD COLUMN record_kind_reason TEXT")
    if "record_kind_classified_at" not in columns:
        op.execute("ALTER TABLE maintenance_orders ADD COLUMN record_kind_classified_at DATETIME")
    if "record_kind_classified_by" not in columns:
        op.execute("ALTER TABLE maintenance_orders ADD COLUMN record_kind_classified_by VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_maintenance_orders_record_kind_status ON maintenance_orders (record_kind, execution_status, completed_at)")


def downgrade() -> None:
    # Não remover colunas em SQLite: preservar a classificação é mais seguro
    # que uma reconstrução destrutiva da tabela de rastreabilidade.
    op.execute("DROP INDEX IF EXISTS ix_maintenance_orders_record_kind_status")
