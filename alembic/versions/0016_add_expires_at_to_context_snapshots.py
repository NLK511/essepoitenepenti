"""add expires_at to context snapshots

Revision ID: 0016_add_expires_at_to_context_snapshots
Revises: a71d15669f3f
Create Date: 2026-03-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_add_expires_at_to_context_snapshots"
down_revision = "a71d15669f3f"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _ensure_expires_at(table_name: str, index_name: str) -> None:
    if table_name not in _get_tables():
        return
    columns = _get_columns(table_name)
    if "expires_at" not in columns:
        op.add_column(table_name, sa.Column("expires_at", sa.DateTime(), nullable=True))
    indexes = _get_indexes(table_name)
    if index_name not in indexes:
        op.create_index(index_name, table_name, ["expires_at"], unique=False)


def upgrade() -> None:
    _ensure_expires_at("macro_context_snapshots", "ix_macro_context_snapshots_expires_at")
    _ensure_expires_at("industry_context_snapshots", "ix_industry_context_snapshots_expires_at")


def _drop_expires_at(table_name: str, index_name: str) -> None:
    if table_name not in _get_tables():
        return
    indexes = _get_indexes(table_name)
    if index_name in indexes:
        op.drop_index(index_name, table_name=table_name)
    columns = _get_columns(table_name)
    if "expires_at" in columns:
        op.drop_column(table_name, "expires_at")


def downgrade() -> None:
    _drop_expires_at("industry_context_snapshots", "ix_industry_context_snapshots_expires_at")
    _drop_expires_at("macro_context_snapshots", "ix_macro_context_snapshots_expires_at")
