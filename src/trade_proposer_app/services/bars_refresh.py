import gc
import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy import func

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.retry_utils import bounded_backoff_seconds

logger = logging.getLogger(__name__)


class BarsRefreshService:
    MAX_REFRESH_ATTEMPTS = 3
    REFRESH_RETRY_BACKOFF_SECONDS = (0.0, 1.0, 2.0)

    def __init__(self, repository: HistoricalMarketDataRepository):
        self.repository = repository

    def refresh_bars(self, tickers: list[str], lookback_days: int = 6) -> dict[str, object]:
        end_date = datetime.now(timezone.utc)
        default_start_date = end_date - timedelta(days=lookback_days)
        total_ingested = 0
        stats: dict[str, int] = {}
        warnings: list[str] = []
        retry_diagnostics: dict[str, dict[str, object]] = {}
        pending = list(dict.fromkeys(tickers))
        final_outcomes: dict[str, dict[str, object]] = {}

        logger.info(
            "Starting bars refresh for %s tickers (lookback %s days, max attempts %s)",
            len(pending),
            lookback_days,
            self.MAX_REFRESH_ATTEMPTS,
        )

        for attempt_index in range(self.MAX_REFRESH_ATTEMPTS):
            if not pending:
                break

            backoff = bounded_backoff_seconds(self.REFRESH_RETRY_BACKOFF_SECONDS, attempt_index)
            if attempt_index > 0 and backoff > 0:
                time.sleep(backoff)

            attempt_number = attempt_index + 1
            logger.info(
                "Bars refresh attempt %s/%s for %s unresolved tickers",
                attempt_number,
                self.MAX_REFRESH_ATTEMPTS,
                len(pending),
            )

            current_batch = pending
            pending = []
            for ticker_index, ticker in enumerate(current_batch, start=1):
                outcome = self._refresh_single_ticker(
                    ticker=ticker,
                    ticker_index=ticker_index,
                    ticker_count=len(current_batch),
                    default_start_date=default_start_date,
                    end_date=end_date,
                )
                final_outcomes[ticker] = outcome
                retry_diagnostics.setdefault(ticker, {"attempt_count": 0, "attempts": []})
                retry_diagnostics[ticker]["attempt_count"] = int(retry_diagnostics[ticker]["attempt_count"]) + 1
                retry_diagnostics[ticker]["attempts"].append(
                    {
                        "attempt": attempt_number,
                        "status": outcome["status"],
                        "ingested": outcome["ingested"],
                        "message": outcome.get("message"),
                    }
                )

                if outcome["status"] in {"success", "up_to_date", "no_new_bars", "no_valid_bars"}:
                    stats[ticker] = int(outcome["ingested"])
                    total_ingested += int(outcome["ingested"])
                    continue

                logger.warning(
                    "Bars refresh unresolved for %s on attempt %s/%s: %s",
                    ticker,
                    attempt_number,
                    self.MAX_REFRESH_ATTEMPTS,
                    outcome.get("message") or outcome["status"],
                )
                pending.append(ticker)

        for ticker, outcome in final_outcomes.items():
            status = str(outcome["status"])
            if status == "error":
                stats[ticker] = -1
                warnings.append(
                    f"{ticker}: Error during refresh after {retry_diagnostics[ticker]['attempt_count']} attempts: {outcome.get('message') or 'unknown error'}"
                )
            elif status == "empty":
                stats[ticker] = 0
                warnings.append(
                    f"{ticker}: No data returned from Yahoo after {retry_diagnostics[ticker]['attempt_count']} attempts"
                )
            else:
                stats.setdefault(ticker, int(outcome["ingested"]))

        logger.info("Bars refresh complete. Total ingested: %s", total_ingested)
        return {
            "total_ingested": total_ingested,
            "ticker_stats": stats,
            "warnings": warnings,
            "retry_diagnostics": retry_diagnostics,
            "refreshed_at": end_date.isoformat(),
        }

    def _refresh_single_ticker(
        self,
        *,
        ticker: str,
        ticker_index: int,
        ticker_count: int,
        default_start_date: datetime,
        end_date: datetime,
    ) -> dict[str, object]:
        try:
            latest_bar_time = (
                self.repository.session.query(func.max(HistoricalMarketBarRecord.bar_time))
                .filter(HistoricalMarketBarRecord.ticker == ticker)
                .filter(HistoricalMarketBarRecord.timeframe == "1m")
                .scalar()
            )

            if latest_bar_time:
                if latest_bar_time.tzinfo is None:
                    latest_bar_time = latest_bar_time.replace(tzinfo=timezone.utc)
                start_date = max(default_start_date, latest_bar_time + timedelta(minutes=1))
            else:
                start_date = default_start_date

            if (end_date - start_date).total_seconds() < 600:
                logger.debug("[%s/%s] %s is already up to date", ticker_index, ticker_count, ticker)
                return {"status": "up_to_date", "ingested": 0, "message": None}

            logger.info(
                "[%s/%s] Refreshing %s since %s",
                ticker_index,
                ticker_count,
                ticker,
                start_date.isoformat(),
            )

            df = self._download_bars(ticker=ticker, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return {
                    "status": "empty",
                    "ingested": 0,
                    "message": f"{ticker}: No data returned from Yahoo",
                }

            df = self._normalize_downloaded_frame(ticker, df)
            df = df[df.index >= start_date]
            if df.empty:
                logger.info("  No new bars found for %s", ticker)
                return {"status": "no_new_bars", "ingested": 0, "message": None}

            bars_to_upsert: list[HistoricalMarketBar] = []
            for timestamp, row in df.iterrows():
                bar = self._create_bar_model(ticker, timestamp, row)
                if bar:
                    bars_to_upsert.append(bar)

            if not bars_to_upsert:
                logger.info("  No valid bars processed for %s", ticker)
                return {"status": "no_valid_bars", "ingested": 0, "message": None}

            logger.info("  Ingesting %s bars for %s", len(bars_to_upsert), ticker)
            sub_batch_size = 1000
            for index in range(0, len(bars_to_upsert), sub_batch_size):
                self.repository.upsert_bars(bars_to_upsert[index : index + sub_batch_size])

            ingested = len(bars_to_upsert)
            del df
            del bars_to_upsert
            gc.collect()
            return {"status": "success", "ingested": ingested, "message": None}
        except Exception as exc:
            logger.error("Failed to refresh bars for %s: %s", ticker, exc)
            return {
                "status": "error",
                "ingested": 0,
                "message": str(exc),
            }

    @staticmethod
    def _download_bars(*, ticker: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
        return yf.download(
            ticker,
            start=start_str,
            end=end_str,
            interval="1m",
            progress=False,
            auto_adjust=False,
        )

    @staticmethod
    def _normalize_downloaded_frame(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(df.columns, pd.MultiIndex):
            return df
        if ticker in df.columns.get_level_values(1):
            return df.xs(ticker, axis=1, level=1)
        if ticker in df.columns.get_level_values(0):
            return df.xs(ticker, axis=1, level=0)

        standard_cols = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        for level in range(df.columns.nlevels):
            if any(col in standard_cols for col in df.columns.get_level_values(level)):
                normalized = df.copy()
                normalized.columns = normalized.columns.get_level_values(level)
                return normalized
        return df

    def _create_bar_model(self, ticker: str, timestamp: datetime, row: pd.Series) -> HistoricalMarketBar | None:
        try:
            row_dict = {str(k).strip(): v for k, v in row.to_dict().items()}
            close_val = row_dict.get("Close") or row_dict.get("Adj Close")
            if close_val is None or pd.isna(close_val):
                return None

            open_val = row_dict.get("Open", close_val)
            high_val = row_dict.get("High", close_val)
            low_val = row_dict.get("Low", close_val)
            vol_val = row_dict.get("Volume", 0.0)

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
