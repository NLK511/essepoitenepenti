from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService
from trade_proposer_app.services.monitored_tickers import MonitoredTickerService


class FundamentalAnalysisRefreshService:
    def __init__(self, session: Session, *, analysis_service: Any | None = None, snapshots: FundamentalAnalysisSnapshotRepository | None = None, monitored_tickers: MonitoredTickerService | None = None) -> None:
        self.session = session
        self.snapshots = snapshots or FundamentalAnalysisSnapshotRepository(session)
        self.analysis_service = analysis_service or FundamentalAnalysisService(repository=self.snapshots)
        self.monitored_tickers = monitored_tickers or MonitoredTickerService(session)
        self.due_logic = FundamentalAnalysisService()

    def refresh_due_monitored_tickers(self, *, as_of: datetime | None = None, max_tickers: int = 100, job_id: int | None = None, run_id: int | None = None) -> dict[str, Any]:
        effective_as_of = as_of or datetime.now(timezone.utc)
        tickers = self.monitored_tickers.list_monitored_tickers()
        refreshed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for ticker in tickers:
            if len(refreshed) >= max(1, int(max_tickers)):
                skipped.append({"ticker": ticker, "reason": "max_tickers_reached"})
                continue
            latest = self.snapshots.get_latest_for_ticker(ticker)
            reason = self.due_logic.snapshot_due_reason(latest, effective_as_of)
            if reason is None:
                skipped.append({"ticker": ticker, "reason": "fresh"})
                continue
            try:
                result = self.analysis_service.refresh_ticker(ticker, job_id=job_id, run_id=run_id, as_of=effective_as_of)
            except Exception as exc:
                failed.append({"ticker": ticker, "reason": reason, "error": str(exc)})
                continue
            refreshed.append({"ticker": ticker, "reason": reason, "snapshot": result})
        return {
            "monitored_count": len(tickers),
            "refreshed_count": len(refreshed),
            "skipped_fresh_count": len([item for item in skipped if item["reason"] == "fresh"]),
            "failed_count": len(failed),
            "refreshed": refreshed,
            "skipped": skipped,
            "failed": failed,
        }
