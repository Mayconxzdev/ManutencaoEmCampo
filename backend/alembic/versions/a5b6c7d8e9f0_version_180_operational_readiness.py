"""version 1.9.0 operational readiness

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return {row[0] for row in bind.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}


def _indexes(bind) -> set[tuple[str, str]]:
    return {
        (row[0], row[1])
        for row in bind.execute(sa.text("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")).fetchall()
    }


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = _tables(bind)
    existing_indexes = _indexes(bind)
    if "system_validation_runs" not in existing_tables:
        op.create_table(
            "system_validation_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("kind", sa.String(length=50), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("executed_by", sa.String(length=100), nullable=True),
            sa.Column("report_json", sa.Text(), nullable=False),
        )
    if ("ix_system_validation_runs_created_at", "system_validation_runs") not in existing_indexes:
        op.create_index("ix_system_validation_runs_created_at", "system_validation_runs", ["created_at"])
    if ("ix_system_validation_runs_status", "system_validation_runs") not in existing_indexes:
        op.create_index("ix_system_validation_runs_status", "system_validation_runs", ["status"])
    try:
        op.execute("insert or replace into quality_config(key, value, updated_at) values ('version', '1.9.0', datetime('now'))")
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = _tables(bind)
    existing_indexes = _indexes(bind)
    if ("ix_system_validation_runs_status", "system_validation_runs") in existing_indexes:
        op.drop_index("ix_system_validation_runs_status", table_name="system_validation_runs")
    if ("ix_system_validation_runs_created_at", "system_validation_runs") in existing_indexes:
        op.drop_index("ix_system_validation_runs_created_at", table_name="system_validation_runs")
    if "system_validation_runs" in existing_tables:
        op.drop_table("system_validation_runs")
    try:
        op.execute("update quality_config set value = '1.7.0', updated_at = datetime('now') where key = 'version'")
    except Exception:
        pass
