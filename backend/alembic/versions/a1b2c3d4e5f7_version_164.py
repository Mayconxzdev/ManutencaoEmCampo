"""version 1.6.4 storage organization and monthly planning guards

Revision ID: a1b2c3d4e5f7
Revises: 9c3d4e5f6a7b
Create Date: 2026-07-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f7"
down_revision = "9c3d4e5f6a7b"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return {row[0] for row in bind.execute(sa.text("select name from sqlite_master where type='table'"))}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA index_list({table_name})")).fetchall()}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables()

    if "file_organization_tasks" not in tables:
        op.create_table(
            "file_organization_tasks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("task_type", sa.String(length=50), nullable=False, server_default="asset_file_organization"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("source_paths_json", sa.Text(), nullable=True),
            sa.Column("total_files", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("analyzed_files", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("imported_files", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("duplicate_files", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("review_files", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("error_files", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("report_path", sa.String(length=1000), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )

    if "ix_file_organization_tasks_status" not in _indexes("file_organization_tasks"):
        op.create_index("ix_file_organization_tasks_status", "file_organization_tasks", ["status"])

    if "maintenance_orders" in tables and "ux_orders_plan_month_active" not in _indexes("maintenance_orders"):
        duplicate_rows = bind.execute(
            sa.text(
                """
                select plan_id, planned_year, planned_month, count(*) as c
                  from maintenance_orders
                 where plan_id is not null
                   and planned_year is not null
                   and planned_month is not null
                   and coalesce(status, '') != 'cancelled'
                 group by plan_id, planned_year, planned_month
                having count(*) > 1
                """
            )
        ).fetchall()
        if duplicate_rows:
            raise RuntimeError("Não é possível criar índice mensal: existem OMs duplicadas por plano/competência.")
        bind.execute(
            sa.text(
                """
                create unique index if not exists ux_orders_plan_month_active
                    on maintenance_orders(plan_id, planned_year, planned_month)
                 where plan_id is not null
                   and planned_year is not null
                   and planned_month is not null
                   and coalesce(status, '') != 'cancelled'
                """
            )
        )

    if "quality_config" in tables:
        bind.execute(
            sa.text(
                """
                INSERT INTO quality_config(key, value, updated_at)
                VALUES ('version', '1.6.4', datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "maintenance_orders" in _tables() and "ux_orders_plan_month_active" in _indexes("maintenance_orders"):
        op.drop_index("ux_orders_plan_month_active", table_name="maintenance_orders")
    if "file_organization_tasks" in _tables():
        op.drop_table("file_organization_tasks")
    if "quality_config" in _tables():
        bind.execute(
            sa.text(
                """
                INSERT INTO quality_config(key, value, updated_at)
                VALUES ('version', '1.6.3', datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """
            )
        )
