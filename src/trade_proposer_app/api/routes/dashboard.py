from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.persistence.models import BrokerOrderExecutionRecord, HistoricalMarketBarRecord, HistoricalNewsRecord, TickerSignalSnapshotRecord
from trade_proposer_app.domain.enums import RunStatus
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService
from trade_proposer_app.services.recommendation_plan_baselines import RecommendationPlanBaselineService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.recommendation_quality_summary import RecommendationQualitySummaryService
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.trading_performance_metrics import TradingPerformanceMetricsService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

WINDOW_DEFINITIONS: dict[str, timedelta | None] = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "all": None,
}
DASHBOARD_TREND_SERIES: list[tuple[str, str, str]] = [
    ("win_rate_percent", "Win rate", "percent"),
    ("profit_percent", "Profit %", "percent"),
    ("shortlist_rate_percent", "Shortlist rate", "percent"),
    ("actionable_rate_percent", "Actionable rate", "percent"),
    ("actionability_gap_percent", "Actionability gap", "percent"),
    ("news_processed", "News processed", "count"),
    ("tweets_processed", "Tweets processed", "count"),
    ("bars_stored", "Bars stored", "count"),
    ("orders_placed", "Orders placed", "count"),
    ("broker_closed_positions", "Broker closed", "count"),
    ("broker_realized_pnl", "Broker realized P&L", "currency"),
]


def _normalize_window(window: str | None) -> str:
    normalized = str(window or "1m").strip().lower()
    return normalized if normalized in WINDOW_DEFINITIONS else "1m"


def _window_start(window: str, now: datetime) -> datetime | None:
    delta = WINDOW_DEFINITIONS[window]
    if delta is None:
        return None
    return now - delta


def _percentage(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((part / total) * 100.0, 1)


def _count_ticker_signals(session: Session, *, computed_after: datetime | None, computed_before: datetime | None) -> int:
    query = select(func.count()).select_from(TickerSignalSnapshotRecord)
    if computed_after is not None:
        query = query.where(TickerSignalSnapshotRecord.computed_at >= computed_after)
    if computed_before is not None:
        query = query.where(TickerSignalSnapshotRecord.computed_at <= computed_before)
    return int(session.scalar(query) or 0)


def _recent_items_within_window(items: list, *, computed_after: datetime | None, attr_name: str = "created_at") -> list:
    if computed_after is None:
        return items
    filtered = []
    for item in items:
        value = getattr(item, attr_name, None)
        if isinstance(value, datetime) and value >= computed_after:
            filtered.append(item)
    return filtered


def _sum_plan_item_count(plans: list, key: str) -> int:
    total = 0
    for plan in plans:
        breakdown = getattr(plan, "signal_breakdown", None)
        if hasattr(breakdown, "get"):
            try:
                total += int(breakdown.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
    return total


def _count_records(session: Session, model, column, computed_after: datetime | None, computed_before: datetime | None = None) -> int:
    query = select(func.count()).select_from(model)
    if computed_after is not None:
        query = query.where(column >= computed_after)
    if computed_before is not None:
        query = query.where(column <= computed_before)
    return int(session.scalar(query) or 0)


def _baseline_metric(summary, key: str, metric: str) -> float | None:
    for item in summary.comparisons:
        if item.key == key:
            return getattr(item, metric, None)
    return None


def _dashboard_window_metrics(
    session: Session,
    *,
    now: datetime,
    window_key: str,
    quality_fallback: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    computed_after = _window_start(window_key, now)
    plan_repository = RecommendationPlanRepository(session)
    outcome_repository = RecommendationOutcomeRepository(session)
    effective_outcome_repository = EffectivePlanOutcomeRepository(session)
    signals_amount = _count_ticker_signals(session, computed_after=computed_after, computed_before=now)
    plan_amount = plan_repository.count_plans(computed_after=computed_after, computed_before=now)
    shortlisted_plans = plan_repository.count_plans(shortlisted=True, computed_after=computed_after, computed_before=now)
    actionable_plans = plan_repository.count_plans(action="long", computed_after=computed_after, computed_before=now) + plan_repository.count_plans(action="short", computed_after=computed_after, computed_before=now)
    technical_plans = plan_repository.list_plans(limit=5000, computed_after=computed_after, computed_before=now)

    news_processed = _count_records(session, HistoricalNewsRecord, HistoricalNewsRecord.published_at, computed_after, now)
    bars_stored = _count_records(session, HistoricalMarketBarRecord, HistoricalMarketBarRecord.bar_time, computed_after, now)
    orders_placed = _count_records(session, BrokerOrderExecutionRecord, BrokerOrderExecutionRecord.created_at, computed_after, now)
    broker_summary = TradingPerformanceMetricsService(session).summarize_broker_closed_positions(evaluated_after=computed_after, evaluated_before=now).to_dict()
    tweets_processed = _sum_plan_item_count(technical_plans, "social_item_count")

    calibration = RecommendationPlanCalibrationService(effective_outcome_repository).summarize(evaluated_after=computed_after, evaluated_before=now)
    baselines = RecommendationPlanBaselineService(plan_repository).summarize(computed_after=computed_after, computed_before=now)
    actionability = outcome_repository.summarize_actionability_diagnostics(evaluated_after=computed_after, evaluated_before=now)

    win_rate_percent = broker_summary["win_rate_percent"]
    if win_rate_percent is None:
        win_rate_percent = (
            quality_fallback.get("overall_win_rate_percent") if quality_fallback is not None else calibration.overall_win_rate_percent
        )
    profit_percent = broker_summary["average_return_percent"]
    if profit_percent is None:
        profit_percent = (
            quality_fallback.get("actual_actionable_average_return_5d")
            if quality_fallback is not None
            else _baseline_metric(baselines, "actual_actionable", "average_return_5d")
        )

    dashboard_summary = {
        "plan_amount": plan_amount,
        "signals_amount": signals_amount,
        "shortlisted_plans": shortlisted_plans,
        "shortlist_rate_percent": _percentage(plan_amount, signals_amount),
        "actionable_plans": actionable_plans,
        "actionable_rate_percent": _percentage(actionable_plans, plan_amount),
        "win_rate_percent": win_rate_percent,
        "win_rate_source": "broker" if broker_summary["win_rate_percent"] is not None else ("quality" if quality_fallback is not None else "calibration"),
        "profit_percent": profit_percent,
        "profit_source": "broker" if broker_summary["average_return_percent"] is not None else ("quality" if quality_fallback is not None else "baseline"),
        "actionability_gap_percent": actionability["actionability_gap_percent"],
        "actionable_win_rate_percent": actionability["actionable_win_rate_percent"],
        "phantom_win_rate_percent": actionability["phantom_win_rate_percent"],
        "actionable_resolved_outcomes": actionability["actionable_resolved_outcomes"],
        "phantom_resolved_outcomes": actionability["phantom_resolved_outcomes"],
        "actionable_win_outcomes": actionability["actionable_win_outcomes"],
        "actionable_loss_outcomes": actionability["actionable_loss_outcomes"],
        "phantom_win_outcomes": actionability["phantom_win_outcomes"],
        "phantom_loss_outcomes": actionability["phantom_loss_outcomes"],
        "no_action_outcomes": actionability["no_action_outcomes"],
        "watchlist_outcomes": actionability["watchlist_outcomes"],
    }
    technical_summary = {
        "news_processed": news_processed,
        "tweets_processed": tweets_processed,
        "bars_stored": bars_stored,
        "orders_placed": orders_placed,
        "broker_closed_positions": broker_summary["closed_positions"],
        "broker_wins": broker_summary["wins"],
        "broker_losses": broker_summary["losses"],
        "broker_realized_pnl": broker_summary["realized_pnl"],
    }
    return {
        "window_key": window_key,
        "dashboard_summary": dashboard_summary,
        "technical_summary": technical_summary,
    }


def _build_dashboard_trends(session: Session, *, now: datetime) -> dict[str, object]:
    snapshots = [
        _dashboard_window_metrics(session, now=now, window_key=window_key)
        for window_key in WINDOW_DEFINITIONS
    ]
    return {
        "windows": [
            {"key": snapshot["window_key"], "label": snapshot["window_key"].upper() if snapshot["window_key"] != "all" else "ALL"}
            for snapshot in snapshots
        ],
        "series": [
            {
                "key": key,
                "label": label,
                "kind": kind,
                "values": [snapshot["dashboard_summary"].get(key) if key in snapshot["dashboard_summary"] else snapshot["technical_summary"].get(key) for snapshot in snapshots],
            }
            for key, label, kind in DASHBOARD_TREND_SERIES
        ],
    }


@router.get("")
async def get_dashboard(
    session: Session = Depends(get_db_session),
    window: str = Query("1m", description="Dashboard time window"),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    window_key = _normalize_window(window)
    computed_after = _window_start(window_key, now)
    watchlists = WatchlistRepository(session).list_all()
    jobs = JobRepository(session).list_all()
    runs = RunRepository(session)
    plan_repository = RecommendationPlanRepository(session)
    outcome_repository = RecommendationOutcomeRepository(session)
    effective_outcome_repository = EffectivePlanOutcomeRepository(session)
    confidence_threshold = SettingsDomainService(session).strategy_settings().confidence_threshold

    latest_runs = _recent_items_within_window(
        runs.list_latest_runs_above_confidence_threshold(confidence_threshold=confidence_threshold, limit=20),
        computed_after=computed_after,
    )[:10]
    recent_runs = _recent_items_within_window(runs.list_latest_runs(limit=50), computed_after=computed_after)
    recommendation_plans = plan_repository.list_plans(limit=12, computed_after=computed_after, computed_before=now)
    recent_plans = plan_repository.list_plans(limit=500, computed_after=computed_after, computed_before=now)
    technical_plans = plan_repository.list_plans(limit=5000, computed_after=computed_after, computed_before=now)

    signals_amount = _count_ticker_signals(session, computed_after=computed_after, computed_before=now)
    plan_amount = plan_repository.count_plans(computed_after=computed_after, computed_before=now)
    shortlisted_plans = plan_repository.count_plans(shortlisted=True, computed_after=computed_after, computed_before=now)
    actionable_plans = plan_repository.count_plans(action="long", computed_after=computed_after, computed_before=now) + plan_repository.count_plans(action="short", computed_after=computed_after, computed_before=now)

    quality_service = RecommendationQualitySummaryService(session)
    news_processed = _count_records(session, HistoricalNewsRecord, HistoricalNewsRecord.published_at, computed_after, now)
    bars_stored = _count_records(session, HistoricalMarketBarRecord, HistoricalMarketBarRecord.bar_time, computed_after, now)
    orders_placed = _count_records(session, BrokerOrderExecutionRecord, BrokerOrderExecutionRecord.created_at, computed_after, now)
    broker_summary = TradingPerformanceMetricsService(session).summarize_broker_closed_positions(evaluated_after=computed_after, evaluated_before=now).to_dict()
    tweets_processed = _sum_plan_item_count(technical_plans, "social_item_count")

    calibration = RecommendationPlanCalibrationService(effective_outcome_repository).summarize(evaluated_after=computed_after, evaluated_before=now)
    baselines = RecommendationPlanBaselineService(plan_repository).summarize(computed_after=computed_after, computed_before=now)
    evidence = RecommendationEvidenceConcentrationService(effective_outcome_repository).summarize(evaluated_after=computed_after, evaluated_before=now)
    family_review = RecommendationSetupFamilyReviewService(effective_outcome_repository).summarize(evaluated_after=computed_after, evaluated_before=now)
    entry_miss = outcome_repository.summarize_entry_miss_diagnostics(evaluated_after=computed_after, evaluated_before=now)
    actionability = outcome_repository.summarize_actionability_diagnostics(evaluated_after=computed_after, evaluated_before=now)
    selected_quality = quality_service._summary_payload(  # noqa: SLF001 - dashboard needs the selected window summary
        calibration,
        baselines,
        evidence,
        family_review,
        entry_miss,
        walk_forward=None,
        walk_forward_error=None,
        window_label=window_key,
        computed_after=computed_after or (now - timedelta(days=3650)),
        computed_before=now,
        evaluated_after=computed_after or (now - timedelta(days=3650)),
        evaluated_before=now,
    )
    selected_window_metrics = _dashboard_window_metrics(session, now=now, window_key=window_key, quality_fallback=selected_quality)
    dashboard_trends = _build_dashboard_trends(session, now=now)

    major_failures: list[dict[str, object]] = []
    for run in recent_runs:
        if run.status != RunStatus.FAILED.value:
            continue
        major_failures.append(
            {
                "source": run.job_type,
                "label": f"Run #{run.id}" if run.id is not None else "Run",
                "detail": run.error_message or "failed",
                "run_id": run.id,
                "status": run.status,
                "created_at": run.created_at,
            }
        )

    warning_counter: Counter[str] = Counter()
    warning_sources: dict[str, set[str]] = {}

    def add_warning(message: str | None, source: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        warning_counter[text] += 1
        warning_sources.setdefault(text, set()).add(source)

    for run in recent_runs:
        if run.error_message:
            add_warning(run.error_message, f"run:{run.id or 'unknown'}")
    for plan in recent_plans:
        for warning in plan.warnings:
            add_warning(warning, f"plan:{plan.id or 'unknown'}")
    status_reason = str(selected_quality.get("status_reason") or "").strip()
    if status_reason and str(selected_quality.get("status") or "") in {"thin", "needs_attention"}:
        add_warning(status_reason, "quality")
    add_warning(selected_quality.get("walk_forward_error") if isinstance(selected_quality, dict) else None, "quality")

    distinct_warnings = [
        {
            "label": warning,
            "count": count,
            "sources": sorted(warning_sources.get(warning, set())),
        }
        for warning, count in warning_counter.most_common(8)
    ]

    return {
        "dashboard_window": window_key,
        "watchlists": watchlists,
        "jobs": jobs,
        "latest_runs": latest_runs,
        "recent_runs": recent_runs,
        "recommendation_plans": recommendation_plans,
        "recommendation_quality": {"summary": selected_quality},
        "dashboard_summary": selected_window_metrics["dashboard_summary"],
        "technical_summary": selected_window_metrics["technical_summary"],
        "dashboard_trends": dashboard_trends,
        "major_failures": major_failures[:6],
        "distinct_warnings": distinct_warnings,
    }
