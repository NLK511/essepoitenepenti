from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from trade_proposer_app.repositories.fundamental_analysis_snapshots import (
    FundamentalAnalysisSnapshotRepository,
)
from trade_proposer_app.services.fundamental_analysis import FundamentalAnalysisService
from trade_proposer_app.services.monitored_tickers import MonitoredTickerService


class FundamentalCoverageHealthService:
    def __init__(
        self,
        session: Session,
        *,
        snapshots: FundamentalAnalysisSnapshotRepository | None = None,
        monitored_tickers: MonitoredTickerService | None = None,
        due_logic: FundamentalAnalysisService | None = None,
    ) -> None:
        self.session = session
        self.snapshots = snapshots or FundamentalAnalysisSnapshotRepository(session)
        self.monitored_tickers = monitored_tickers or MonitoredTickerService(session)
        self.due_logic = due_logic or FundamentalAnalysisService()

    def summarize(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        effective_as_of = self._dt(as_of) or datetime.now(UTC)
        monitored = self.monitored_tickers.list_monitored_tickers_with_provenance()
        tickers: list[dict[str, Any]] = []
        coverage_status_counts: dict[str, int] = {}
        freshness_status_counts: dict[str, int] = {}
        due_count = 0
        missing_snapshot_count = 0
        stale_or_degraded_count = 0
        for item in monitored:
            ticker = str(item.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            snapshot = self.snapshots.get_latest_for_ticker(ticker)
            due_reason = self.due_logic.snapshot_due_reason(snapshot, effective_as_of)
            if due_reason is not None:
                due_count += 1
            coverage_status = str(snapshot.get("coverage_status") if snapshot else "missing")
            freshness_status = str(snapshot.get("freshness_status") if snapshot else "missing")
            if snapshot is None:
                missing_snapshot_count += 1
            if coverage_status not in {"ok", "missing"} or freshness_status in {
                "stale",
                "missing",
            }:
                stale_or_degraded_count += 1
            coverage_status_counts[coverage_status] = (
                coverage_status_counts.get(coverage_status, 0) + 1
            )
            freshness_status_counts[freshness_status] = (
                freshness_status_counts.get(freshness_status, 0) + 1
            )
            tickers.append(
                {
                    "ticker": ticker,
                    "provenance": list(item.get("provenance") or []),
                    "health_status": self._health_status(snapshot, due_reason=due_reason),
                    "due_reason": due_reason,
                    "snapshot_id": snapshot.get("id") if snapshot else None,
                    "snapshot_as_of": self._iso(snapshot.get("as_of")) if snapshot else None,
                    "coverage_status": coverage_status,
                    "freshness_status": freshness_status,
                    "warnings": list(snapshot.get("warnings") or []) if snapshot else [],
                    "missing_inputs": list(snapshot.get("missing_inputs") or [])
                    if snapshot
                    else [],
                }
            )
        return {
            "schema_version": "fundamental-coverage-health-v1",
            "status": self._overall_status(
                monitored_count=len(tickers),
                missing_snapshot_count=missing_snapshot_count,
                stale_or_degraded_count=stale_or_degraded_count,
                due_count=due_count,
            ),
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of": effective_as_of.isoformat(),
            "monitored_count": len(tickers),
            "snapshot_available_count": len(tickers) - missing_snapshot_count,
            "missing_snapshot_count": missing_snapshot_count,
            "stale_or_degraded_count": stale_or_degraded_count,
            "due_count": due_count,
            "coverage_status_counts": coverage_status_counts,
            "freshness_status_counts": freshness_status_counts,
            "tickers": tickers,
        }

    @staticmethod
    def _overall_status(
        *,
        monitored_count: int,
        missing_snapshot_count: int,
        stale_or_degraded_count: int,
        due_count: int,
    ) -> str:
        if monitored_count == 0:
            return "empty"
        if missing_snapshot_count or stale_or_degraded_count or due_count:
            return "needs_attention"
        return "ok"

    @staticmethod
    def _health_status(snapshot: dict[str, Any] | None, *, due_reason: str | None) -> str:
        if snapshot is None:
            return "missing"
        if due_reason is not None:
            return "due"
        if str(snapshot.get("coverage_status") or "") != "ok":
            return "degraded"
        if str(snapshot.get("freshness_status") or "") == "stale":
            return "stale"
        return "ok"

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @classmethod
    def _iso(cls, value: Any) -> str | None:
        parsed = cls._dt(value)
        return parsed.isoformat() if parsed is not None else None
