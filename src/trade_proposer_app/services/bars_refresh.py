import logging
import time
from datetime import datetime, time as datetime_time, timedelta, timezone

from sqlalchemy import func

from trade_proposer_app.persistence.models import HistoricalMarketBarRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.historical_bars_access import HistoricalBarsAccessService
from trade_proposer_app.services.historical_market_data import HistoricalBarProvider, HistoricalMarketDataService
from trade_proposer_app.services.retry_utils import bounded_backoff_seconds

logger = logging.getLogger(__name__)


class BarsRefreshService:
    MAX_REFRESH_ATTEMPTS = 3
    REFRESH_RETRY_BACKOFF_SECONDS = (0.0, 1.0, 2.0)

    def __init__(self, repository: HistoricalMarketDataRepository, provider: HistoricalBarProvider | None = None):
        self.repository = repository
        self.market_data = HistoricalMarketDataService(repository, provider=provider)
        self.bars_access = HistoricalBarsAccessService(self.market_data)

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

        coverage = self._refresh_coverage(tickers=list(dict.fromkeys(tickers)), start_at=default_start_date, end_at=end_date)
        logger.info("Bars refresh complete. Total ingested: %s", total_ingested)
        return {
            "total_ingested": total_ingested,
            "ticker_stats": stats,
            "warnings": warnings,
            "retry_diagnostics": retry_diagnostics,
            "refreshed_at": end_date.isoformat(),
            "input_access": {
                "service": "HistoricalBarsAccessService",
                "policy": "cache_only",
                "coverage": coverage,
            },
        }

    def _refresh_coverage(self, *, tickers: list[str], start_at: datetime, end_at: datetime) -> dict[str, object]:
        by_ticker: dict[str, dict[str, object]] = {}
        covered = 0
        for ticker in tickers:
            result = self.bars_access.intraday_1m_bars(
                ticker=ticker,
                start_at=start_at,
                end_at=end_at,
                available_at=end_at,
                limit=1,
                policy="cache_only",
            )
            by_ticker[ticker] = result.coverage
            by_ticker[ticker]["recent_sessions"] = self._recent_session_coverage(ticker, end_at=end_at)
            if result.coverage.get("covered"):
                covered += 1
        return {
            "timeframe": "1m",
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "ticker_count": len(tickers),
            "covered_ticker_count": covered,
            "coverage_ratio": round((covered / len(tickers)) if tickers else 0.0, 4),
            "by_ticker": by_ticker,
        }

    def _recent_session_coverage(self, ticker: str, *, end_at: datetime) -> list[dict[str, object]]:
        sessions: list[dict[str, object]] = []
        cursor = end_at.date()
        checked = 0
        while checked < 7:
            if cursor.weekday() >= 5:
                cursor -= timedelta(days=1)
                continue
            start = datetime.combine(cursor, datetime_time(0, 0), tzinfo=timezone.utc)
            end = datetime.combine(cursor, datetime_time(23, 59, 59), tzinfo=timezone.utc)
            count = self.repository.count_bars(
                ticker=ticker,
                timeframe="1m",
                start_at=start,
                end_at=end,
                available_at=end_at,
            )
            status = "complete" if count >= 300 else ("partial" if count > 0 else "missing")
            sessions.append(
                {
                    "date": cursor.isoformat(),
                    "row_count": count,
                    "status": status,
                }
            )
            checked += 1
            cursor -= timedelta(days=1)
        return sessions

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

            persisted = self.market_data.ingest_bars(
                ticker=ticker,
                timeframe="1m",
                start_at=start_date,
                end_at=end_date,
            )
            if not persisted:
                provider_label = "Yahoo" if self.market_data.provider.provider_name == "yahoo" else self.market_data.provider.provider_name
                return {
                    "status": "empty",
                    "ingested": 0,
                    "message": f"{ticker}: No data returned from {provider_label}",
                }

            ingested = len(persisted)
            logger.info("  Ingested %s bars for %s", ingested, ticker)
            return {"status": "success", "ingested": ingested, "message": None}
        except Exception as exc:
            logger.error("Failed to refresh bars for %s: %s", ticker, exc)
            return {
                "status": "error",
                "ingested": 0,
                "message": str(exc),
            }
