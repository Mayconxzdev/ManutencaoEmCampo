"""version 2.0.3 operational queue cleanup and imported baseline review

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-14
"""
from alembic import op


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Paquimetros e demais instrumentos de medicao devem permanecer
    # rastreaveis, mas fora da fila de preventiva diaria. A estrategia passa
    # a ser verificacao/calibracao, tratada em area propria de Qualidade.
    op.execute("""
        UPDATE assets
        SET show_in_daily_list = 0,
            maintenance_strategy = 'calibration_or_verification'
        WHERE asset_class = 'measuring_instrument'
    """)

    # As pendencias vencidas vieram da importacao inicial da planilha, nao de
    # manutencoes reais atrasadas. Elas ficam preservadas e visiveis para
    # conferencia, sem poluir a lista operacional nem indicadores de atraso.
    op.execute("""
        UPDATE maintenance_orders
        SET status = 'needs_review',
            needs_review = 1,
            review_decision = 'to_review',
            review_notes = COALESCE(
                review_notes,
                'Programacao inicial importada da planilha; aguardando conferencia antes de contar como manutencao atrasada.'
            ),
            source_note = COALESCE(
                source_note,
                'ManutencaoEmCampo 2.0.3: pendencia de importacao inicial preservada para conferencia operacional.'
            )
        WHERE status = 'overdue'
          AND execution_status = 'not_started'
          AND COALESCE(needs_review, 0) = 0
    """)

    # Duas OMs de componentes foram abertas apenas como teste. Nao apagamos o
    # registro; retiramos da fila diaria e deixamos a situacao explicitamente
    # identificada para regularizacao/auditoria futura.
    op.execute("""
        UPDATE maintenance_orders
        SET status = 'needs_review',
            needs_review = 1,
            review_decision = 'regularization',
            review_notes = COALESCE(
                review_notes,
                'Execucao de teste em componente fora da rotina diaria; preservar para regularizacao, sem concluir automaticamente.'
            ),
            source_note = COALESCE(
                source_note,
                'ManutencaoEmCampo 2.0.3: teste preservado fora da fila operacional.'
            )
        WHERE asset_id IN (
            SELECT id FROM assets WHERE show_in_daily_list = 0
        )
          AND execution_status = 'in_progress'
          AND status <> 'completed'
    """)


def downgrade() -> None:
    # A reversao automatica poderia reintroduzir atrasos falsos e misturar
    # inventario complementar na rotina. A trilha preservada fica para revisao.
    return
