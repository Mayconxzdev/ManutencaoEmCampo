"""separate checklist reviewer from maintenance executor and final PDF hash

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-15
"""
from alembic import op


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Listas de seleção simples: não são RBAC e não removem pessoas/histórico.
    op.execute("ALTER TABLE operators ADD COLUMN can_record_checklist BOOLEAN NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE operators ADD COLUMN can_execute_maintenance BOOLEAN NOT NULL DEFAULT 1")
    op.execute("CREATE INDEX IF NOT EXISTS ix_operators_can_record_checklist ON operators (can_record_checklist)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_operators_can_execute_maintenance ON operators (can_execute_maintenance)")

    # Só Camila e Rafael aparecem inicialmente no tablet; todos os nomes
    # ativos continuam disponíveis como executantes até ajuste na Gestão.
    op.execute("""
        UPDATE operators
        SET can_record_checklist = CASE
            WHEN lower(trim(name)) IN ('camila duarte', 'rafael moreira') THEN 1
            ELSE 0
        END,
        can_execute_maintenance = CASE
            WHEN lower(trim(name)) IN ('camila duarte', 'rafael moreira') THEN 0
            ELSE 1
        END
        WHERE COALESCE(is_active, 1) = 1
    """)

    # Mantém operator_name para compatibilidade e acrescenta o executor físico
    # como dado próprio, sem adivinhar informações em OMs antigas.
    op.execute("ALTER TABLE maintenance_orders ADD COLUMN performed_by_name VARCHAR(100)")
    op.execute("ALTER TABLE maintenance_orders ADD COLUMN performed_by_operator_id VARCHAR(36)")
    op.execute("ALTER TABLE maintenance_orders ADD COLUMN performed_by_snapshot VARCHAR(100)")
    op.execute("ALTER TABLE maintenance_orders ADD COLUMN final_pdf_sha256 VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_maintenance_orders_performed_by_operator_id ON maintenance_orders (performed_by_operator_id)")


def downgrade() -> None:
    # SQLite não remove colunas com segurança em produção. A reversão lógica
    # preserva rastreabilidade e apenas desativa as classificações adicionadas.
    op.execute("UPDATE operators SET can_record_checklist = 0, can_execute_maintenance = 1")
