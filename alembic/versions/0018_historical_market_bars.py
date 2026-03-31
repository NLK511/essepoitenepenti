"""add historical market bars table

Revision ID: 0018_historical_market_bars
Revises: 0017_historical_replay_batches
Create Date: 2026-03-24 00:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_historical_market_bars"
down_revision = "0017_historical_replay_batches"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    tables = _get_tables()
    if "historical_market_bars" in tables:
        return
    op.create_table(
        "historical_market_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False, server_default="1d"),
        sa.Column("bar_time", sa.DateTime(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("high_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("low_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("close_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
        sa.Column("adjusted_close", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("source_tier", sa.String(length=32), nullable=False, server_default="tier_a"),
        sa.Column("point_in_time_confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("ticker", "timeframe", "bar_time", name="uq_historical_market_bars_ticker_timeframe_bar_time"),
    )
    op.create_index("ix_historical_market_bars_ticker", "historical_market_bars", ["ticker"], unique=False)
    op.create_index("ix_historical_market_bars_timeframe", "historical_market_bars", ["timeframe"], unique=False)
    op.create_index("ix_historical_market_bars_bar_time", "historical_market_bars", ["bar_time"], unique=False)


def downgrade() -> None:
    tables = _get_tables()
    if "historical_market_bars" not in tables:
        return
    indexes = _get_indexes("historical_market_bars")
    for index_name in (
        "ix_historical_market_bars_bar_time",
        "ix_historical_market_bars_timeframe",
        "ix_historical_market_bars_ticker",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="historical_market_bars")
    op.drop_table("historical_market_bars")
