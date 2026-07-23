"""Alembic migration: 1.4.0 - Histórico imutável, EPI, corretivas, rodadas, notificações, materiais"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers
revision = 'f1a2b3c4d5e6_version_140'
down_revision = 'e1f2g3h4i5j6_version_130'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def table_exists(table_name: str) -> bool:
        return table_name in inspector.get_table_names()

    def column_names(table_name: str) -> set:
        if not table_exists(table_name):
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    def add_columns_if_missing(table_name: str, columns: list) -> None:
        existing = column_names(table_name)
        missing = [column for column in columns if column.name not in existing]
        if not missing:
            return
        with op.batch_alter_table(table_name) as batch_op:
            for column in missing:
                batch_op.add_column(column)

    # =========================================================
    # 1. maintenance_orders: campos da 1.4.0
    # =========================================================
    add_columns_if_missing('maintenance_orders', [
        sa.Column('order_type', sa.String(30), nullable=True, server_default='preventive'),
        sa.Column('parent_work_order_id', sa.String(36), nullable=True),
        sa.Column('relation_type', sa.String(30), nullable=True),
        sa.Column('occurrence_number', sa.Integer, nullable=True),
        sa.Column('plan_code', sa.String(50), nullable=True),
        sa.Column('epi_confirmed', sa.Boolean, nullable=True, server_default='0'),
        sa.Column('epi_confirmed_at', sa.DateTime, nullable=True),
        sa.Column('epi_confirmed_by', sa.String(100), nullable=True),
        sa.Column('machine_stopped', sa.Boolean, nullable=True, server_default='0'),
        sa.Column('machine_stopped_at', sa.DateTime, nullable=True),
        sa.Column('machine_released_at', sa.DateTime, nullable=True),
        sa.Column('final_json', sa.Text, nullable=True),
        sa.Column('final_pdf_path', sa.String(500), nullable=True),
        sa.Column('final_sha256', sa.String(64), nullable=True),
        sa.Column('final_revision', sa.Integer, nullable=True, server_default='1'),
        sa.Column('round_id', sa.String(36), nullable=True),
    ])

    # Garantir defaults
    op.execute("UPDATE maintenance_orders SET order_type = 'preventive' WHERE order_type IS NULL")
    op.execute("UPDATE maintenance_orders SET epi_confirmed = 0 WHERE epi_confirmed IS NULL")
    op.execute("UPDATE maintenance_orders SET machine_stopped = 0 WHERE machine_stopped IS NULL")
    op.execute("UPDATE maintenance_orders SET final_revision = 1 WHERE final_revision IS NULL")

    # =========================================================
    # 2. work_order_events — linha do tempo imutável
    # =========================================================
    if not table_exists('work_order_events'):
        op.create_table('work_order_events',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=False),
            sa.Column('event_type', sa.String(50), nullable=False),
            sa.Column('operator_name', sa.String(100), nullable=True),
            sa.Column('payload', sa.Text, nullable=True),  # JSON
            sa.Column('created_at', sa.DateTime, nullable=False),
        )

    # =========================================================
    # 3. work_order_snapshots — fotografia lógica imutável
    # =========================================================
    if not table_exists('work_order_snapshots'):
        op.create_table('work_order_snapshots',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=False),
            sa.Column('snapshot_json', sa.Text, nullable=False),  # JSON completo
            sa.Column('created_at', sa.DateTime, nullable=False),
        )

    # =========================================================
    # 4. work_order_corrections — correções posteriores auditadas
    # =========================================================
    if not table_exists('work_order_corrections'):
        op.create_table('work_order_corrections',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=False),
            sa.Column('field_name', sa.String(100), nullable=False),
            sa.Column('old_value', sa.Text, nullable=True),
            sa.Column('new_value', sa.Text, nullable=True),
            sa.Column('reason', sa.Text, nullable=True),
            sa.Column('operator_name', sa.String(100), nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=False),
        )

    # =========================================================
    # 5. epi_requirements — EPIs obrigatórios por plano
    # =========================================================
    if not table_exists('epi_requirements'):
        op.create_table('epi_requirements',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('plan_id', sa.String(36), sa.ForeignKey('maintenance_plans.id'), nullable=True),
            sa.Column('checklist_template_id', sa.String(36), sa.ForeignKey('checklist_templates.id'), nullable=True),
            sa.Column('item_name', sa.String(200), nullable=False),
            sa.Column('ca_number', sa.String(50), nullable=True),
            sa.Column('validity', sa.String(50), nullable=True),
            sa.Column('is_mandatory', sa.Boolean, nullable=True, server_default='1'),
            sa.Column('added_by', sa.String(100), nullable=True),
            sa.Column('added_at', sa.DateTime, nullable=True),
        )

    # =========================================================
    # 6. epi_confirmations — confirmação de EPI por execução
    # =========================================================
    if not table_exists('epi_confirmations'):
        op.create_table('epi_confirmations',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=False),
            sa.Column('operator_name', sa.String(100), nullable=False),
            sa.Column('epi_rule_version', sa.String(50), nullable=True),
            sa.Column('confirmed_at', sa.DateTime, nullable=False),
            sa.Column('items_json', sa.Text, nullable=True),  # JSON com lista de EPIs
            sa.Column('status', sa.String(20), nullable=False, server_default='confirmed'),
            sa.Column('blocker_reason', sa.String(255), nullable=True),
        )

    # =========================================================
    # 7. maintenance_rounds — rodadas de manutenção agrupadas
    # =========================================================
    if not table_exists('maintenance_rounds'):
        op.create_table('maintenance_rounds',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('plan_reference', sa.String(100), nullable=True),  # ex: RQ-CMP-011
            sa.Column('competence', sa.String(7), nullable=True),  # YYYY-MM
            sa.Column('status', sa.String(30), nullable=False, server_default='in_progress'),
            sa.Column('created_by', sa.String(100), nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=False),
            sa.Column('completed_at', sa.DateTime, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
        )

    # =========================================================
    # 8. round_orders — link rodada ↔ ordens individuais
    # =========================================================
    if not table_exists('round_orders'):
        op.create_table('round_orders',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('round_id', sa.String(36), sa.ForeignKey('maintenance_rounds.id'), nullable=False),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=False),
            sa.Column('sequence', sa.Integer, nullable=True),
        )

    # =========================================================
    # 9. material_requests — solicitações de material/Compras
    # =========================================================
    if not table_exists('material_requests'):
        op.create_table('material_requests',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=True),
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=True),
            sa.Column('item_name', sa.String(255), nullable=False),
            sa.Column('quantity', sa.Float, nullable=True),
            sa.Column('unit', sa.String(50), nullable=True),
            sa.Column('priority', sa.String(20), nullable=True, server_default='medium'),
            sa.Column('status', sa.String(30), nullable=False, server_default='requested'),
            sa.Column('requested_by', sa.String(100), nullable=True),
            sa.Column('requested_at', sa.DateTime, nullable=False),
            sa.Column('supplier', sa.String(255), nullable=True),
            sa.Column('purchase_order', sa.String(100), nullable=True),
            sa.Column('received_at', sa.DateTime, nullable=True),
            sa.Column('applied_at', sa.DateTime, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
            sa.Column('defect_description', sa.Text, nullable=True),
            sa.Column('photo_path', sa.String(500), nullable=True),
        )

    # =========================================================
    # 10. external_service_requests — assistência técnica
    # =========================================================
    if not table_exists('external_service_requests'):
        op.create_table('external_service_requests',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=True),
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=True),
            sa.Column('service_type', sa.String(100), nullable=True),
            sa.Column('supplier', sa.String(255), nullable=True),
            sa.Column('status', sa.String(30), nullable=False, server_default='requested'),
            sa.Column('requested_at', sa.DateTime, nullable=False),
            sa.Column('requested_by', sa.String(100), nullable=True),
            sa.Column('scheduled_at', sa.DateTime, nullable=True),
            sa.Column('completed_at', sa.DateTime, nullable=True),
            sa.Column('document_status', sa.String(30), nullable=True, server_default='pending'),
            sa.Column('laudo_path', sa.String(500), nullable=True),
            sa.Column('certificate_path', sa.String(500), nullable=True),
            sa.Column('warranty_until', sa.Date, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
            sa.Column('operational_status', sa.String(30), nullable=True),  # 'stopped', 'released', 'released_with_attention'
        )

    # =========================================================
    # 11. notification_rules — regras de notificação
    # =========================================================
    if not table_exists('notification_rules'):
        op.create_table('notification_rules',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('event_type', sa.String(100), nullable=False),
            sa.Column('roles_json', sa.Text, nullable=True),  # JSON lista de roles/destinatários
            sa.Column('sector_id', sa.String(36), nullable=True),
            sa.Column('is_active', sa.Boolean, nullable=True, server_default='1'),
            sa.Column('channel', sa.String(20), nullable=True, server_default='email'),
            sa.Column('created_at', sa.DateTime, nullable=True),
        )

    # =========================================================
    # 12. notification_queue — fila de saída idempotente
    # =========================================================
    if not table_exists('notification_queue'):
        op.create_table('notification_queue',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('rule_id', sa.String(36), nullable=True),
            sa.Column('order_id', sa.String(36), nullable=True),
            sa.Column('event_type', sa.String(100), nullable=True),
            sa.Column('recipient', sa.String(255), nullable=False),
            sa.Column('channel', sa.String(20), nullable=False, server_default='email'),
            sa.Column('subject', sa.String(500), nullable=True),
            sa.Column('body', sa.Text, nullable=True),
            sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
            sa.Column('attempt_count', sa.Integer, nullable=True, server_default='0'),
            sa.Column('last_attempt_at', sa.DateTime, nullable=True),
            sa.Column('sent_at', sa.DateTime, nullable=True),
            sa.Column('error_msg', sa.Text, nullable=True),
            sa.Column('idempotency_key', sa.String(120), nullable=True, unique=True),
            sa.Column('created_at', sa.DateTime, nullable=False),
        )

    # =========================================================
    # 13. downtime_records — paradas de máquina
    # =========================================================
    if not table_exists('downtime_records'):
        op.create_table('downtime_records',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=False),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('maintenance_orders.id'), nullable=True),
            sa.Column('started_at', sa.DateTime, nullable=False),
            sa.Column('ended_at', sa.DateTime, nullable=True),
            sa.Column('duration_mins', sa.Integer, nullable=True),
            sa.Column('reason', sa.Text, nullable=True),
            sa.Column('released_by', sa.String(100), nullable=True),
            sa.Column('condition_after', sa.String(30), nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
        )

    # =========================================================
    # 14. checklist_import_log — rastreabilidade de importação
    # =========================================================
    if not table_exists('checklist_import_log'):
        op.create_table('checklist_import_log',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('file_name', sa.String(255), nullable=False),
            sa.Column('file_path', sa.String(500), nullable=True),
            sa.Column('file_hash', sa.String(64), nullable=False),
            sa.Column('rq_cmp_number', sa.String(20), nullable=True),
            sa.Column('year', sa.Integer, nullable=True),
            sa.Column('version', sa.String(20), nullable=True),
            sa.Column('title', sa.String(500), nullable=True),
            sa.Column('asset_references', sa.Text, nullable=True),  # JSON lista de ativos referenciados
            sa.Column('status', sa.String(30), nullable=False),  # 'imported', 'conflict', 'duplicate', 'error', 'skipped'
            sa.Column('classification', sa.String(50), nullable=True),  # 'template', 'programming', 'execution', 'partial', etc.
            sa.Column('conflicts_json', sa.Text, nullable=True),  # JSON de conflitos detectados
            sa.Column('checklist_template_id', sa.String(36), nullable=True),
            sa.Column('checklist_version_id', sa.String(36), nullable=True),
            sa.Column('items_count', sa.Integer, nullable=True),
            sa.Column('epi_count', sa.Integer, nullable=True),
            sa.Column('materials_count', sa.Integer, nullable=True),
            sa.Column('imported_at', sa.DateTime, nullable=False),
            sa.Column('notes', sa.Text, nullable=True),
        )

    # =========================================================
    # 15. Adicionar campos ao checklist_items
    # =========================================================
    add_columns_if_missing('checklist_items', [
        sa.Column('item_type', sa.String(30), nullable=True, server_default='inspection'),  # 'inspection', 'service', 'measurement'
        sa.Column('not_applicable_reasons', sa.Text, nullable=True),  # JSON com motivos rápidos
    ])

    # =========================================================
    # 16. Adicionar campos ao checklist_template_versions
    # =========================================================
    add_columns_if_missing('checklist_template_versions', [
        sa.Column('valid_from', sa.Date, nullable=True),
        sa.Column('valid_until', sa.Date, nullable=True),
        sa.Column('source_document', sa.String(500), nullable=True),
        sa.Column('source_document_hash', sa.String(64), nullable=True),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
    ])

    # =========================================================
    # 17. Adicionar campos ao checklist_templates
    # =========================================================
    add_columns_if_missing('checklist_templates', [
        sa.Column('asset_patrimonio', sa.String(50), nullable=True),  # Ex: M-16
        sa.Column('asset_manufacturer', sa.String(100), nullable=True),
        sa.Column('asset_model_ref', sa.String(100), nullable=True),
        sa.Column('epi_summary', sa.Text, nullable=True),  # JSON resumo de EPIs
        sa.Column('materials_summary', sa.Text, nullable=True),  # JSON resumo de materiais
        sa.Column('maintenance_type', sa.String(30), nullable=True, server_default='preventive'),
        sa.Column('rq_cmp_reference', sa.String(50), nullable=True),
    ])

    # =========================================================
    # 18. Adicionar campos ao maintenance_order_items (respostas)
    # =========================================================
    add_columns_if_missing('maintenance_order_items', [
        sa.Column('defect_found', sa.Text, nullable=True),
        sa.Column('corrected_in_place', sa.Boolean, nullable=True),
        sa.Column('correction_description', sa.Text, nullable=True),
        sa.Column('needs_part', sa.Boolean, nullable=True),
        sa.Column('part_name', sa.String(255), nullable=True),
        sa.Column('can_operate', sa.Boolean, nullable=True),
        sa.Column('not_applicable_reason', sa.String(100), nullable=True),
        sa.Column('audio_transcript', sa.Text, nullable=True),
        sa.Column('photo_category', sa.String(30), nullable=True),  # 'before', 'defect', 'during', 'after', 'meter', 'document', 'plate'
    ])

    # =========================================================
    # 19. Atualizar configuração de versão
    # =========================================================
    op.execute("""
        INSERT OR REPLACE INTO quality_config (key, value, updated_at)
        VALUES ('version', '1.4.0', datetime('now'))
    """)

    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('maintenance_target_pct', '90', datetime('now'))
    """)

    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('epi_require_before_checklist', '1', datetime('now'))
    """)

    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('notification_email_enabled', '0', datetime('now'))
    """)

    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('notification_smtp_host', '', datetime('now'))
    """)

    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('notification_smtp_port', '587', datetime('now'))
    """)

    op.execute("""
        INSERT OR IGNORE INTO quality_config (key, value, updated_at)
        VALUES ('notification_smtp_user', '', datetime('now'))
    """)


def downgrade():
    # Remover tabelas novas (ordem inversa de dependências)
    for table in [
        'round_orders', 'maintenance_rounds',
        'epi_confirmations', 'epi_requirements',
        'work_order_corrections', 'work_order_snapshots', 'work_order_events',
        'downtime_records', 'external_service_requests', 'material_requests',
        'notification_queue', 'notification_rules',
        'checklist_import_log',
    ]:
        try:
            op.drop_table(table)
        except Exception:
            pass

    # Remover colunas de maintenance_orders
    with op.batch_alter_table('maintenance_orders') as batch_op:
        for col in ['order_type', 'parent_work_order_id', 'relation_type', 'occurrence_number',
                    'plan_code', 'epi_confirmed', 'epi_confirmed_at', 'epi_confirmed_by',
                    'machine_stopped', 'machine_stopped_at', 'machine_released_at',
                    'final_json', 'final_pdf_path', 'final_sha256', 'final_revision', 'round_id']:
            try:
                batch_op.drop_column(col)
            except Exception:
                pass
