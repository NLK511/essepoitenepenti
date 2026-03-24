"""add watchlist metadata

Revision ID: 0012_watchlist_metadata
Revises: 0011_sentiment_snapshot_summaries
Create Date: 2026-03-24 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_watchlist_metadata"
down_revision = "0011_sentiment_snapshot_summaries"
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


def upgrade() -> None:
    tables = _get_tables()
    if "watchlists" not in tables:
        return

    columns = _get_columns("watchlists")
    additions = (
        ("description", sa.Text(), ""),
        ("region", sa.String(length=64), ""),
        ("exchange", sa.String(length=64), ""),
        ("timezone", sa.String(length=64), ""),
        ("default_horizon", sa.String(length=8), "1w"),
        ("allow_shorts", sa.Boolean(), sa.true()),
        ("optimize_evaluation_timing", sa.Boolean(), sa.false()),
    )
    for name, column_type, default in additions:
        if name in columns:
            continue
        op.add_column(
            "watchlists",
            sa.Column(name, column_type, nullable=False, server_default=default),
        )


def downgrade() -> None:
    tables = _get_tables()
    if "watchlists" not in tables:
        return

    columns = _get_columns("watchlists")
    for name in (
        "optimize_evaluation_timing",
        "allow_shorts",
        "default_horizon",
        "timezone",
        "exchange",
        "region",
        "description",
    ):
        if name in columns:
            op.drop_column("watchlists", name)
