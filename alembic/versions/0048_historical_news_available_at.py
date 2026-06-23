"""add point-in-time availability metadata to historical news

Revision ID: 0048_news_available_at
Revises: 0047_plan_tuning_eligible
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0048_news_available_at"
down_revision = "0047_plan_tuning_eligible"
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
        if "available_at" not in columns:
            batch_op.add_column(sa.Column("available_at", sa.DateTime(), nullable=True))
        if "availability_metadata_json" not in columns:
            batch_op.add_column(
                sa.Column("availability_metadata_json", sa.Text(), nullable=False, server_default="{}")
            )

    op.execute("UPDATE historical_news_items SET available_at = published_at WHERE available_at IS NULL")
    op.execute(
        """
        UPDATE historical_news_items
        SET availability_metadata_json = '{"available_at_inferred_from": "published_at", "point_in_time_confidence": 0.6}'
        WHERE availability_metadata_json IS NULL OR availability_metadata_json = '' OR availability_metadata_json = '{}'
        """
    )

    indexes = _indexes("historical_news_items")
    if "ix_historical_news_items_available_at" not in indexes:
        op.create_index(
            "ix_historical_news_items_available_at",
            "historical_news_items",
            ["available_at"],
            unique=False,
        )


def downgrade() -> None:
    indexes = _indexes("historical_news_items")
    if "ix_historical_news_items_available_at" in indexes:
        op.drop_index("ix_historical_news_items_available_at", table_name="historical_news_items")
    columns = _columns("historical_news_items")
    with op.batch_alter_table("historical_news_items") as batch_op:
        if "availability_metadata_json" in columns:
            batch_op.drop_column("availability_metadata_json")
        if "available_at" in columns:
            batch_op.drop_column("available_at")
