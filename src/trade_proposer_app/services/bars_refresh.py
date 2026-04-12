import logging
import pandas as pd
import yfinance as yf
import gc
from datetime import datetime, timedelta, timezone
from sqlalchemy import func

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord

logger = logging.getLogger(__name__)

class BarsRefreshService:
    def __init__(self, repository: HistoricalMarketDataRepository):
        self.repository = repository

    def refresh_bars(self, tickers: list[str], lookback_days: int = 6) -> dict[str, object]:
        end_date = datetime.now(timezone.utc)
        default_start_date = end_date - timedelta(days=lookback_days)
        total_ingested = 0
        stats = {}
        warnings = []

        for ticker in tickers:
            try:
                # Get latest bar time from DB
                latest_bar_time = self.repository.session.query(func.max(HistoricalMarketBarRecord.bar_time))\
                    .filter(HistoricalMarketBarRecord.ticker == ticker)\
                    .filter(HistoricalMarketBarRecord.timeframe == "1m")\
                    .scalar()
                
                if latest_bar_time:
                    if latest_bar_time.tzinfo is None:
                        latest_bar_time = latest_bar_time.replace(tzinfo=timezone.utc)
                    start_date = max(default_start_date, latest_bar_time + timedelta(minutes=1))
                else:
                    start_date = default_start_date

                # If already up to date, skip
                if (end_date - start_date).total_seconds() < 600:
                    stats[ticker] = 0
                    continue

                start_str = start_date.strftime("%Y-%m-%d")
                end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")

                df = yf.download(
                    ticker,
                    start=start_str,
                    end=end_str,
                    interval="1m",
                    progress=False,
                    auto_adjust=False,
                )

                if df is None or df.empty:
                    warnings.append(f"{ticker}: No data returned from Yahoo (possible delisting or holiday)")
                    stats[ticker] = 0
                    continue

                # Handle MultiIndex
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
                
                df = df[df.index >= start_date]
                if df.empty:
                    stats[ticker] = 0
                    continue

                bars_to_upsert = []
                for timestamp, row in df.iterrows():
                    bar = self._create_bar_model(ticker, timestamp, row)
                    if bar:
                        bars_to_upsert.append(bar)

                if bars_to_upsert:
                    sub_batch_size = 1000
                    for j in range(0, len(bars_to_upsert), sub_batch_size):
                        self.repository.upsert_bars(bars_to_upsert[j : j + sub_batch_size])
                    
                    total_ingested += len(bars_to_upsert)
                    stats[ticker] = len(bars_to_upsert)
                else:
                    stats[ticker] = 0
                
                del df
                del bars_to_upsert
                gc.collect()

            except Exception as e:
                logger.error(f"Failed to refresh bars for {ticker}: {e}")
                warnings.append(f"{ticker}: Error during refresh: {str(e)}")
                stats[ticker] = -1

        return {
            "total_ingested": total_ingested,
            "ticker_stats": stats,
            "warnings": warnings,
            "refreshed_at": end_date.isoformat(),
        }

    def _create_bar_model(self, ticker: str, timestamp: datetime, row: pd.Series) -> HistoricalMarketBar | None:
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
                timeframe="1m",
                bar_time=bar_time,
                available_at=available_at,
                open_price=float(open_val),
                high_price=float(high_val),
                low_price=float(low_val),
                close_price=float(close_val),
                volume=float(vol_val) if not pd.isna(vol_val) else 0.0,
                source="yfinance_refresh",
            )
        except Exception:
            return None
