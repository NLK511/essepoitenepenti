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

        # 2. Define standard time window
        end_date = datetime.now(timezone.utc)
        default_start_date = end_date - timedelta(days=6)
        
        total_ingested = 0
        
        for i, ticker in enumerate(tickers):
            # Check latest bar in DB for this ticker
            latest_bar_time = session.query(func.max(HistoricalMarketBarRecord.bar_time))\
                .filter(HistoricalMarketBarRecord.ticker == ticker)\
                .filter(HistoricalMarketBarRecord.timeframe == "1m")\
                .scalar()
            
            if latest_bar_time:
                # If latest bar is within the last 7 days, start from there + 1 minute
                # Otherwise, stay with the default 7-day lookback.
                if latest_bar_time.tzinfo is None:
                    latest_bar_time = latest_bar_time.replace(tzinfo=timezone.utc)
                
                start_date = max(default_start_date, latest_bar_time + timedelta(minutes=1))
            else:
                start_date = default_start_date

            # If start_date is too close to now (e.g. less than 10 mins ago), skip
            if (end_date - start_date).total_seconds() < 600:
                print(f"[{i+1}/{len(tickers)}] {ticker} is already up to date. Skipping.")
                continue

            start_str = start_date.strftime("%Y-%m-%d")
            end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
            
            print(f"[{i+1}/{len(tickers)}] Processing {ticker} (from {start_date.isoformat()} to {end_str})...")
            
            try:
                df = yf.download(
                    ticker,
                    start=start_str,
                    end=end_str,
                    interval="1m",
                    progress=False,
                    auto_adjust=False,
                )
                
                if df is None or df.empty:
                    print(f"  No data returned for {ticker}.")
                    continue

                # Flatten MultiIndex columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    if ticker in df.columns.get_level_values(1):
                        df = df.xs(ticker, axis=1, level=1)
                    elif ticker in df.columns.get_level_values(0):
                        df = df.xs(ticker, axis=1, level=0)
                    else:
                        standard_cols = {'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume'}
                        for level in range(df.columns.nlevels):
                            if any(col in standard_cols for col in df.columns.get_level_values(level)):
                                df.columns = df.columns.get_level_values(level)
                                break

                # Filter out rows before start_date (Yahoo sometimes returns a bit more)
                df = df[df.index >= start_date]

                if df.empty:
                    print(f"  No new bars for {ticker} since {start_date.isoformat()}.")
                    continue

                bars_to_upsert = []
                for timestamp, row in df.iterrows():
                    bar = create_bar(ticker, timestamp, row, "1m")
                    if bar:
                        bars_to_upsert.append(bar)

                if bars_to_upsert:
                    sub_batch_size = 1000
                    for j in range(0, len(bars_to_upsert), sub_batch_size):
                        sub_batch = bars_to_upsert[j : j + sub_batch_size]
                        market_data.upsert_bars(sub_batch)
                    
                    total_ingested += len(bars_to_upsert)
                    print(f"  Ingested {len(bars_to_upsert)} new bars.")
                else:
                    print(f"  No valid bars found for {ticker}.")
                
                del df
                del bars_to_upsert
                gc.collect()

            except Exception as e:
                print(f"  Error processing {ticker}: {e}")

        print(f"Bulk load complete. Total new 1m bars ingested: {total_ingested}")

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
            
        available_at = bar_time + timedelta(minutes=1)
        
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
