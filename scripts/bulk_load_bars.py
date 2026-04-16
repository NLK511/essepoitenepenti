import os
import sys
import pandas as pd
import yfinance as yf
import gc
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker

# Add the src directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord

def bulk_load_bars():
    print(f"Connecting to database...")
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    print(f"Using database URL: {db_url}")
    
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    market_data = HistoricalMarketDataRepository(session)

    try:
        # 1. Get all tickers from watchlists
        tickers = list(set([
            t.strip().upper() 
            for r in session.execute(text('SELECT tickers_csv FROM watchlists')) 
            for t in r[0].split(',') if t.strip()
        ]))
        print(f"Found {len(tickers)} unique tickers in watchlists.")

        if not tickers:
            print("No tickers found in watchlists. Aborting.")
            return

        # 2. Ingest both 1m and 1d bars
        for timeframe in ["1d", "1m"]: # Do 1d first as it is more critical for signals
            lookback_days = 60 if timeframe == "1d" else 7
            print(f"--- Ingesting {timeframe} bars (lookback {lookback_days} days) ---")
            
            end_date = datetime.now(timezone.utc)
            default_start_date = end_date - timedelta(days=lookback_days)
            total_ingested = 0

            for i, ticker in enumerate(tickers):
                # Check latest bar in DB
                latest_bar_time = session.query(func.max(HistoricalMarketBarRecord.bar_time))\
                    .filter(HistoricalMarketBarRecord.ticker == ticker)\
                    .filter(HistoricalMarketBarRecord.timeframe == timeframe)\
                    .scalar()
                
                if latest_bar_time:
                    if latest_bar_time.tzinfo is None:
                        latest_bar_time = latest_bar_time.replace(tzinfo=timezone.utc)
                    start_date = max(default_start_date, latest_bar_time + timedelta(minutes=1 if timeframe == "1m" else 1440))
                else:
                    start_date = default_start_date

                # Skip if up to date
                gap_threshold = 600 if timeframe == "1m" else 43200
                if (end_date - start_date).total_seconds() < gap_threshold:
                    continue

                start_str = start_date.strftime("%Y-%m-%d")
                end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
                
                try:
                    df = yf.download(
                        ticker,
                        start=start_str,
                        end=end_str,
                        interval=timeframe,
                        progress=False,
                        auto_adjust=False,
                    )
                    
                    if df is None or df.empty:
                        continue

                    if isinstance(df.columns, pd.MultiIndex):
                        if ticker in df.columns.get_level_values(1):
                            df = df.xs(ticker, axis=1, level=1)
                        elif ticker in df.columns.get_level_values(0):
                            df = df.xs(ticker, axis=1, level=0)

                    # Ensure timezone consistency for comparison
                    if df.index.tz is None:
                        df.index = df.index.tz_localize(timezone.utc)
                    else:
                        df.index = df.index.tz_convert(timezone.utc)

                    # Use pd.Timestamp for safe comparison
                    ts_start = pd.Timestamp(start_date)
                    df = df[df.index >= ts_start]

                    if df.empty:
                        continue

                    bars_to_upsert = []
                    for timestamp, row in df.iterrows():
                        bar = create_bar(ticker, timestamp, row, timeframe)
                        if bar:
                            bars_to_upsert.append(bar)

                    if bars_to_upsert:
                        print(f"[{i+1}/{len(tickers)}] {ticker} {timeframe}: {len(bars_to_upsert)} bars")
                        market_data.upsert_bars(bars_to_upsert)
                        total_ingested += len(bars_to_upsert)
                    
                    del df
                    del bars_to_upsert
                    gc.collect()

                except Exception as e:
                    print(f"  Error processing {ticker} {timeframe}: {e}")

            print(f"Finished {timeframe}. Ingested {total_ingested} bars.")

    finally:
        session.close()

def create_bar(ticker, timestamp, row, timeframe):
    try:
        row_dict = {str(k).strip(): v for k, v in row.to_dict().items()}
        close_val = row_dict.get('Close') or row_dict.get('Adj Close')
        if close_val is None or pd.isna(close_val):
            return None
        
        open_val = row_dict.get('Open', close_val)
        high_val = row_dict.get('High', close_val)
        low_val = row_dict.get('Low', close_val)
        vol_val = row_dict.get('Volume', 0.0)

        bar_time = timestamp.to_pydatetime()
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        else:
            bar_time = bar_time.astimezone(timezone.utc)
            
        if timeframe == "1m":
            available_at = bar_time + timedelta(minutes=1)
        else:
            available_at = datetime.combine(bar_time.date(), datetime.max.time(), tzinfo=timezone.utc)
        
        return HistoricalMarketBar(
            ticker=ticker,
            timeframe=timeframe,
            bar_time=bar_time,
            available_at=available_at,
            open_price=float(open_val),
            high_price=float(high_val),
            low_price=float(low_val),
            close_price=float(close_val),
            volume=float(vol_val) if not pd.isna(vol_val) else 0.0,
            source="yfinance_bulk_load",
        )
    except Exception:
        return None

if __name__ == "__main__":
    bulk_load_bars()
