"""Alembic migration: 1.3.0 - Execution status, needs_review, legacy history, planning automation"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers
revision = 'e1f2g3h4i5j6_version_130'
down_revision = 'd3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def table_exists(table_name: str) -> bool:
        return table_name in inspector.get_table_names()

    def column_names(table_name: str) -> set[str]:
        if not table_exists(table_name):
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    def add_columns_if_missing(table_name: str, columns: list[sa.Column]) -> None:
        existing = column_names(table_name)
        missing = [column for column in columns if column.name not in existing]
        if not missing:
            return
        with op.batch_alter_table(table_name) as batch_op:
            for column in missing:
                batch_op.add_column(column)

    # === 1. maintenance_orders: campos para separar execução de prazo ===
    add_columns_if_missing('maintenance_orders', [
        sa.Column('execution_status', sa.String(30), nullable=True, server_default='not_started'),
        sa.Column('needs_review', sa.Boolean, nullable=True, server_default='0'),
        sa.Column('review_decision', sa.String(30), nullable=True),
        sa.Column('review_operator', sa.String(100), nullable=True),
        sa.Column('review_at', sa.DateTime, nullable=True),
        sa.Column('review_notes', sa.Text, nullable=True),
        sa.Column('source_file_hash', sa.String(64), nullable=True),
        sa.Column('source_sheet', sa.String(50), nullable=True),
        sa.Column('source_row', sa.Integer, nullable=True),
        sa.Column('source_cell', sa.String(20), nullable=True),
        sa.Column('source_value_130', sa.String(20), nullable=True),
        sa.Column('rules_engine_version', sa.String(10), nullable=True),
        sa.Column('deadline_calculated_at', sa.DateTime, nullable=True),
    ])

    # Preencher execution_status baseado no status atual
    op.execute("""
        UPDATE maintenance_orders
        SET execution_status = 'completed'
        WHERE status IN ('completed', 'completed_with_issues')
    """)
    op.execute("""
        UPDATE maintenance_orders
        SET execution_status = 'in_progress'
        WHERE status = 'in_progress'
    """)
    op.execute("""
        UPDATE maintenance_orders
        SET execution_status = 'cancelled'
        WHERE status = 'cancelled'
    """)
    op.execute("""
        UPDATE maintenance_orders
        SET execution_status = 'not_started'
        WHERE execution_status IS NULL
    """)
    op.execute("""
        UPDATE maintenance_orders
        SET needs_review = 0
        WHERE needs_review IS NULL
    """)

    # Marcar ordens sem planned_date como needs_review (situação a conferir)
    # Essas são ordens que não têm data explícita - situação ambígua
    op.execute("""
        UPDATE maintenance_orders
        SET needs_review = 1
        WHERE planned_date IS NULL
        AND planned_year IS NULL
        AND status IN ('overdue', 'scheduled', 'today')
    """)

    # === 2. maintenance_plans: campos de automação e rastreabilidade ===
    add_columns_if_missing('maintenance_plans', [
        sa.Column('plan_type', sa.String(30), nullable=True, server_default='fixed_calendar'),
        sa.Column('fixed_months', sa.Text, nullable=True),
        sa.Column('generation_horizon_months', sa.Integer, nullable=True, server_default='12'),
        sa.Column('confidence', sa.String(10), nullable=True, server_default='medium'),
        sa.Column('source_document', sa.String(500), nullable=True),
        sa.Column('source_document_hash', sa.String(64), nullable=True),
        sa.Column('source_document_page', sa.String(50), nullable=True),
        sa.Column('last_auto_generated_at', sa.DateTime, nullable=True),
        sa.Column('confirmed_by', sa.String(100), nullable=True),
        sa.Column('confirmed_at', sa.DateTime, nullable=True),
    ])
    op.execute("""
        UPDATE maintenance_plans
        SET plan_type = 'fixed_calendar'
        WHERE plan_type IS NULL
    """)
    op.execute("""
        UPDATE maintenance_plans
        SET generation_horizon_months = 12
        WHERE generation_horizon_months IS NULL
    """)
    op.execute("""
        UPDATE maintenance_plans
        SET confidence = 'medium'
        WHERE confidence IS NULL
    """)

    # === 3. Tabela de histórico legado ===
    if not table_exists('legacy_history'):
        op.create_table('legacy_history',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=False),
            sa.Column('planned_year', sa.Integer, nullable=True),
            sa.Column('planned_month', sa.Integer, nullable=True),
            sa.Column('planned_date', sa.Date, nullable=True),
            sa.Column('source_value', sa.String(20), nullable=True),
            sa.Column('source_file', sa.String(500), nullable=True),
            sa.Column('source_file_hash', sa.String(64), nullable=True),
            sa.Column('source_sheet', sa.String(50), nullable=True),
            sa.Column('source_row', sa.Integer, nullable=True),
            sa.Column('source_cell', sa.String(20), nullable=True),
            sa.Column('interpretation', sa.String(30), nullable=True),
            sa.Column('interpretation_confidence', sa.String(10), nullable=True),
            sa.Column('operator_name', sa.String(100), nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=True),
        )

    # === 4. Tabela de medidores ===
    if not table_exists('asset_meters'):
        op.create_table('asset_meters',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=False),
            sa.Column('meter_type', sa.String(30), nullable=False),
            sa.Column('unit', sa.String(20), nullable=True),
            sa.Column('current_reading', sa.Float, nullable=True),
            sa.Column('last_reading_at', sa.DateTime, nullable=True),
            sa.Column('maintenance_interval', sa.Float, nullable=True),
            sa.Column('next_maintenance_at', sa.Float, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=True),
            sa.Column('updated_at', sa.DateTime, nullable=True),
        )

    # === 5. Tabela de configuração de qualidade ===
    if not table_exists('quality_config'):
        op.create_table('quality_config',
            sa.Column('key', sa.String(50), primary_key=True),
            sa.Column('value', sa.Text, nullable=True),
            sa.Column('updated_at', sa.DateTime, nullable=True),
        )
    # Inserir configuração padrão
    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('maintenance_target_pct', '80', datetime('now'))
    """)
    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('version', '1.3.0', datetime('now'))
    """)

    # === 6. Tabela de documentos indexados ===
    if not table_exists('asset_document_index'):
        op.create_table('asset_document_index',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=True),
            sa.Column('file_path', sa.String(1000), nullable=False),
            sa.Column('file_name', sa.String(500), nullable=False),
            sa.Column('file_extension', sa.String(20), nullable=True),
            sa.Column('file_size', sa.Integer, nullable=True),
            sa.Column('file_hash', sa.String(64), nullable=True),
            sa.Column('document_type', sa.String(50), nullable=True),
            sa.Column('confidence', sa.String(10), nullable=True),
            sa.Column('extracted_text', sa.Text, nullable=True),
            sa.Column('extraction_method', sa.String(30), nullable=True),
            sa.Column('needs_review', sa.Boolean, nullable=True, server_default='0'),
            sa.Column('indexed_at', sa.DateTime, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
        )


def downgrade():
    # Remover tabelas novas
    op.drop_table('asset_document_index')
    op.drop_table('quality_config')
    op.drop_table('asset_meters')
    op.drop_table('legacy_history')

    # Remover colunas de maintenance_plans
    with op.batch_alter_table('maintenance_plans') as batch_op:
        for col in ['plan_type', 'fixed_months', 'generation_horizon_months', 'confidence',
                    'source_document', 'source_document_hash', 'source_document_page',
                    'last_auto_generated_at', 'confirmed_by', 'confirmed_at']:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    # Remover colunas de maintenance_orders
    with op.batch_alter_table('maintenance_orders') as batch_op:
        for col in ['execution_status', 'needs_review', 'review_decision', 'review_operator',
                    'review_at', 'review_notes', 'source_file_hash', 'source_sheet',
                    'source_row', 'source_cell', 'source_value_130', 'rules_engine_version',
                    'deadline_calculated_at']:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass
