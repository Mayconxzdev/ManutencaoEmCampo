"""version_161

Revision ID: 7a9b8c3d2e1f
Revises: 5c39b67d8b87
Create Date: 2026-06-30 12:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import date

# revision identifiers, used by Alembic.
revision: str = '7a9b8c3d2e1f'
down_revision: Union[str, Sequence[str], None] = '5c39b67d8b87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Add columns with safety check (SQLite doesn't support multiple alter tables easily, so add them one by one)
    op.add_column('epi_catalog', sa.Column('ca_number', sa.String(length=50), nullable=True))
    op.add_column('epi_catalog', sa.Column('ca_status', sa.String(length=50), nullable=True))
    op.add_column('epi_catalog', sa.Column('ca_validity', sa.Date(), nullable=True))
    op.add_column('epi_catalog', sa.Column('ca_consulted_at', sa.DateTime(), nullable=True))
    op.add_column('epi_catalog', sa.Column('ca_source', sa.String(length=255), nullable=True))

    # 2. O 1.6.2 não semeia CAs. CA só pode vir de conferência real e auditável.

def downgrade() -> None:
    # Remove columns (SQLite doesn't support drop column in older versions easily, but modern python/sqlite does)
    # Using batch_alter_table is safest for SQLite compatibility
    with op.batch_alter_table('epi_catalog') as batch_op:
        batch_op.drop_column('ca_source')
        batch_op.drop_column('ca_consulted_at')
        batch_op.drop_column('ca_validity')
        batch_op.drop_column('ca_status')
        batch_op.drop_column('ca_number')
