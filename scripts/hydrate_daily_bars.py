import sys
import logging
from datetime import datetime, timedelta, timezone
import yfinance as yf
import pandas as pd

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def hydrate_ticker(repo, ticker, as_of, days=90):
    start_at = as_of - timedelta(days=days)
    logger.info(f"Hydrating {ticker} from {start_at.date()} to {as_of.date()}...")
    
    try:
        df = yf.download(
            ticker,
            start=start_at.date().isoformat(),
            end=(as_of + timedelta(days=1)).date().isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=False
        )
        
        if df is None or df.empty:
            logger.warning(f"  No data for {ticker}")
            return
            
        # Handle MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            if ticker in df.columns.get_level_values(1):
                df = df.xs(ticker, axis=1, level=1)
            elif ticker in df.columns.get_level_values(0):
                df = df.xs(ticker, axis=1, level=0)

        bars = []
        for timestamp, row in df.iterrows():
            bar_time = timestamp if isinstance(timestamp, datetime) else pd.to_datetime(timestamp)
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
                
            bars.append(HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=bar_time,
                available_at=datetime.combine(bar_time.date(), datetime.max.time(), tzinfo=timezone.utc),
                open_price=float(row["Open"]),
                high_price=float(row["High"]),
                low_price=float(row["Low"]),
                close_price=float(row["Close"]),
                volume=int(row["Volume"]),
                source="manual_hydration",
                source_tier="tier_a",
                point_in_time_confidence=1.0,
            ))
        
        if bars:
            cnt = repo.upsert_bars(bars)
            logger.info(f"  Persisted {cnt} bars for {ticker}")
            
    except Exception as e:
        logger.error(f"  Error hydrating {ticker}: {e}")

def main():
    as_of = datetime(2026, 4, 13, tzinfo=timezone.utc)
    
    with SessionLocal() as session:
        repo = HistoricalMarketDataRepository(session)
        wl_repo = WatchlistRepository(session)
        
        watchlists = wl_repo.list_all()
        
        tickers = set()
        for wl in watchlists:
            # Skip the massive reference watchlists for now to ensure we finish main ones
            if len(wl.tickers) > 100:
                continue
            tickers.update(wl.tickers)
        
        sorted_tickers = sorted(list(tickers))
        logger.info(f"Found {len(sorted_tickers)} unique tickers to hydrate")
        
        for i, ticker in enumerate(sorted_tickers):
            logger.info(f"Progress: {i+1}/{len(sorted_tickers)}")
            hydrate_ticker(repo, ticker, as_of)

if __name__ == "__main__":
    main()
