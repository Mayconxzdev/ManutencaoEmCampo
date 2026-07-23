"""version 2.0.2 repair classification review decision compatibility

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-14
"""
from alembic import op


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A API histórica /orders valida este campo com valores controlados. A
    # classificação continua explícita em review_notes/source_note; aqui só
    # normalizamos o valor já salvo para não quebrar a listagem nem perder OM.
    op.execute("""
        UPDATE maintenance_orders
        SET review_decision = 'regularization'
        WHERE review_decision = 'classification_adjustment'
    """)


def downgrade() -> None:
    # Não reintroduzir valor incompatível em registros de produção.
    return
