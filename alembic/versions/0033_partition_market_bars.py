"""partition_historical_market_bars

Revision ID: 23f22508e92b
Revises: 0023_context_refresh_cleanup
Create Date: 2026-04-12 14:20:37.283235
"""
from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '23f22508e92b'
down_revision = '0023_context_refresh_cleanup'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get the database dialect
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == 'postgresql'

    if not is_postgresql:
        # For non-Postgres (SQLite), we just ensure the indices and unique constraints match,
        # but partitioning is not supported.
        return

    # 1. Rename existing table to a backup
    op.rename_table('historical_market_bars', 'historical_market_bars_old')

    # 2. Create the new partitioned table
    # Note: bar_time MUST be part of the primary/unique key for partitioning
    op.execute("""
        CREATE TABLE historical_market_bars (
            id SERIAL,
            ticker VARCHAR(32) NOT NULL,
            timeframe VARCHAR(16) NOT NULL,
            bar_time TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ,
            open_price FLOAT NOT NULL,
            high_price FLOAT NOT NULL,
            low_price FLOAT NOT NULL,
            close_price FLOAT NOT NULL,
            volume FLOAT NOT NULL,
            adjusted_close FLOAT,
            source VARCHAR(64),
            source_tier VARCHAR(32),
            point_in_time_confidence FLOAT,
            metadata_json TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (ticker, timeframe, bar_time)
        ) PARTITION BY RANGE (bar_time);
    """)

    # 3. Create indices on the partitioned table
    op.create_index('ix_bars_bar_time', 'historical_market_bars', ['bar_time'])
    op.create_index('ix_bars_ticker', 'historical_market_bars', ['ticker'])

    # 4. Create initial partitions (2024 - 2026)
    for year in [2024, 2025, 2026]:
        for month in range(1, 13):
            partition_name = f"historical_market_bars_y{year}_m{month:02d}"
            start_date = f"{year}-{month:02d}-01"
            
            # Calculate end date
            if month == 12:
                end_year, end_month = year + 1, 1
            else:
                end_year, end_month = year, month + 1
            end_date = f"{end_year}-{end_month:02d}-01"
            
            op.execute(f"""
                CREATE TABLE {partition_name} 
                PARTITION OF historical_market_bars 
                FOR VALUES FROM ('{start_date}') TO ('{end_date}');
            """)

    # 5. Migrate data from old table to new
    op.execute("""
        INSERT INTO historical_market_bars (
            ticker, timeframe, bar_time, available_at, open_price, high_price, 
            low_price, close_price, volume, adjusted_close, source, source_tier, 
            point_in_time_confidence, metadata_json, created_at, updated_at
        ) 
        SELECT 
            ticker, timeframe, bar_time, available_at, open_price, high_price, 
            low_price, close_price, volume, adjusted_close, source, source_tier, 
            point_in_time_confidence, metadata_json, created_at, updated_at
        FROM historical_market_bars_old
        ON CONFLICT (ticker, timeframe, bar_time) DO NOTHING;
    """)

    # 6. Drop old table
    op.drop_table('historical_market_bars_old')


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    # To downgrade, we have to recreate the non-partitioned table
    op.execute("""
        CREATE TABLE historical_market_bars_new (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(32) NOT NULL,
            timeframe VARCHAR(16) NOT NULL,
            bar_time TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ,
            open_price FLOAT NOT NULL,
            high_price FLOAT NOT NULL,
            low_price FLOAT NOT NULL,
            close_price FLOAT NOT NULL,
            volume FLOAT NOT NULL,
            adjusted_close FLOAT,
            source VARCHAR(64),
            source_tier VARCHAR(32),
            point_in_time_confidence FLOAT,
            metadata_json TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_historical_market_bars_ticker_timeframe_bar_time UNIQUE (ticker, timeframe, bar_time)
        );
    """)

    op.execute("""
        INSERT INTO historical_market_bars_new (
            ticker, timeframe, bar_time, available_at, open_price, high_price, 
            low_price, close_price, volume, adjusted_close, source, source_tier, 
            point_in_time_confidence, metadata_json, created_at, updated_at
        )
        SELECT * FROM historical_market_bars;
    """)

    op.drop_table('historical_market_bars')
    op.rename_table('historical_market_bars_new', 'historical_market_bars')
