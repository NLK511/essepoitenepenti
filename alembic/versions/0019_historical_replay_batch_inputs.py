"""extend historical replay batch inputs and market bar availability

Revision ID: 0019_historical_replay_batch_inputs
Revises: 0018_historical_market_bars
Create Date: 2026-03-24 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_historical_replay_batch_inputs"
down_revision = "0018_historical_market_bars"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    replay_columns = _get_columns("historical_replay_batches")
    if "universe_mode" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("universe_mode", sa.String(length=32), nullable=False, server_default="explicit"))
    if "universe_preset" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("universe_preset", sa.String(length=120), nullable=True))
    if "tickers_json" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("tickers_json", sa.Text(), nullable=False, server_default="[]"))
    if "entry_timing" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("entry_timing", sa.String(length=32), nullable=False, server_default="next_open"))
    if "price_provider" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("price_provider", sa.String(length=64), nullable=False, server_default="yahoo"))
    if "price_source_tier" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("price_source_tier", sa.String(length=32), nullable=False, server_default="research"))
    if "bar_timeframe" not in replay_columns:
        op.add_column("historical_replay_batches", sa.Column("bar_timeframe", sa.String(length=16), nullable=False, server_default="1d"))

    replay_indexes = _get_indexes("historical_replay_batches")
    if "ix_historical_replay_batches_universe_preset" not in replay_indexes:
        op.create_index("ix_historical_replay_batches_universe_preset", "historical_replay_batches", ["universe_preset"], unique=False)

    market_columns = _get_columns("historical_market_bars")
    if "available_at" not in market_columns:
        op.add_column("historical_market_bars", sa.Column("available_at", sa.DateTime(), nullable=True))
        op.execute("UPDATE historical_market_bars SET available_at = bar_time WHERE available_at IS NULL")

    market_indexes = _get_indexes("historical_market_bars")
    if "ix_historical_market_bars_available_at" not in market_indexes:
        op.create_index("ix_historical_market_bars_available_at", "historical_market_bars", ["available_at"], unique=False)


def downgrade() -> None:
    market_columns = _get_columns("historical_market_bars")
    market_indexes = _get_indexes("historical_market_bars")
    if "ix_historical_market_bars_available_at" in market_indexes:
        op.drop_index("ix_historical_market_bars_available_at", table_name="historical_market_bars")
    if "available_at" in market_columns:
        op.drop_column("historical_market_bars", "available_at")

    replay_indexes = _get_indexes("historical_replay_batches")
    if "ix_historical_replay_batches_universe_preset" in replay_indexes:
        op.drop_index("ix_historical_replay_batches_universe_preset", table_name="historical_replay_batches")

    replay_columns = _get_columns("historical_replay_batches")
    for column_name in (
        "bar_timeframe",
        "price_source_tier",
        "price_provider",
        "entry_timing",
        "tickers_json",
        "universe_preset",
        "universe_mode",
    ):
        if column_name in replay_columns:
            op.drop_column("historical_replay_batches", column_name)
