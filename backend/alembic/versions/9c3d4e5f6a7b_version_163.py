"""version 1.6.3 asset files and operational fixes

Revision ID: 9c3d4e5f6a7b
Revises: 8b2c3d4e5f6a
Create Date: 2026-06-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9c3d4e5f6a7b"
down_revision = "8b2c3d4e5f6a"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing("operators", sa.Column("photo_path", sa.String(length=1000), nullable=True))
    _add_column_if_missing("operators", sa.Column("photo_thumbnail_path", sa.String(length=1000), nullable=True))
    _add_column_if_missing("operators", sa.Column("photo_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("operators", sa.Column("is_active", sa.Boolean(), nullable=True))
    _add_column_if_missing("operators", sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("operators", sa.Column("updated_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("operators", sa.Column("archived_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("operators", sa.Column("archived_by", sa.String(length=100), nullable=True))

    _add_column_if_missing("asset_documents", sa.Column("original_name", sa.String(length=255), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("extension", sa.String(length=20), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("mime_type", sa.String(length=100), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("file_size", sa.Integer(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("file_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("category", sa.String(length=50), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("origin", sa.String(length=50), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("original_path", sa.String(length=1000), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("internal_path", sa.String(length=1000), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("thumbnail_path", sa.String(length=1000), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("width", sa.Integer(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("height", sa.Integer(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("imported_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("uploaded_by", sa.String(length=100), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("status", sa.String(length=30), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("is_primary_photo", sa.Boolean(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("archived_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("archived_by", sa.String(length=100), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("review_status", sa.String(length=50), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("suggested_asset_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("asset_documents", sa.Column("source_index_id", sa.String(length=36), nullable=True))

    bind = op.get_bind()
    index_names = {row[1] for row in bind.execute(sa.text("PRAGMA index_list(asset_documents)")).fetchall()}
    if "ix_asset_documents_file_hash" not in index_names:
        op.create_index("ix_asset_documents_file_hash", "asset_documents", ["file_hash"])
    if "ix_asset_documents_status" not in index_names:
        op.create_index("ix_asset_documents_status", "asset_documents", ["status"])

    operator_index_names = {row[1] for row in bind.execute(sa.text("PRAGMA index_list(operators)")).fetchall()}
    if "ix_operators_is_active" not in operator_index_names:
        op.create_index("ix_operators_is_active", "operators", ["is_active"])

    bind.execute(sa.text("UPDATE asset_documents SET status = 'active' WHERE status IS NULL"))
    bind.execute(sa.text("UPDATE asset_documents SET original_name = name WHERE original_name IS NULL"))
    bind.execute(sa.text("UPDATE asset_documents SET internal_path = file_path WHERE internal_path IS NULL AND file_path IS NOT NULL"))
    bind.execute(sa.text("UPDATE asset_documents SET mime_type = file_type WHERE mime_type IS NULL AND file_type IS NOT NULL"))
    bind.execute(sa.text("UPDATE asset_documents SET imported_at = uploaded_at WHERE imported_at IS NULL AND uploaded_at IS NOT NULL"))
    bind.execute(sa.text("UPDATE asset_documents SET category = 'other' WHERE category IS NULL"))
    bind.execute(sa.text("UPDATE operators SET is_active = 1 WHERE is_active IS NULL"))
    bind.execute(sa.text("UPDATE operators SET created_at = datetime('now') WHERE created_at IS NULL"))

    bind.execute(
        sa.text(
            """
            INSERT INTO quality_config(key, value, updated_at)
            VALUES ('version', '1.6.3', datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO quality_config(key, value, updated_at)
            VALUES ('version', '1.6.2', datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """
        )
    )
