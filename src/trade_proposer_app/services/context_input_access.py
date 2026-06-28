from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.services.input_access import stable_hash


@dataclass(frozen=True)
class CoverageAccessResult:
    coverage: dict[str, object]
    provenance: dict[str, object]


class HistoricalNewsAccessService:
    def __init__(self, repository: HistoricalNewsRepository | None) -> None:
        self.repository = repository

    def replay_coverage(self, *, tickers: list[str], as_of: datetime, lookback_hours: int = 24) -> CoverageAccessResult:
        if self.repository is None:
            coverage = {"status": "not_configured", "lookback_hours": lookback_hours}
            return CoverageAccessResult(coverage=coverage, provenance=self._provenance(as_of, coverage))
        normalized_as_of = self._normalize(as_of)
        start_at = normalized_as_of - timedelta(hours=max(1, lookback_hours))
        counts_by_ticker = {
            ticker: self.repository.count_news(
                ticker,
                start_at=start_at,
                end_at=normalized_as_of,
                available_at=normalized_as_of,
            )
            for ticker in tickers
        }
        covered = sum(1 for count in counts_by_ticker.values() if count > 0)
        coverage = {
            "status": "available",
            "lookback_hours": lookback_hours,
            "lookback_start": start_at.isoformat(),
            "as_of": normalized_as_of.isoformat(),
            "covered_ticker_count": covered,
            "coverage_ratio": round((covered / len(tickers)) if tickers else 0.0, 4),
            "article_count_by_ticker": counts_by_ticker,
            "point_in_time_filter": "published_at <= as_of and available_at <= as_of",
        }
        return CoverageAccessResult(coverage=coverage, provenance=self._provenance(normalized_as_of, coverage))

    @staticmethod
    def _provenance(as_of: datetime, coverage: dict[str, object]) -> dict[str, object]:
        return {"source": "HistoricalNewsAccessService", "as_of": HistoricalNewsAccessService._normalize(as_of).isoformat(), "coverage_hash": stable_hash(coverage)}

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ContextSnapshotAccessService:
    def __init__(self, repository: ContextSnapshotRepository | None) -> None:
        self.repository = repository

    def replay_coverage(self, *, tickers: list[str], as_of: datetime) -> CoverageAccessResult:
        if self.repository is None:
            coverage = {"status": "not_configured"}
            return CoverageAccessResult(coverage=coverage, provenance=self._provenance(as_of, coverage))
        normalized_as_of = self._normalize(as_of)
        macro = self.repository.get_latest_macro_context_snapshot_before(normalized_as_of)
        industry_counts = {"available": 0, "missing": 0}
        industry_by_ticker: dict[str, dict[str, object]] = {}
        for ticker in tickers:
            industry_key = self._industry_key_for_ticker(ticker)
            industry = (
                self.repository.get_latest_industry_context_snapshot_before(industry_key, normalized_as_of)
                if industry_key
                else None
            )
            industry_counts["available" if industry is not None else "missing"] += 1
            industry_by_ticker[ticker] = {
                "industry_key": industry_key,
                "available": industry is not None,
                "computed_at": industry.computed_at.isoformat() if industry and industry.computed_at else None,
                "status": industry.status if industry else None,
                "point_in_time_filter": "computed_at <= as_of",
            }
        coverage = {
            "status": "available",
            "macro": {
                "available": macro is not None,
                "computed_at": macro.computed_at.isoformat() if macro and macro.computed_at else None,
                "status": macro.status if macro else None,
                "point_in_time_filter": "computed_at <= as_of",
            },
            "industry_counts": industry_counts,
            "industry_by_ticker": industry_by_ticker,
            "industry_coverage_ratio": round((industry_counts["available"] / len(tickers)) if tickers else 0.0, 4),
        }
        return CoverageAccessResult(coverage=coverage, provenance=self._provenance(normalized_as_of, coverage))

    def _industry_key_for_ticker(self, ticker: str) -> str:
        if self.repository is None:
            return ""
        try:
            profile = self.repository.taxonomy_service.get_industry_profile(ticker)
        except Exception:
            return ""
        return str(profile.get("subject_key") or "").strip()

    @staticmethod
    def _provenance(as_of: datetime, coverage: dict[str, object]) -> dict[str, object]:
        return {"source": "ContextSnapshotAccessService", "as_of": ContextSnapshotAccessService._normalize(as_of).isoformat(), "coverage_hash": stable_hash(coverage)}

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class FundamentalSnapshotAccessService:
    def __init__(self, repository: FundamentalAnalysisSnapshotRepository | None) -> None:
        self.repository = repository

    def replay_coverage(self, *, tickers: list[str], as_of: datetime) -> CoverageAccessResult:
        if self.repository is None:
            coverage = {"status": "not_configured"}
            return CoverageAccessResult(coverage=coverage, provenance=self._provenance(as_of, coverage))
        normalized_as_of = self._normalize(as_of)
        snapshots = self.repository.list_latest_by_tickers(tickers, as_of=normalized_as_of)
        by_ticker: dict[str, dict[str, object]] = {}
        covered = 0
        for ticker in tickers:
            normalized_ticker = ticker.upper()
            snapshot: dict[str, Any] | None = snapshots.get(normalized_ticker)
            if snapshot is not None:
                covered += 1
            snapshot_as_of = snapshot.get("as_of") if snapshot else None
            by_ticker[normalized_ticker] = {
                "available": snapshot is not None,
                "as_of": snapshot_as_of.isoformat() if isinstance(snapshot_as_of, datetime) else None,
                "coverage_status": snapshot.get("coverage_status") if snapshot else None,
                "freshness_status": snapshot.get("freshness_status") if snapshot else None,
                "point_in_time_filter": "snapshot.as_of <= replay as_of",
            }
        coverage = {
            "status": "available",
            "covered_ticker_count": covered,
            "coverage_ratio": round((covered / len(tickers)) if tickers else 0.0, 4),
            "by_ticker": by_ticker,
        }
        return CoverageAccessResult(coverage=coverage, provenance=self._provenance(normalized_as_of, coverage))

    @staticmethod
    def _provenance(as_of: datetime, coverage: dict[str, object]) -> dict[str, object]:
        return {"source": "FundamentalSnapshotAccessService", "as_of": FundamentalSnapshotAccessService._normalize(as_of).isoformat(), "coverage_hash": stable_hash(coverage)}

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
