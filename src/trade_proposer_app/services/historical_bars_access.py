from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trade_proposer_app.domain.models import HistoricalMarketBar

from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.input_access import InputAccessPolicy, normalize_input_access_policy


@dataclass(frozen=True)
class ReplayMarketInputAccessResult:
    market_input: dict[str, object]
    coverage_report: dict[str, object]
    hydration_summary: dict[str, object]


@dataclass(frozen=True)
class HistoricalBarsAccessResult:
    ticker: str
    timeframe: str
    start_at: datetime | None
    end_at: datetime | None
    available_at: datetime | None
    bars: list[HistoricalMarketBar]
    coverage: dict[str, object]
    hydration_summary: dict[str, object]


class HistoricalBarsAccessService:
    """Single entry point for replay market-bar input access.

    This service intentionally hides whether bars came from cache or remote hydration.
    Callers choose an explicit policy, then receive market input plus the matching
    coverage/provenance summary in one result.
    """

    def __init__(self, market_data: HistoricalMarketDataService) -> None:
        self.market_data = market_data

    def replay_market_inputs(
        self,
        *,
        tickers: list[str],
        batch_start: datetime,
        batch_end: datetime,
        as_of: datetime,
        policy: str = "cache_then_remote",
    ) -> ReplayMarketInputAccessResult:
        normalized_policy: InputAccessPolicy = normalize_input_access_policy(policy)
        hydration_summary = self._hydrate_if_allowed(
            tickers=tickers,
            batch_start=batch_start,
            batch_end=batch_end,
            policy=normalized_policy,
            timeframe="1d",
        )
        source = "cache" if normalized_policy in {"cache_only", "fail_if_missing"} else "cache_plus_remote"
        market_input = self.market_data.build_slice_market_input(tickers=tickers, as_of=as_of)
        coverage_report = self.market_data.build_replay_coverage_report(
            tickers=tickers,
            as_of=as_of,
            input_policy=normalized_policy,
            source=source,
        )
        coverage_report["access_service"] = "HistoricalBarsAccessService"
        hydration_summary["access_service"] = "HistoricalBarsAccessService"
        return ReplayMarketInputAccessResult(
            market_input=market_input,
            coverage_report=coverage_report,
            hydration_summary=hydration_summary,
        )

    def daily_bars(
        self,
        *,
        ticker: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        available_at: datetime | None = None,
        limit: int = 200,
        policy: str = "cache_only",
    ) -> HistoricalBarsAccessResult:
        normalized_policy = normalize_input_access_policy(policy, default="cache_only")
        hydration_summary = self._hydrate_if_allowed(
            tickers=[ticker],
            batch_start=start_at or end_at or available_at or datetime.utcnow(),
            batch_end=end_at or start_at or available_at or datetime.utcnow(),
            policy=normalized_policy,
            timeframe="1d",
        )
        bars = self.market_data.historical_market_data.list_bars(
            ticker=ticker,
            timeframe="1d",
            start_at=start_at,
            end_at=end_at,
            available_at=available_at,
            limit=limit,
        )
        return HistoricalBarsAccessResult(
            ticker=ticker,
            timeframe="1d",
            start_at=start_at,
            end_at=end_at,
            available_at=available_at,
            bars=bars,
            coverage=self._bar_coverage(ticker=ticker, timeframe="1d", start_at=start_at, end_at=end_at, available_at=available_at, bar_count=len(bars), policy=normalized_policy),
            hydration_summary=hydration_summary,
        )

    def intraday_1m_bars(
        self,
        *,
        ticker: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        available_at: datetime | None = None,
        limit: int = 500,
        policy: str = "cache_only",
    ) -> HistoricalBarsAccessResult:
        normalized_policy = normalize_input_access_policy(policy, default="cache_only")
        hydration_summary = self._hydrate_if_allowed(
            tickers=[ticker],
            batch_start=start_at or end_at or available_at or datetime.utcnow(),
            batch_end=end_at or start_at or available_at or datetime.utcnow(),
            policy=normalized_policy,
            timeframe="1m",
        )
        bars = self.market_data.historical_market_data.list_bars(
            ticker=ticker,
            timeframe="1m",
            start_at=start_at,
            end_at=end_at,
            available_at=available_at,
            limit=limit,
        )
        return HistoricalBarsAccessResult(
            ticker=ticker,
            timeframe="1m",
            start_at=start_at,
            end_at=end_at,
            available_at=available_at,
            bars=bars,
            coverage=self._bar_coverage(ticker=ticker, timeframe="1m", start_at=start_at, end_at=end_at, available_at=available_at, bar_count=len(bars), policy=normalized_policy),
            hydration_summary=hydration_summary,
        )

    def _hydrate_if_allowed(
        self,
        *,
        tickers: list[str],
        batch_start: datetime,
        batch_end: datetime,
        policy: InputAccessPolicy,
        timeframe: str,
    ) -> dict[str, object]:
        gap_report = self._gap_report(tickers=tickers, timeframe=timeframe, start_at=batch_start, end_at=batch_end)
        if policy in {"cache_then_remote", "remote_refresh"} and timeframe == "1d":
            fetch_tickers = list(tickers) if policy == "remote_refresh" else list(gap_report["missing_tickers"])
            ingested_by_ticker: dict[str, int] = {}
            for ticker in fetch_tickers:
                persisted = self.market_data.ingest_daily_bars(ticker=ticker, start_at=batch_start, end_at=batch_end)
                ingested_by_ticker[ticker] = len(persisted)
            return {
                "provider": getattr(self.market_data.provider, "provider_name", "unknown"),
                "source_tier": getattr(self.market_data.provider, "source_tier", "unknown"),
                "policy": policy,
                "status": "hydrated" if fetch_tickers else "cache_satisfied",
                "ticker_count": len(tickers),
                "requested_ticker_count": len(fetch_tickers),
                "bars_ingested_by_ticker": ingested_by_ticker,
                "bar_count": sum(ingested_by_ticker.values()),
                "gap_report": gap_report,
            }
        if policy in {"cache_then_remote", "remote_refresh"} and timeframe != "1d":
            return {
                "provider": getattr(self.market_data.provider, "provider_name", "unknown"),
                "source_tier": getattr(self.market_data.provider, "source_tier", "unknown"),
                "policy": policy,
                "status": "skipped_remote_hydration",
                "reason": f"remote_hydration_not_supported_for_{timeframe}",
                "ticker_count": len(tickers),
                "gap_report": gap_report,
            }
        return {
            "provider": getattr(self.market_data.provider, "provider_name", "unknown"),
            "source_tier": getattr(self.market_data.provider, "source_tier", "unknown"),
            "policy": policy,
            "status": "skipped_remote_hydration",
            "reason": "input_access_policy_disallows_remote_fetch",
            "ticker_count": len(tickers),
            "gap_report": gap_report,
        }

    def _gap_report(
        self,
        *,
        tickers: list[str],
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, object]:
        counts: dict[str, int] = {}
        missing: list[str] = []
        for ticker in tickers:
            count = self.market_data.historical_market_data.count_bars(
                ticker=ticker,
                timeframe=timeframe,
                start_at=start_at,
                end_at=end_at,
                available_at=None,
            )
            counts[ticker] = count
            if count <= 0:
                missing.append(ticker)
        return {
            "timeframe": timeframe,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "ticker_count": len(tickers),
            "missing_tickers": missing,
            "missing_ticker_count": len(missing),
            "bar_counts_by_ticker": counts,
        }

    @staticmethod
    def _bar_coverage(
        *,
        ticker: str,
        timeframe: str,
        start_at: datetime | None,
        end_at: datetime | None,
        available_at: datetime | None,
        bar_count: int,
        policy: InputAccessPolicy,
    ) -> dict[str, object]:
        return {
            "ticker": ticker,
            "timeframe": timeframe,
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
            "available_at": available_at.isoformat() if available_at else None,
            "bar_count": bar_count,
            "covered": bar_count > 0,
            "policy": policy,
            "access_service": "HistoricalBarsAccessService",
        }
