"""version 1.6.5 stabilization, file review queue and operator identity

Revision ID: b1c2d3e4f5a8
Revises: a1b2c3d4e5f7
Create Date: 2026-07-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f5a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    return {row[0] for row in bind.execute(sa.text("select name from sqlite_master where type='table'"))}


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA index_list({table_name})")).fetchall()}


def _operators_name_has_unique_index() -> bool:
    bind = op.get_bind()
    for index in bind.execute(sa.text("PRAGMA index_list(operators)")).fetchall():
        index_name = index[1]
        is_unique = bool(index[2])
        if not is_unique:
            continue
        cols = [row[2] for row in bind.execute(sa.text(f"PRAGMA index_info({index_name})")).fetchall()]
        if cols == ["name"]:
            return True
    return False


def _rebuild_operators_without_unique_name() -> None:
    bind = op.get_bind()
    existing_columns = _columns("operators")
    if not _operators_name_has_unique_index():
        return
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(
        sa.text(
            """
            create table operators_165 (
                id varchar(36) primary key,
                name varchar(100) not null,
                normalized_name varchar(120),
                nickname varchar(100),
                sector_id varchar(36),
                origin varchar(30),
                photo_path varchar(1000),
                photo_thumbnail_path varchar(1000),
                photo_hash varchar(64),
                is_active boolean,
                created_at datetime,
                updated_at datetime,
                created_by_operator_id varchar(36),
                archived_at datetime,
                archived_by varchar(100),
                archived_by_operator_id varchar(36)
            )
            """
        )
    )
    copy_columns = [
        "id",
        "name",
        "photo_path",
        "photo_thumbnail_path",
        "photo_hash",
        "is_active",
        "created_at",
        "updated_at",
        "archived_at",
        "archived_by",
    ]
    select_exprs = []
    for col in copy_columns:
        select_exprs.append(col if col in existing_columns else "null")
    bind.execute(
        sa.text(
            f"""
            insert into operators_165 (
                id, name, photo_path, photo_thumbnail_path, photo_hash, is_active,
                created_at, updated_at, archived_at, archived_by
            )
            select {", ".join(select_exprs)}
              from operators
            """
        )
    )
    bind.execute(
        sa.text(
            """
            update operators_165
               set normalized_name = upper(trim(name)),
                   origin = coalesce(origin, 'manual')
            """
        )
    )
    bind.execute(sa.text("drop table operators"))
    bind.execute(sa.text("alter table operators_165 rename to operators"))
    bind.execute(sa.text("create index if not exists ix_operators_name on operators(name)"))
    bind.execute(sa.text("create index if not exists ix_operators_is_active on operators(is_active)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def _add_column(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables()

    if "operators" in tables:
        _rebuild_operators_without_unique_name()
        _add_column("operators", sa.Column("normalized_name", sa.String(length=120), nullable=True))
        _add_column("operators", sa.Column("nickname", sa.String(length=100), nullable=True))
        _add_column("operators", sa.Column("sector_id", sa.String(length=36), nullable=True))
        _add_column("operators", sa.Column("origin", sa.String(length=30), nullable=True, server_default="manual"))
        _add_column("operators", sa.Column("created_by_operator_id", sa.String(length=36), nullable=True))
        _add_column("operators", sa.Column("archived_by_operator_id", sa.String(length=36), nullable=True))
        bind.execute(
            sa.text(
                """
                update operators
                   set normalized_name = upper(trim(name))
                 where normalized_name is null
                """
            )
        )
        if "ix_operators_normalized_name" not in _indexes("operators"):
            op.create_index("ix_operators_normalized_name", "operators", ["normalized_name"])

    if "asset_documents" in tables:
        _add_column("asset_documents", sa.Column("uploaded_by_operator_id", sa.String(length=36), nullable=True))
        _add_column("asset_documents", sa.Column("archived_by_operator_id", sa.String(length=36), nullable=True))
        _add_column("asset_documents", sa.Column("resolved_by_operator_id", sa.String(length=36), nullable=True))
        _add_column("asset_documents", sa.Column("resolved_at", sa.DateTime(), nullable=True))
        _add_column("asset_documents", sa.Column("review_reason", sa.String(length=255), nullable=True))
        _add_column("asset_documents", sa.Column("possible_assets_json", sa.Text(), nullable=True))

    if "file_organization_tasks" in tables:
        _add_column("file_organization_tasks", sa.Column("last_file", sa.String(length=1000), nullable=True))
        _add_column("file_organization_tasks", sa.Column("attempt", sa.Integer(), nullable=True, server_default="1"))
        _add_column("file_organization_tasks", sa.Column("pause_requested_at", sa.DateTime(), nullable=True))
        _add_column("file_organization_tasks", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
        _add_column("file_organization_tasks", sa.Column("checkpoint_json", sa.Text(), nullable=True))
        _add_column("file_organization_tasks", sa.Column("worker_id", sa.String(length=100), nullable=True))

    if "file_review_items" not in tables:
        op.create_table(
            "file_review_items",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("task_id", sa.String(length=36), nullable=True),
            sa.Column("source_path", sa.String(length=1000), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("extension", sa.String(length=20), nullable=True),
            sa.Column("mime_type", sa.String(length=100), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("file_hash", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("reason_code", sa.String(length=80), nullable=True),
            sa.Column("reason_message", sa.Text(), nullable=True),
            sa.Column("possible_assets_json", sa.Text(), nullable=True),
            sa.Column("suggested_asset_id", sa.String(length=36), nullable=True),
            sa.Column("selected_asset_id", sa.String(length=36), nullable=True),
            sa.Column("document_id", sa.String(length=36), nullable=True),
            sa.Column("resolved_by_operator_id", sa.String(length=36), nullable=True),
            sa.Column("resolved_by_name", sa.String(length=100), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_file_review_items_task_id", "file_review_items", ["task_id"])
        op.create_index("ix_file_review_items_status", "file_review_items", ["status"])
        op.create_index("ix_file_review_items_file_hash", "file_review_items", ["file_hash"])

    if "work_order_sequence" not in tables:
        op.create_table(
            "work_order_sequence",
            sa.Column("name", sa.String(length=50), primary_key=True),
            sa.Column("next_value", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    next_value = bind.execute(sa.text("select coalesce(max(friendly_number), 1000) + 1 from maintenance_orders")).scalar() or 1001
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
        {"next_value": int(next_value)},
    )

    if "quality_config" in _tables():
        bind.execute(
            sa.text(
                """
                INSERT INTO quality_config(key, value, updated_at)
                VALUES ('version', '1.6.5', datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "file_review_items" in _tables():
        op.drop_table("file_review_items")
    if "work_order_sequence" in _tables():
        op.drop_table("work_order_sequence")
    if "quality_config" in _tables():
        bind.execute(
            sa.text(
                """
                INSERT INTO quality_config(key, value, updated_at)
                VALUES ('version', '1.6.4', datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """
            )
        )
