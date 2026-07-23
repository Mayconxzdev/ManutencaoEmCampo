"""version 1.6.8 planning sequence hardening

Revision ID: e3f4a5b6c7d1
Revises: d2e3f4a5b6c0
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d1"
down_revision = "d2e3f4a5b6c0"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return {row[0] for row in bind.execute(sa.text("select name from sqlite_master where type='table'"))}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA index_list({table_name})")).fetchall()}


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    if "maintenance_orders" not in tables:
        return

    if "work_order_sequence" not in tables:
        op.create_table(
            "work_order_sequence",
            sa.Column("name", sa.String(length=50), primary_key=True),
            sa.Column("next_value", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    _add_column_if_missing("maintenance_orders", sa.Column("operator_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("maintenance_order_items", sa.Column("operator_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("work_order_events", sa.Column("operator_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("work_order_corrections", sa.Column("operator_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("epi_confirmations", sa.Column("operator_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("audit_logs", sa.Column("selected_user_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("audit_logs", sa.Column("actor_name_snapshot", sa.String(length=100), nullable=True))
    _add_column_if_missing("audit_logs", sa.Column("device_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("audit_logs", sa.Column("session_id", sa.String(length=100), nullable=True))
    _add_column_if_missing("audit_logs", sa.Column("correlation_id", sa.String(length=100), nullable=True))

    duplicate_rows = bind.execute(
        sa.text(
            """
            select plan_id, planned_year, planned_month, count(*) as total
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
        raise RuntimeError("Existem OMs duplicadas por plano/competencia; corrija antes da 1.6.8.")

    if "ux_orders_plan_month_active" not in _indexes("maintenance_orders"):
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

    next_value = bind.execute(sa.text("select coalesce(max(friendly_number), 1000) + 1 from maintenance_orders")).scalar()
    bind.execute(
        sa.text(
            """
            insert into work_order_sequence(name, next_value, updated_at)
            values ('maintenance_order', :next_value, datetime('now'))
            on conflict(name) do update
                set next_value = max(work_order_sequence.next_value, excluded.next_value),
                    updated_at = excluded.updated_at
            """
        ),
        {"next_value": int(next_value or 1001)},
    )

    if "quality_config" in _tables():
        bind.execute(
            sa.text(
                """
                insert into quality_config(key, value, updated_at)
                values ('version', '1.6.8', datetime('now'))
                on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at
                """
            )
        )


def downgrade() -> None:
    if "quality_config" in _tables():
        op.get_bind().execute(
            sa.text(
                """
                update quality_config
                   set value = '1.6.7', updated_at = datetime('now')
                 where key = 'version'
                """
            )
        )
