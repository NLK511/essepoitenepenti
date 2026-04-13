from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.models import Watchlist
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.context_snapshot_resolver import ContextSnapshotResolver
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.proposals import ProposalService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.signals import SignalIngestionService
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.summary import SummaryService
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignalService
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService


class _SignalStore:
    def __init__(self) -> None:
        self.items = []
        self._next_id = 1

    def create_ticker_signal_snapshot(self, signal):
        stored = signal.model_copy(update={"id": self._next_id})
        self._next_id += 1
        self.items.append(stored)
        return stored


class _PlanStore:
    def __init__(self) -> None:
        self.items = []
        self._next_id = 1

    def create_plan(self, plan):
        stored = plan.model_copy(update={"id": self._next_id})
        self._next_id += 1
        self.items.append(stored)
        return stored


class _BuggyReplayService(WatchlistOrchestrationService):
    def _run_deep_analysis(self, ticker, horizon, as_of=None):
        try:
            if hasattr(self.deep_analysis_service, "analyze"):
                return self.deep_analysis_service.analyze(ticker, horizon=horizon), None
            return self.deep_analysis_service.generate(ticker), None
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)


@dataclass
class _RunArtifacts:
    service: WatchlistOrchestrationService
    signals: _SignalStore
    plans: _PlanStore


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_artifacts(session, *, buggy: bool, disable_social: bool, summary_backend: str) -> _RunArtifacts:
    settings = SettingsRepository(session)
    credentials = settings.get_provider_credential_map()
    social_settings = settings.get_social_settings()
    if disable_social:
        social_settings["social_sentiment_enabled"] = "false"
        social_settings["social_nitter_enabled"] = "false"

    read_context_repo = ContextSnapshotRepository(session)
    signal_store = _SignalStore()
    plan_store = _PlanStore()
    social_service = SocialIngestionService.from_settings(social_settings)
    proposal_service = ProposalService(
        news_service=NewsIngestionService.from_provider_credentials(credentials, max_articles=12),
        social_service=social_service,
        signal_service=SignalIngestionService(social_service=social_service) if not disable_social else None,
        summary_service=SummaryService(summary_settings={"summary_backend": summary_backend}),
        snapshot_resolver=ContextSnapshotResolver(read_context_repo),
    )
    deep_analysis = TickerDeepAnalysisService(proposal_service)
    cls = _BuggyReplayService if buggy else WatchlistOrchestrationService
    service = cls(
        context_snapshots=signal_store,
        recommendation_plans=plan_store,
        decision_samples=None,
        cheap_scan_service=CheapScanSignalService(),
        deep_analysis_service=deep_analysis,
        confidence_threshold=60.0,
        calibration_service=RecommendationPlanCalibrationService(RecommendationOutcomeRepository(session)),
    )
    return _RunArtifacts(service=service, signals=signal_store, plans=plan_store)


def _summarize(plan_store: _PlanStore, signal_store: _SignalStore) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    signal_map = {item.ticker: item for item in signal_store.items}
    for plan in plan_store.items:
        transmission = plan.signal_breakdown.get("transmission_summary", {}) if isinstance(plan.signal_breakdown, dict) else {}
        calibration = plan.signal_breakdown.get("calibration_review", {}) if isinstance(plan.signal_breakdown, dict) else {}
        signal = signal_map.get(plan.ticker)
        rows.append(
            {
                "ticker": plan.ticker,
                "action": plan.action,
                "confidence_percent": round(float(plan.confidence_percent), 2),
                "raw_confidence_percent": round(float(plan.signal_breakdown.get("raw_confidence_percent", plan.confidence_percent)), 2),
                "effective_threshold": calibration.get("effective_confidence_threshold"),
                "action_reason": plan.evidence_summary.get("action_reason") if isinstance(plan.evidence_summary, dict) else None,
                "transmission_bias": transmission.get("context_bias"),
                "contradiction_count": int(transmission.get("contradiction_count", 0) or 0),
                "signal_warning_count": len(signal.warnings) if signal is not None else None,
                "signal_warnings": list(signal.warnings) if signal is not None else [],
                "plan_warning_count": len(plan.warnings or []),
            }
        )
    if not rows:
        return {
            "avg_confidence_percent": None,
            "avg_raw_confidence_percent": None,
            "actionable_count": 0,
            "headwind_count": 0,
            "contradiction_total": 0,
            "rows": [],
        }
    return {
        "avg_confidence_percent": round(mean(row["confidence_percent"] for row in rows), 2),
        "avg_raw_confidence_percent": round(mean(row["raw_confidence_percent"] for row in rows), 2),
        "actionable_count": sum(1 for row in rows if row["action"] in {"long", "short"}),
        "headwind_count": sum(1 for row in rows if row["transmission_bias"] == "headwind"),
        "contradiction_total": sum(row["contradiction_count"] for row in rows),
        "rows": rows,
    }


def _diff(fixed: dict[str, Any], buggy: dict[str, Any]) -> dict[str, Any]:
    fixed_rows = {row["ticker"]: row for row in fixed.get("rows", [])}
    buggy_rows = {row["ticker"]: row for row in buggy.get("rows", [])}
    per_ticker = []
    for ticker in sorted(set(fixed_rows) | set(buggy_rows)):
        left = fixed_rows.get(ticker, {})
        right = buggy_rows.get(ticker, {})
        per_ticker.append(
            {
                "ticker": ticker,
                "confidence_delta": round(float(left.get("confidence_percent", 0.0)) - float(right.get("confidence_percent", 0.0)), 2),
                "raw_confidence_delta": round(float(left.get("raw_confidence_percent", 0.0)) - float(right.get("raw_confidence_percent", 0.0)), 2),
                "action_fixed": left.get("action"),
                "action_buggy": right.get("action"),
                "action_reason_fixed": left.get("action_reason"),
                "action_reason_buggy": right.get("action_reason"),
                "signal_warnings_fixed": left.get("signal_warnings", []),
                "signal_warnings_buggy": right.get("signal_warnings", []),
            }
        )
    return {
        "avg_confidence_percent_delta": (
            round(float(fixed["avg_confidence_percent"] or 0.0) - float(buggy["avg_confidence_percent"] or 0.0), 2)
            if fixed.get("avg_confidence_percent") is not None and buggy.get("avg_confidence_percent") is not None
            else None
        ),
        "avg_raw_confidence_percent_delta": (
            round(float(fixed["avg_raw_confidence_percent"] or 0.0) - float(buggy["avg_raw_confidence_percent"] or 0.0), 2)
            if fixed.get("avg_raw_confidence_percent") is not None and buggy.get("avg_raw_confidence_percent") is not None
            else None
        ),
        "actionable_count_delta": int(fixed.get("actionable_count", 0)) - int(buggy.get("actionable_count", 0)),
        "headwind_count_delta": int(fixed.get("headwind_count", 0)) - int(buggy.get("headwind_count", 0)),
        "contradiction_total_delta": int(fixed.get("contradiction_total", 0)) - int(buggy.get("contradiction_total", 0)),
        "per_ticker": per_ticker,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare fixed replay behavior vs the previous buggy deep-analysis as_of omission.")
    parser.add_argument("--watchlist-id", type=int, required=True)
    parser.add_argument("--as-of", required=True, help="ISO timestamp, e.g. 2026-04-13T13:20:00+00:00")
    parser.add_argument("--limit-tickers", type=int, default=0, help="Optional cap for quick sampling")
    parser.add_argument("--disable-social", action="store_true", help="Disable social fetches for faster/debug runs")
    parser.add_argument("--summary-backend", default="news_digest")
    args = parser.parse_args()

    as_of = _parse_datetime(args.as_of)

    with SessionLocal() as session:
        watchlist = WatchlistRepository(session).get(args.watchlist_id)
        if args.limit_tickers > 0:
            watchlist = watchlist.model_copy(update={"tickers": watchlist.tickers[: args.limit_tickers]})

        fixed_artifacts = _build_artifacts(
            session,
            buggy=False,
            disable_social=args.disable_social,
            summary_backend=args.summary_backend,
        )
        fixed_result = fixed_artifacts.service.execute(watchlist, watchlist.tickers, as_of=as_of)
        fixed_summary = _summarize(fixed_artifacts.plans, fixed_artifacts.signals)

        buggy_artifacts = _build_artifacts(
            session,
            buggy=True,
            disable_social=args.disable_social,
            summary_backend=args.summary_backend,
        )
        buggy_result = buggy_artifacts.service.execute(watchlist, watchlist.tickers, as_of=as_of)
        buggy_summary = _summarize(buggy_artifacts.plans, buggy_artifacts.signals)

        payload = {
            "watchlist": {
                "id": watchlist.id,
                "name": watchlist.name,
                "ticker_count": len(watchlist.tickers),
            },
            "as_of": as_of.isoformat(),
            "fixed": {
                "orchestration_summary": fixed_result.get("summary", {}),
                "plan_summary": fixed_summary,
            },
            "buggy": {
                "orchestration_summary": buggy_result.get("summary", {}),
                "plan_summary": buggy_summary,
            },
            "delta": _diff(fixed_summary, buggy_summary),
        }
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
