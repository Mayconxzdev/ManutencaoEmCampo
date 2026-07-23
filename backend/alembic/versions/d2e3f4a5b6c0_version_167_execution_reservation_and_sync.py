"""version 1.6.7 execution reservation and sync foundations

Revision ID: d2e3f4a5b6c0
Revises: b1c2d3e4f5a8
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c0"
down_revision = "b1c2d3e4f5a8"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return {row[0] for row in bind.execute(sa.text("select name from sqlite_master where type='table'"))}


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()}


def _add_column(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    if "maintenance_orders" not in _tables():
        return

    _add_column("maintenance_orders", sa.Column("reservation_operator", sa.String(length=100), nullable=True))
    _add_column("maintenance_orders", sa.Column("reservation_device_id", sa.String(length=100), nullable=True))
    _add_column("maintenance_orders", sa.Column("reservation_started_at", sa.DateTime(), nullable=True))
    _add_column("maintenance_orders", sa.Column("reservation_expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # SQLite deployments keep additive columns on downgrade to avoid table rebuild
    # against production maintenance data. Rollback of the official app restores
    # the 1.6.6 database snapshot instead of destructively rebuilding this table.
    pass
