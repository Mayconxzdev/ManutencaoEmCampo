"""version 1.7.0 search and AI capabilities

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d1
Create Date: 2026-07-02
"""
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS global_search_fts USING fts5(
                entity_type,
                entity_id UNINDEXED,
                title,
                body,
                metadata UNINDEXED,
                tokenize = 'unicode61 remove_diacritics 2'
            )
        """)
    try:
        op.execute("insert or replace into quality_config(key, value, updated_at) values ('version', '1.7.0', datetime('now'))")
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS global_search_fts")
    try:
        op.execute("update quality_config set value = '1.6.8', updated_at = datetime('now') where key = 'version'")
    except Exception:
        pass
