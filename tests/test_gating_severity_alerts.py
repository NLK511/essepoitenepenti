from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.persistence.models import (
    Base,
    JobRecord,
    ObservabilityEventRecord,
    RecommendationDecisionSampleRecord,
)
from trade_proposer_app.services.gating_severity_alerts import (
    GatingSeverityAlertService,
    GatingSeverityThresholds,
)


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _sample(
    session: Session,
    *,
    created_at: datetime,
    shortlisted: bool,
    decision_type: str = "near_miss",
    review_priority: str = "high",
    confidence_gap_percent: float = 5.0,
    benchmark_status: str = "pending",
) -> None:
    session.add(
        RecommendationDecisionSampleRecord(
            ticker=f"T{created_at.microsecond}",
            horizon="1w",
            action="no_action",
            decision_type=decision_type,
            decision_reason="not_shortlisted"
            if not shortlisted
            else "below_calibrated_action_threshold",
            shortlisted=shortlisted,
            confidence_percent=70.0,
            calibrated_confidence_percent=68.0,
            effective_threshold_percent=53.6,
            confidence_gap_percent=confidence_gap_percent,
            setup_family="breakout",
            review_priority=review_priority,
            benchmark_status=benchmark_status,
            created_at=created_at.replace(tzinfo=None),
        )
    )
    session.commit()


def test_gating_severity_alert_records_critical_when_zero_actionable_and_many_near_misses() -> None:
    session = create_session()
    now = datetime(2026, 6, 14, tzinfo=timezone.utc)
    for index in range(6):
        _sample(session, created_at=now - timedelta(hours=index), shortlisted=False)

    payload = GatingSeverityAlertService(
        session,
        thresholds=GatingSeverityThresholds(
            min_samples=5,
            warning_high_priority_non_shortlisted=3,
            warning_near_miss_non_shortlisted=3,
            warning_positive_gap_non_shortlisted_rate_percent=10.0,
        ),
    ).evaluate(now=now, window_days=7)

    assert payload["severity"] == "critical"
    assert "zero_actionable_plans" in payload["reasons"]
    assert payload["metrics"]["near_miss_non_shortlisted"] == 6
    event = session.scalars(select(ObservabilityEventRecord)).one()
    assert event.event_type == "decision_gating.severity_check"
    assert event.severity == "critical"


def test_gating_severity_alert_is_info_when_sample_count_is_too_small() -> None:
    session = create_session()
    now = datetime(2026, 6, 14, tzinfo=timezone.utc)
    _sample(session, created_at=now, shortlisted=False)

    payload = GatingSeverityAlertService(
        session,
        thresholds=GatingSeverityThresholds(min_samples=5),
    ).evaluate(now=now, window_days=7, record_event=False)

    assert payload["severity"] == "info"
    assert payload["reasons"] == ["insufficient_sample_count"]


def test_latest_alert_returns_full_observability_payload() -> None:
    session = create_session()
    now = datetime(2026, 6, 14, tzinfo=timezone.utc)
    for index in range(6):
        _sample(session, created_at=now - timedelta(hours=index), shortlisted=False)

    service = GatingSeverityAlertService(
        session,
        thresholds=GatingSeverityThresholds(
            min_samples=5,
            warning_high_priority_non_shortlisted=3,
            warning_near_miss_non_shortlisted=3,
        ),
    )
    service.evaluate(now=now, window_days=7)

    latest = service.latest_alert()

    assert latest is not None
    assert latest["event_type"] == "decision_gating.severity_check"
    assert latest["severity"] == "critical"
    assert latest["metrics"]["near_miss_non_shortlisted"] == 6
    assert latest["window_days"] == 7


def test_default_weekly_gating_severity_job_is_scheduled_for_saturday_0500() -> None:
    from trade_proposer_app.services.default_jobs import ensure_default_gating_severity_check_job

    session = create_session()

    spec = ensure_default_gating_severity_check_job(session)

    assert spec["cron"] == "00 05 * * SAT"
    job = session.scalars(
        select(JobRecord).where(JobRecord.name == "Auto: Gating Severity Check Weekly")
    ).one()
    assert job.job_type == JobType.GATING_SEVERITY_CHECK.value
    assert job.schedule == "00 05 * * SAT"
    assert job.enabled is True
