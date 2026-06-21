import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import RunStatus
from trade_proposer_app.persistence.models import (
    BrokerOrderExecutionRecord,
    HistoricalMarketBarRecord,
    HistoricalNewsRecord,
    ObservabilityEventRecord,
    RecommendationPlanRecord,
    TickerSignalSnapshotRecord,
)
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.risk_halt_events import RiskHaltEventRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.dashboard_trends import DashboardTrendService
from trade_proposer_app.services.data_quality_audit import DataQualityAuditService
from trade_proposer_app.services.gating_severity_alerts import GatingSeverityAlertService
from trade_proposer_app.services.policy_trust_report import PolicyTrustReportService
from trade_proposer_app.services.recommendation_evidence_concentration import (
    RecommendationEvidenceConcentrationService,
)
from trade_proposer_app.services.recommendation_plan_baselines import (
    RecommendationPlanBaselineService,
)
from trade_proposer_app.services.recommendation_plan_calibration import (
    RecommendationPlanCalibrationService,
)
from trade_proposer_app.services.recommendation_quality_summary import (
    RecommendationQualitySummaryService,
)
from trade_proposer_app.services.recommendation_setup_family_reviews import (
    RecommendationSetupFamilyReviewService,
)
from trade_proposer_app.services.risk_management import BrokerRiskManager
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.utils.json_payloads import loads_json_object as _json_object
from trade_proposer_app.services.time_windows import normalize_review_window, review_window_start
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
from trade_proposer_app.services.trading_performance_metrics import TradingPerformanceMetricsService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _normalize_window(window: str | None) -> str:
    return normalize_review_window(window, default="1d")


def _window_start(window: str, now: datetime) -> datetime | None:
    return review_window_start(window, now)


def _percentage(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((part / total) * 100.0, 1)


def _count_ticker_signals(
    session: Session, *, computed_after: datetime | None, computed_before: datetime | None
) -> int:
    query = select(func.count()).select_from(TickerSignalSnapshotRecord)
    if computed_after is not None:
        query = query.where(TickerSignalSnapshotRecord.computed_at >= computed_after)
    if computed_before is not None:
        query = query.where(TickerSignalSnapshotRecord.computed_at <= computed_before)
    return int(session.scalar(query) or 0)


def _recent_items_within_window(
    items: list, *, computed_after: datetime | None, attr_name: str = "created_at"
) -> list:
    if computed_after is None:
        return items
    filtered = []
    for item in items:
        value = getattr(item, attr_name, None)
        if isinstance(value, datetime) and value >= computed_after:
            filtered.append(item)
    return filtered


def _sum_plan_signal_breakdown_count(
    session: Session,
    key: str,
    *,
    computed_after: datetime | None,
    computed_before: datetime | None,
) -> int:
    query = select(RecommendationPlanRecord.signal_breakdown_json)
    if computed_after is not None:
        query = query.where(RecommendationPlanRecord.computed_at >= computed_after)
    if computed_before is not None:
        query = query.where(RecommendationPlanRecord.computed_at <= computed_before)
    total = 0
    for raw_breakdown in session.scalars(query).all():
        if not raw_breakdown:
            continue
        try:
            breakdown = json.loads(raw_breakdown)
        except json.JSONDecodeError:
            continue
        if not isinstance(breakdown, dict):
            continue
        try:
            total += int(breakdown.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _extract_warning_messages(payload_text: str | None) -> list[str]:
    if not payload_text:
        return []
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return []
    warnings: list[str] = []
    if isinstance(payload, dict):
        for key in ("warnings", "warning", "summary_warning", "context_summary_warning"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                warnings.append(value.strip())
            elif isinstance(value, list):
                warnings.extend(str(item).strip() for item in value if str(item).strip())
        artifact = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else None
        if isinstance(artifact, dict):
            for key in ("warnings", "warning"):
                value = artifact.get(key)
                if isinstance(value, str) and value.strip():
                    warnings.append(value.strip())
                elif isinstance(value, list):
                    warnings.extend(str(item).strip() for item in value if str(item).strip())
    return list(dict.fromkeys(warnings))


def _count_records(
    session: Session,
    model,
    column,
    computed_after: datetime | None,
    computed_before: datetime | None = None,
) -> int:
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
    aggregate_days = {"7d": 7, "1m": 30}.get(window_key)
    if aggregate_days is not None:
        return DashboardTrendService(session).build_cached_window_metrics(
            now=now, days=aggregate_days
        )

    computed_after = _window_start(window_key, now)
    plan_repository = RecommendationPlanRepository(session)
    outcome_repository = RecommendationOutcomeRepository(session)
    signals_amount = _count_ticker_signals(
        session, computed_after=computed_after, computed_before=now
    )
    plan_amount = plan_repository.count_plans(computed_after=computed_after, computed_before=now)
    shortlisted_plans = plan_repository.count_plans(
        shortlisted=True, computed_after=computed_after, computed_before=now
    )
    actionable_plans = plan_repository.count_plans(
        action="long", computed_after=computed_after, computed_before=now
    ) + plan_repository.count_plans(
        action="short", computed_after=computed_after, computed_before=now
    )

    news_processed = _count_records(
        session, HistoricalNewsRecord, HistoricalNewsRecord.published_at, computed_after, now
    )
    bars_stored = _count_records(
        session, HistoricalMarketBarRecord, HistoricalMarketBarRecord.bar_time, computed_after, now
    )
    orders_placed = _count_records(
        session,
        BrokerOrderExecutionRecord,
        BrokerOrderExecutionRecord.created_at,
        computed_after,
        now,
    )
    performance = TradingPerformanceMetricsService(session)
    broker_summary = performance.summarize_broker_closed_positions(
        evaluated_after=computed_after, evaluated_before=now
    ).to_dict()
    effective_summary = performance.summarize_effective_outcomes(
        evaluated_after=computed_after, evaluated_before=now
    ).to_dict()
    tweets_processed = _sum_plan_signal_breakdown_count(
        session, "social_item_count", computed_after=computed_after, computed_before=now
    )
    actionability = outcome_repository.summarize_actionability_diagnostics(
        evaluated_after=computed_after, evaluated_before=now
    )

    overall_win_rate_percent = effective_summary["win_rate_percent"]
    total_profit = effective_summary["realized_pnl"]
    average_profit_percent = effective_summary["average_return_percent"]
    broker_average_profit_percent = broker_summary["average_return_percent"]
    simulated_average_profit_percent = effective_summary["simulation_average_return_percent"]

    dashboard_summary = {
        "plan_amount": plan_amount,
        "signals_amount": signals_amount,
        "shortlisted_plans": shortlisted_plans,
        "shortlist_rate_percent": _percentage(plan_amount, signals_amount),
        "actionable_plans": actionable_plans,
        "actionable_rate_percent": _percentage(actionable_plans, plan_amount),
        "overall_win_rate_percent": overall_win_rate_percent,
        "broker_win_rate_percent": broker_summary["win_rate_percent"],
        "total_profit": total_profit,
        "average_profit_percent": average_profit_percent,
        "broker_realized_pnl": broker_summary["realized_pnl"],
        "broker_average_profit_percent": broker_average_profit_percent,
        "simulated_average_profit_percent": simulated_average_profit_percent,
        "win_rate_percent": overall_win_rate_percent,
        "profit_percent": average_profit_percent,
        "win_rate_source": "effective",
        "profit_source": "effective",
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
        "simulated_actionability_diagnostics": actionability,
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
    return DashboardTrendService(session).build_trends(now=now, days=7)


@router.get("/trends")
async def get_dashboard_trends(session: Session = Depends(get_db_session)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {"dashboard_trends": _build_dashboard_trends(session, now=now)}


def _dashboard_quality_payload(
    session: Session, *, now: datetime, window_key: str
) -> dict[str, object]:
    computed_after = _window_start(window_key, now)
    plan_repository = RecommendationPlanRepository(session)
    outcome_repository = RecommendationOutcomeRepository(session)
    effective_outcome_repository = EffectivePlanOutcomeRepository(session)
    quality_service = RecommendationQualitySummaryService(session)
    calibration = RecommendationPlanCalibrationService(effective_outcome_repository).summarize(
        evaluated_after=computed_after, evaluated_before=now
    )
    baselines = RecommendationPlanBaselineService(plan_repository).summarize(
        computed_after=computed_after, computed_before=now
    )
    evidence = RecommendationEvidenceConcentrationService(effective_outcome_repository).summarize(
        evaluated_after=computed_after, evaluated_before=now
    )
    family_review = RecommendationSetupFamilyReviewService(effective_outcome_repository).summarize(
        evaluated_after=computed_after, evaluated_before=now
    )
    entry_miss = outcome_repository.summarize_entry_miss_diagnostics(
        evaluated_after=computed_after, evaluated_before=now
    )
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
    return {"summary": selected_quality}


@router.get("/quality")
def get_dashboard_quality(
    session: Session = Depends(get_db_session),
    window: str = Query("1d", description="Dashboard time window"),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "recommendation_quality": _dashboard_quality_payload(
            session, now=now, window_key=_normalize_window(window)
        )
    }


@router.get("/operator-status")
async def get_dashboard_operator_status(
    session: Session = Depends(get_db_session),
    window: str = Query("1d", description="Dashboard time window"),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    computed_after = _window_start(_normalize_window(window), now)
    effective_outcomes = EffectivePlanOutcomeRepository(session)
    risk = BrokerRiskManager(
        SettingsRepository(session),
        BrokerPositionRepository(session),
        RiskHaltEventRepository(session),
    ).assess()
    data_quality = DataQualityAuditService(session).summarize(limit=1)
    data_quality_summary = {
        key: data_quality[key]
        for key in ("generated_at", "ticker_count", "issue_ticker_count", "issue_counts")
        if key in data_quality
    }
    policy_trust = PolicyTrustReportService(
        effective_outcomes,
        policy_service=TradeDecisionPolicyService(session),
    ).summarize_active_policy(
        evaluated_after=computed_after,
        evaluated_before=now,
        limit=5000,
        degraded_input_summary=None,
        risk_state=risk,
    )
    policy_trust_payload = policy_trust.to_dict()
    return {
        "policy_trust": policy_trust_payload,
        "policy_health": policy_trust_payload["policy_health_headline"],
        "edge_validation_gate": policy_trust_payload["edge_validation_gate"],
        "risk": risk.model_dump(mode="json"),
        "data_quality": data_quality_summary,
        "provider_failures": _provider_failure_summary(
            session, computed_after=computed_after, computed_before=now
        ),
        "broker_submission_health": _broker_submission_health(session, now=now),
        "gating_severity_alert": GatingSeverityAlertService(session).latest_alert(),
    }


def _broker_submission_health(
    session: Session, *, now: datetime, lookback_days: int = 21
) -> dict[str, object]:
    computed_after = now - timedelta(days=lookback_days)
    rows = session.scalars(
        select(BrokerOrderExecutionRecord)
        .where(BrokerOrderExecutionRecord.created_at >= computed_after.replace(tzinfo=None))
        .where(BrokerOrderExecutionRecord.created_at <= now.replace(tzinfo=None))
        .order_by(BrokerOrderExecutionRecord.created_at.desc())
        .limit(1000)
    ).all()
    attempted = [row for row in rows if row.status not in {"skipped"}]
    failed = [row for row in attempted if row.status in {"failed", "rejected"}]
    broker_422 = [
        row
        for row in failed
        if "422" in (row.error_message or "") or "422" in (row.response_payload_json or "")
    ]
    sub_penny = [
        row
        for row in broker_422
        if "sub-penny" in (row.response_payload_json or "").lower()
        or "sub-penny" in (row.error_message or "").lower()
    ]
    failure_rate = round((len(failed) / len(attempted)) * 100.0, 2) if attempted else 0.0
    broker_422_rate = round((len(broker_422) / len(attempted)) * 100.0, 2) if attempted else 0.0
    status = "ok"
    reasons: list[str] = []
    if broker_422:
        status = "danger"
        reasons.append("broker_422_submission_failures")
    if len(sub_penny) >= 2:
        status = "danger"
        reasons.append("systematic_sub_penny_pricing_rejections")
    if failure_rate >= 20.0 and failed:
        status = "danger"
        reasons.append("high_broker_submission_failure_rate")
    elif failed and status == "ok":
        status = "warning"
        reasons.append("broker_submission_failures_present")

    recent_messages: list[str] = []
    for row in broker_422[:5]:
        payload = _json_object(row.response_payload_json)
        message = str(payload.get("message") or row.error_message or "broker submission failed")
        if message not in recent_messages:
            recent_messages.append(message)
    return {
        "status": status,
        "lookback_days": lookback_days,
        "attempted_count": len(attempted),
        "failed_count": len(failed),
        "broker_422_count": len(broker_422),
        "sub_penny_rejection_count": len(sub_penny),
        "failure_rate_percent": failure_rate,
        "broker_422_rate_percent": broker_422_rate,
        "affected_tickers": sorted({row.ticker for row in broker_422 if row.ticker})[:12],
        "latest_failure_at": broker_422[0].created_at if broker_422 else None,
        "recent_error_messages": recent_messages,
        "reasons": reasons,
    }


def _provider_failure_summary(
    session: Session, *, computed_after: datetime, computed_before: datetime
) -> dict[str, object]:
    rows = session.scalars(
        select(ObservabilityEventRecord)
        .where(
            ObservabilityEventRecord.event_type.in_(
                ["provider.request_failed", "provider.request_skipped"]
            )
        )
        .where(ObservabilityEventRecord.created_at >= computed_after.replace(tzinfo=None))
        .where(ObservabilityEventRecord.created_at <= computed_before.replace(tzinfo=None))
        .order_by(ObservabilityEventRecord.created_at.desc())
        .limit(500)
    ).all()
    failed = [row for row in rows if row.event_type == "provider.request_failed"]
    skipped = [row for row in rows if row.event_type == "provider.request_skipped"]
    providers: set[str] = set()
    reasons: list[str] = []
    for row in failed:
        payload = _json_object(row.payload_json)
        provider = str(payload.get("provider") or "").strip()
        reason = str(payload.get("reason") or row.message or "").strip()
        if provider:
            providers.add(provider)
        if reason:
            reasons.append(reason)
    return {
        "failed_request_count": len(failed),
        "skipped_request_count": len(skipped),
        "providers_with_failures": sorted(providers),
        "recent_failure_reasons": list(dict.fromkeys(reasons))[:5],
    }


def _compact_run_payload(run) -> dict[str, object]:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "job_type": run.job_type,
        "status": run.status,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_seconds": run.duration_seconds,
    }


@router.get("")
async def get_dashboard(
    session: Session = Depends(get_db_session),
    window: str = Query("1d", description="Dashboard time window"),
    include_trends: bool = Query(True, description="Include dashboard trend sweep data"),
    include_quality: bool = Query(
        True, description="Include heavier recommendation quality summary"
    ),
    include_diagnostics: bool = Query(
        True, description="Include warning diagnostics from recent runs/plans"
    ),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    window_key = _normalize_window(window)
    computed_after = _window_start(window_key, now)
    watchlists = WatchlistRepository(session).list_all()
    jobs = JobRepository(session).list_all()
    runs = RunRepository(session)
    plan_repository = RecommendationPlanRepository(session)
    confidence_threshold = SettingsDomainService(session).strategy_settings().confidence_threshold

    latest_runs = _recent_items_within_window(
        runs.list_latest_runs_above_confidence_threshold(
            confidence_threshold=confidence_threshold, limit=20
        ),
        computed_after=computed_after,
    )[:10]
    recent_runs = _recent_items_within_window(
        runs.list_latest_runs(limit=50), computed_after=computed_after
    )
    recommendation_plans = plan_repository.list_plans(
        limit=12, computed_after=computed_after, computed_before=now
    )
    recent_plans = (
        plan_repository.list_plans(limit=500, computed_after=computed_after, computed_before=now)
        if include_diagnostics
        else []
    )

    selected_quality = (
        _dashboard_quality_payload(session, now=now, window_key=window_key)["summary"]
        if include_quality
        else None
    )
    selected_window_metrics = _dashboard_window_metrics(session, now=now, window_key=window_key)
    dashboard_trends = _build_dashboard_trends(session, now=now) if include_trends else None

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
    warning_tickers: dict[str, set[str]] = {}

    def add_warning(message: str | None, source: str, ticker: str | None = None) -> None:
        text = str(message or "").strip()
        if not text:
            return
        normalized = text
        if ticker and normalized.startswith(f"{ticker} "):
            normalized = normalized[len(ticker) + 1 :].strip()
        warning_counter[normalized] += 1
        warning_sources.setdefault(normalized, set()).add(source)
        if ticker:
            warning_tickers.setdefault(normalized, set()).add(ticker)

    for run in recent_runs:
        if run.error_message:
            add_warning(run.error_message, f"run:{run.id or 'unknown'}")
        for warning in _extract_warning_messages(getattr(run, "summary_json", None)):
            add_warning(warning, f"run:{run.id or 'unknown'}")
        if getattr(run, "status", None) == RunStatus.COMPLETED_WITH_WARNINGS.value:
            add_warning(
                f"run {run.id or 'unknown'} completed with warnings", f"run:{run.id or 'unknown'}"
            )
    for plan in recent_plans:
        for warning in plan.warnings:
            add_warning(warning, f"plan:{plan.id or 'unknown'}", getattr(plan, "ticker", None))
    if isinstance(selected_quality, dict):
        status_reason = str(selected_quality.get("status_reason") or "").strip()
        if status_reason and str(selected_quality.get("status") or "") in {
            "thin",
            "needs_attention",
        }:
            add_warning(status_reason, "quality")
        add_warning(selected_quality.get("walk_forward_error"), "quality")

    distinct_warnings = [
        {
            "label": warning,
            "count": count,
            "sources": sorted(warning_sources.get(warning, set())),
            "tickers": sorted(warning_tickers.get(warning, set())),
        }
        for warning, count in warning_counter.most_common(8)
    ]

    gating_severity_alert = GatingSeverityAlertService(session).latest_alert()

    return {
        "dashboard_window": window_key,
        "watchlists": watchlists,
        "jobs": jobs,
        "latest_runs": [_compact_run_payload(run) for run in latest_runs],
        "recent_runs": [_compact_run_payload(run) for run in recent_runs],
        "recommendation_plans": recommendation_plans,
        "recommendation_quality": {"summary": selected_quality}
        if isinstance(selected_quality, dict)
        else None,
        "dashboard_summary": selected_window_metrics["dashboard_summary"],
        "technical_summary": selected_window_metrics["technical_summary"],
        "dashboard_trends": dashboard_trends,
        "major_failures": major_failures[:6],
        "distinct_warnings": distinct_warnings,
        "gating_severity_alert": gating_severity_alert,
    }
