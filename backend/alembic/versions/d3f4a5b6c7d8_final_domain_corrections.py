"""final domain corrections

Revision ID: d3f4a5b6c7d8
Revises: 7470b1c6f6b0
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "7470b1c6f6b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("maintenance_plans") as batch:
        batch.add_column(sa.Column("recurrence_status", sa.String(length=30), nullable=True, server_default="to_review"))
        batch.add_column(sa.Column("recurrence_confirmed_by", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("recurrence_confirmed_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("maintenance_orders") as batch:
        batch.add_column(sa.Column("planned_year", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("planned_month", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("original_competence", sa.String(length=7), nullable=True))
        batch.add_column(sa.Column("scheduled_day_is_explicit", sa.Boolean(), nullable=True, server_default=sa.false()))
        batch.add_column(sa.Column("source_status", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("source_note", sa.Text(), nullable=True))

    # Converte respostas vazias/antigas em estado explícito e recria a tabela com regra válida.
    op.execute("UPDATE maintenance_order_items SET status='unanswered' WHERE status IS NULL OR trim(status)='' ")
    with op.batch_alter_table("maintenance_order_items") as batch:
        batch.alter_column("status", existing_type=sa.String(length=20), server_default="unanswered", nullable=False)
        batch.create_check_constraint(
            "ck_order_item_status",
            "status IN ('unanswered','ok','attention','not_applicable')",
        )


def downgrade() -> None:
    with op.batch_alter_table("maintenance_order_items") as batch:
        batch.drop_constraint("ck_order_item_status", type_="check")
        batch.alter_column("status", existing_type=sa.String(length=20), server_default=None, nullable=True)
    with op.batch_alter_table("maintenance_orders") as batch:
        batch.drop_column("source_note")
        batch.drop_column("source_status")
        batch.drop_column("scheduled_day_is_explicit")
        batch.drop_column("original_competence")
        batch.drop_column("planned_month")
        batch.drop_column("planned_year")
    with op.batch_alter_table("maintenance_plans") as batch:
        batch.drop_column("recurrence_confirmed_at")
        batch.drop_column("recurrence_confirmed_by")
        batch.drop_column("recurrence_status")
