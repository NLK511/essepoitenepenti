"""Add ingested_at to historical news items.

Revision ID: 0051_news_ingested_at
Revises: 0050_replay_eligibility_records
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_news_ingested_at"
down_revision = "0050_replay_eligibility_records"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    columns = _columns("historical_news_items")
    with op.batch_alter_table("historical_news_items") as batch_op:
        if "ingested_at" not in columns:
            batch_op.add_column(sa.Column("ingested_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE historical_news_items SET ingested_at = created_at WHERE ingested_at IS NULL")
    indexes = _indexes("historical_news_items")
    if "ix_historical_news_items_ingested_at" not in indexes:
        op.create_index(
            "ix_historical_news_items_ingested_at",
            "historical_news_items",
            ["ingested_at"],
        )


def downgrade() -> None:
    indexes = _indexes("historical_news_items")
    if "ix_historical_news_items_ingested_at" in indexes:
        op.drop_index("ix_historical_news_items_ingested_at", table_name="historical_news_items")
    columns = _columns("historical_news_items")
    with op.batch_alter_table("historical_news_items") as batch_op:
        if "ingested_at" in columns:
            batch_op.drop_column("ingested_at")
