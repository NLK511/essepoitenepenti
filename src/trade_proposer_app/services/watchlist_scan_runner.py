from __future__ import annotations

from datetime import datetime
from typing import Any

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RunOutput
from trade_proposer_app.services.watchlist_candidates import CheapScanCandidate


class WatchlistScanRunnerService:
    """Run cheap scans and deep analysis, normalizing failures into stable orchestration shapes."""

    def __init__(self, cheap_scan_service: Any, deep_analysis_service: Any) -> None:
        self.cheap_scan_service = cheap_scan_service
        self.deep_analysis_service = deep_analysis_service

    def run_cheap_scan(
        self,
        ticker: str,
        horizon: StrategyHorizon,
        as_of: datetime | None = None,
    ) -> CheapScanCandidate:
        try:
            signal = self.cheap_scan_service.score(ticker, horizon, as_of=as_of)
        except Exception as exc:
            return CheapScanCandidate(
                ticker=ticker,
                direction="neutral",
                confidence_percent=0.0,
                attention_score=0.0,
                warnings=[str(exc)],
                indicator_summary="cheap scan failed",
                cheap_scan_signal=None,
                raw_output=None,
                error_message=str(exc),
            )
        return CheapScanCandidate(
            ticker=ticker,
            direction=signal.directional_bias,
            confidence_percent=signal.confidence_percent,
            attention_score=signal.attention_score,
            warnings=list(signal.warnings),
            indicator_summary=signal.indicator_summary,
            cheap_scan_signal=signal,
            raw_output=None,
        )

    def run_deep_analysis(
        self,
        ticker: str,
        horizon: StrategyHorizon,
        as_of: datetime | None = None,
    ) -> tuple[RunOutput | None, str | None]:
        try:
            if hasattr(self.deep_analysis_service, "analyze"):
                return self.deep_analysis_service.analyze(ticker, horizon=horizon, as_of=as_of), None
            return self.deep_analysis_service.generate(ticker, as_of=as_of), None
        except Exception as exc:
            return None, str(exc)
