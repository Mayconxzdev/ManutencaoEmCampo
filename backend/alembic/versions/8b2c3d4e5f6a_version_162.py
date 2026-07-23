"""version_162

Revision ID: 8b2c3d4e5f6a
Revises: 7a9b8c3d2e1f
Create Date: 2026-06-30 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "7a9b8c3d2e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FAKE_CA_VALUES = ("11223", "22334", "33445", "44556", "55667", "99999")


def _table_columns(bind, table_name: str) -> set[str]:
    rows = bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    bind = op.get_bind()
    epi_columns = _table_columns(bind, "epi_catalog")
    if {"ca_number", "ca_status", "ca_validity", "ca_consulted_at", "ca_source"}.issubset(epi_columns):
        bind.execute(
            sa.text(
                """
                UPDATE epi_catalog
                   SET ca_number = NULL,
                       ca_status = 'não conferido',
                       ca_validity = NULL,
                       ca_consulted_at = NULL,
                       ca_source = NULL
                 WHERE ca_number IN :fake_values
                    OR ca_source = 'Consulta CA / MTE'
                """
            ).bindparams(sa.bindparam("fake_values", expanding=True)),
            {"fake_values": FAKE_CA_VALUES},
        )

    quality_columns = _table_columns(bind, "quality_config")
    if {"key", "value", "updated_at"}.issubset(quality_columns):
        bind.execute(
            sa.text(
                "UPDATE quality_config SET value = '90', updated_at = datetime('now') WHERE key = 'maintenance_target_pct'"
            )
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO quality_config(key, value, updated_at)
                SELECT 'maintenance_target_pct', '90', datetime('now')
                 WHERE NOT EXISTS (SELECT 1 FROM quality_config WHERE key = 'maintenance_target_pct')
                """
            )
        )
        bind.execute(
            sa.text(
                "UPDATE quality_config SET value = '1.6.2', updated_at = datetime('now') WHERE key = 'version'"
            )
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO quality_config(key, value, updated_at)
                SELECT 'version', '1.6.2', datetime('now')
                 WHERE NOT EXISTS (SELECT 1 FROM quality_config WHERE key = 'version')
                """
            )
        )


def downgrade() -> None:
    # Não restaura CAs fictícios. Restauração real deve usar o backup pré-update.
    pass
