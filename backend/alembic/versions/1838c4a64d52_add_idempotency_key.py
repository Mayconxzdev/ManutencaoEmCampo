"""add_idempotency_key

Revision ID: 1838c4a64d52
Revises: 95faaf896909
Create Date: 2026-06-24 09:38:02.190407

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1838c4a64d52'
down_revision: Union[str, Sequence[str], None] = '95faaf896909'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('maintenance_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('idempotency_key', sa.String(length=36), nullable=True))
        batch_op.create_unique_constraint('uq_maintenance_orders_idempotency_key', ['idempotency_key'])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        try:
            op.execute("DROP INDEX IF EXISTS uq_maintenance_orders_idempotency_key")
        except Exception:
            pass
        try:
            op.execute("DROP INDEX IF EXISTS ix_maintenance_orders_idempotency_key")
        except Exception:
            pass

    with op.batch_alter_table('maintenance_orders', schema=None) as batch_op:
        if bind.dialect.name != 'sqlite':
            batch_op.drop_constraint('uq_maintenance_orders_idempotency_key', type_='unique')
        batch_op.drop_column('idempotency_key')
