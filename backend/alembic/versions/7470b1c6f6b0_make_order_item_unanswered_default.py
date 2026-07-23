"""make_order_item_unanswered_default

Revision ID: 7470b1c6f6b0
Revises: 1838c4a64d52
Create Date: 2026-06-24 12:10:51.527134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7470b1c6f6b0'
down_revision: Union[str, Sequence[str], None] = '1838c4a64d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
