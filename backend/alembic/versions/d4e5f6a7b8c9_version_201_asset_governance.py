"""version 2.0.1 asset governance and daily-work classification

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4
Create Date: 2026-07-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _add_columns(bind) -> None:
    present = _columns(bind, "assets")
    columns = [
        sa.Column("legacy_patrimonio", sa.String(length=50), nullable=True),
        sa.Column("controlled_code", sa.String(length=80), nullable=True),
        sa.Column("asset_class", sa.String(length=40), nullable=True),
        sa.Column("maintenance_strategy", sa.String(length=40), nullable=True),
        sa.Column("show_in_daily_list", sa.Boolean(), nullable=True),
    ]
    missing = [column for column in columns if column.name not in present]
    if missing:
        with op.batch_alter_table("assets") as batch:
            for column in missing:
                batch.add_column(column)


def _index(name: str, columns: list[str], unique: bool = False) -> None:
    try:
        op.create_index(name, "assets", columns, unique=unique)
    except Exception:
        pass


def upgrade() -> None:
    bind = op.get_bind()
    _add_columns(bind)
    _index("ix_assets_legacy_patrimonio", ["legacy_patrimonio"])
    _index("ix_assets_controlled_code", ["controlled_code"])
    _index("ix_assets_asset_class", ["asset_class"])
    _index("ix_assets_maintenance_strategy", ["maintenance_strategy"])
    _index("ix_assets_show_in_daily_list", ["show_in_daily_list"])

    # A fonte de importação é preservada intacta; esta classificação apenas impede que
    # peças de reposição e ferramentas simples virem preventivas de máquina.
    op.execute("UPDATE assets SET legacy_patrimonio = patrimonio WHERE legacy_patrimonio IS NULL OR trim(legacy_patrimonio) = ''")
    op.execute("UPDATE assets SET controlled_code = patrimonio WHERE controlled_code IS NULL OR trim(controlled_code) = ''")
    op.execute("UPDATE assets SET asset_class = CASE WHEN type = 'machine' THEN 'production_machine' ELSE 'maintainable_equipment' END WHERE asset_class IS NULL OR trim(asset_class) = ''")
    op.execute("UPDATE assets SET maintenance_strategy = CASE WHEN type = 'machine' THEN 'preventive' ELSE 'inspection' END WHERE maintenance_strategy IS NULL OR trim(maintenance_strategy) = ''")
    op.execute("UPDATE assets SET show_in_daily_list = 1 WHERE show_in_daily_list IS NULL")

    # O código de patrimônio original continua visível em legacy_patrimonio.
    # Onde a planilha trouxe o mesmo patrimônio para mais de um registro, cada
    # item recebe uma identificação operacional própria para etiqueta/QR. Não
    # alteramos nem descartamos o código de origem.
    op.execute("""
        UPDATE assets
        SET controlled_code = patrimonio || '-' || upper(substr(replace(id, '-', ''), 1, 6))
        WHERE patrimonio IN (
            SELECT patrimonio FROM assets GROUP BY patrimonio HAVING count(*) > 1
        )
    """)

    # Os 21 conjuntos filtro/regulador/lubrificador são componentes de reposição.
    # Mantemos ativo e documentado, mas retiramos da fila diária e aposentamos o
    # plano recorrente: futuras trocas devem ser lançadas como material/componente
    # da máquina atendida, não como uma máquina independente.
    op.execute("""
        UPDATE assets
        SET asset_class = 'replaceable_component',
            maintenance_strategy = 'replacement_record',
            show_in_daily_list = 0,
            controlled_code = 'COMP-' || replace(patrimonio, '-', '') || '-' || upper(substr(replace(id, '-', ''), 1, 6))
        WHERE upper(description) LIKE '%CONJUNTO FILTRO REGULADOR E LUBRIFICADOR%'
    """)
    op.execute("""
        UPDATE maintenance_plans
        SET is_active = 0,
            recurrence_status = 'retired_component_record',
            confirmed_by = COALESCE(confirmed_by, 'Governança ManutencaoEmCampo 2.0.1')
        WHERE asset_id IN (
            SELECT id FROM assets WHERE asset_class = 'replaceable_component'
        ) AND is_active = 1
    """)

    # Instrumentos precisam de calibração/verificação, não de preventiva comum.
    op.execute("""
        UPDATE assets
        SET asset_class = 'measuring_instrument',
            maintenance_strategy = 'calibration_or_verification'
        WHERE upper(description) LIKE '%PAQUÍMETRO%'
           OR upper(description) LIKE '%MICRÔMETRO%'
           OR upper(description) LIKE '%TORQUÍMETRO%'
           OR upper(description) LIKE '%MANÔMETRO%'
           OR upper(description) LIKE '%MULTÍMETRO%'
    """)

    # Ferramentas manuais/portáteis permanecem inventariadas, sem poluir a lista
    # de equipamentos de produção. Podem ser consultadas em Gestão/Inventário.
    op.execute("""
        UPDATE assets
        SET asset_class = 'tool',
            maintenance_strategy = 'inspection_or_replacement',
            show_in_daily_list = 0
        WHERE upper(description) LIKE '%TRENA%'
           OR upper(description) LIKE '%NÍVEL MAGNÉTICO%'
           OR upper(description) LIKE '%NÍVEL LASER%'
           OR upper(description) LIKE '%CHAVE DE CATRACA%'
           OR upper(description) LIKE '%ESQUADRO%'
    """)

    # Nenhuma OM ou plano é apagado. As rotinas que pertenciam a itens agora
    # classificados como ferramenta/componente saem da agenda de execução e
    # ficam marcadas para consulta da qualidade, sem gerar recorrência futura.
    op.execute("""
        UPDATE maintenance_plans
        SET is_active = 0,
            recurrence_status = 'retired_non_maintainable_record',
            confirmed_by = COALESCE(confirmed_by, 'Governança ManutencaoEmCampo 2.0.1')
        WHERE asset_id IN (
            SELECT id FROM assets
            WHERE asset_class IN ('replaceable_component', 'tool')
        ) AND is_active = 1
    """)
    op.execute("""
        UPDATE maintenance_orders
        SET status = 'needs_review',
            needs_review = 1,
            review_decision = 'regularization',
            review_notes = COALESCE(review_notes, 'Rotina preservada; item reclassificado como componente de reposição ou ferramenta em 14/07/2026. Não gerar nova recorrência.'),
            source_note = COALESCE(source_note, 'Governança ManutencaoEmCampo 2.0.1: removida da agenda diária após reclassificação sem exclusão de histórico.')
        WHERE asset_id IN (
            SELECT id FROM assets
            WHERE asset_class IN ('replaceable_component', 'tool')
        )
          AND execution_status = 'not_started'
          AND status NOT IN ('completed', 'cancelled')
    """)


def downgrade() -> None:
    # Não removemos colunas nem desfazemos a classificação: apagar a relação
    # entre o patrimônio original e sua governança seria perda de rastreabilidade.
    return
