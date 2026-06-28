from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.input_access import InputAccessPolicy, normalize_input_access_policy


@dataclass(frozen=True)
class ReplayMarketInputAccessResult:
    market_input: dict[str, object]
    coverage_report: dict[str, object]
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

    def _hydrate_if_allowed(
        self,
        *,
        tickers: list[str],
        batch_start: datetime,
        batch_end: datetime,
        policy: InputAccessPolicy,
    ) -> dict[str, object]:
        if policy in {"cache_then_remote", "remote_refresh"}:
            summary = self.market_data.hydrate_batch_inputs(
                tickers=tickers,
                start_at=batch_start,
                end_at=batch_end,
            )
            summary["policy"] = policy
            return summary
        return {
            "provider": getattr(self.market_data.provider, "provider_name", "unknown"),
            "source_tier": getattr(self.market_data.provider, "source_tier", "unknown"),
            "policy": policy,
            "status": "skipped_remote_hydration",
            "reason": "input_access_policy_disallows_remote_fetch",
            "ticker_count": len(tickers),
        }
