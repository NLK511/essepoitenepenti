from __future__ import annotations

from sqlalchemy import select

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.persistence.models import JobRecord
from trade_proposer_app.repositories.broker_accounts import BrokerAccountRepository
from trade_proposer_app.repositories.jobs import JobRepository

DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS: list[dict[str, str]] = [
    {
        "name": "Auto: Recommendation Evaluation APAC Close",
        "cron": "35 08 * * MON-FRI",
        "schedule_rationale": "Runs a few minutes after the APAC close so evaluation can use the completed close bar without colliding with the regional bars refresh job.",
    },
    {
        "name": "Auto: Recommendation Evaluation Europe Close",
        "cron": "05 17 * * MON-FRI",
        "schedule_rationale": "Runs a few minutes after the Europe close so evaluation sees the finalized session and stays clear of the Europe bars refresh job.",
    },
    {
        "name": "Auto: Recommendation Evaluation US Close",
        "cron": "35 20 * * MON-FRI",
        "schedule_rationale": "Runs a few minutes after the US close so evaluation can reuse the finished day bar and stay clear of the US bars refresh job.",
    },
]

DEFAULT_BROKER_STEERING_JOB_SPEC = {
    "name": "Auto: Broker Steering Dry Run",
    "cron": "*/30 * * * *",
    "schedule_rationale": "Runs a conservative dry-run steering pass periodically so decision audits stay fresh before live enablement.",
}

DEFAULT_GATING_SEVERITY_CHECK_JOB_SPEC = {
    "name": "Auto: Gating Severity Check Weekly",
    "cron": "00 05 * * SAT",
    "schedule_rationale": "Runs once per week on Saturday at 05:00 UTC over the previous 7 days to detect whether shortlist/signal gating may be too severe.",
}

DEFAULT_RECOMMENDATION_CALIBRATION_REFRESH_JOB_SPEC = {
    "name": "Auto: Recommendation Calibration Refresh Weekly",
    "cron": "30 06 * * SAT",
    "schedule_rationale": "Runs once per week on Saturday at 06:30 UTC to refresh the persisted execution-only confidence calibration snapshot used by live plan framing.",
}

DEFAULT_ACTIONABILITY_FLOOR_CALIBRATION_JOB_SPEC = {
    "name": "Auto: Actionability Floor Calibration Weekly",
    "cron": "00 07 * * SAT",
    "schedule_rationale": "Runs once per week on Saturday at 07:00 UTC to rescore the latest completed last-month replay batch across 40%-60% downstream actionability floors. It proposes paper-only tuning evidence and does not mutate live settings.",
}

DEFAULT_PERFORMANCE_ASSESSMENT_JOB_SPEC = {
    "name": "Auto: Performance Assessment",
    "cron": "0 0 * * *",
    "schedule_rationale": "Runs daily at midnight UTC to summarize recommendation quality, calibration, evidence concentration, and performance trends.",
}

DEFAULT_FUNDAMENTAL_ANALYSIS_JOB_SPECS: list[dict[str, str | list[str]]] = [
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 1",
        "cron": "15 06 * * SAT",
        "schedule_rationale": "Weekend batch 1 refreshes due point-in-time fundamental snapshots while market/proposal-generation load is lower; capped batches reduce provider quota pressure.",
        "legacy_names": ["Auto: Fundamental Analysis Monthly", "Auto: Fundamental Analysis Weekly"],
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 2",
        "cron": "15 09 * * SAT",
        "schedule_rationale": "Weekend batch 2 continues due fundamental snapshots after earlier fresh snapshots are skipped.",
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 3",
        "cron": "15 12 * * SAT",
        "schedule_rationale": "Weekend batch 3 continues due fundamental snapshots after earlier fresh snapshots are skipped.",
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 4",
        "cron": "15 15 * * SAT",
        "schedule_rationale": "Weekend batch 4 continues due fundamental snapshots after earlier fresh snapshots are skipped.",
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 5",
        "cron": "15 06 * * SUN",
        "schedule_rationale": "Weekend batch 5 continues due fundamental snapshots on Sunday after Saturday batches.",
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 6",
        "cron": "15 09 * * SUN",
        "schedule_rationale": "Weekend batch 6 continues due fundamental snapshots on Sunday after earlier batches.",
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 7",
        "cron": "15 12 * * SUN",
        "schedule_rationale": "Weekend batch 7 continues due fundamental snapshots on Sunday after earlier batches.",
    },
    {
        "name": "Auto: Fundamental Analysis Weekend Batch 8",
        "cron": "15 15 * * SUN",
        "schedule_rationale": "Weekend batch 8 completes the weekend due-snapshot sweep under the per-run provider cap.",
    },
]


def ensure_default_recommendation_evaluation_jobs(session) -> list[dict[str, str]]:
    job_repo = JobRepository(session)
    for spec in DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS:
        _ensure_job(
            job_repo, session, spec["name"], spec["cron"], JobType.RECOMMENDATION_EVALUATION
        )
    return DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS


def ensure_default_broker_steering_job(session) -> dict[str, str]:
    job_repo = JobRepository(session)
    _ensure_job(
        job_repo,
        session,
        DEFAULT_BROKER_STEERING_JOB_SPEC["name"],
        DEFAULT_BROKER_STEERING_JOB_SPEC["cron"],
        JobType.BROKER_STEERING,
    )
    return DEFAULT_BROKER_STEERING_JOB_SPEC


def ensure_default_fundamental_analysis_job(session) -> dict[str, list[dict[str, str | list[str]]]]:
    job_repo = JobRepository(session)
    for spec in DEFAULT_FUNDAMENTAL_ANALYSIS_JOB_SPECS:
        _ensure_job(
            job_repo,
            session,
            str(spec["name"]),
            str(spec["cron"]),
            JobType.FUNDAMENTAL_ANALYSIS_REFRESH,
            legacy_names=list(spec.get("legacy_names", [])),
        )
    return {"jobs": DEFAULT_FUNDAMENTAL_ANALYSIS_JOB_SPECS}


def ensure_default_gating_severity_check_job(session) -> dict[str, str]:
    job_repo = JobRepository(session)
    _ensure_job(
        job_repo,
        session,
        DEFAULT_GATING_SEVERITY_CHECK_JOB_SPEC["name"],
        DEFAULT_GATING_SEVERITY_CHECK_JOB_SPEC["cron"],
        JobType.GATING_SEVERITY_CHECK,
    )
    return DEFAULT_GATING_SEVERITY_CHECK_JOB_SPEC


def ensure_default_recommendation_calibration_refresh_job(session) -> dict[str, str]:
    job_repo = JobRepository(session)
    _ensure_job(
        job_repo,
        session,
        DEFAULT_RECOMMENDATION_CALIBRATION_REFRESH_JOB_SPEC["name"],
        DEFAULT_RECOMMENDATION_CALIBRATION_REFRESH_JOB_SPEC["cron"],
        JobType.RECOMMENDATION_CALIBRATION_REFRESH,
    )
    return DEFAULT_RECOMMENDATION_CALIBRATION_REFRESH_JOB_SPEC


def ensure_default_actionability_floor_calibration_job(session) -> dict[str, str]:
    job_repo = JobRepository(session)
    _ensure_job(
        job_repo,
        session,
        DEFAULT_ACTIONABILITY_FLOOR_CALIBRATION_JOB_SPEC["name"],
        DEFAULT_ACTIONABILITY_FLOOR_CALIBRATION_JOB_SPEC["cron"],
        JobType.PLAN_GENERATION_TUNING,
    )
    return DEFAULT_ACTIONABILITY_FLOOR_CALIBRATION_JOB_SPEC


def ensure_default_performance_assessment_job(session) -> dict[str, str]:
    job_repo = JobRepository(session)
    _ensure_job(
        job_repo,
        session,
        DEFAULT_PERFORMANCE_ASSESSMENT_JOB_SPEC["name"],
        DEFAULT_PERFORMANCE_ASSESSMENT_JOB_SPEC["cron"],
        JobType.PERFORMANCE_ASSESSMENT,
    )
    return DEFAULT_PERFORMANCE_ASSESSMENT_JOB_SPEC


def ensure_default_broker_accounts(session) -> dict[str, str]:
    account = BrokerAccountRepository(session).ensure_default_alpaca_paper_account()
    return {"default_alpaca_paper_account_id": account.broker_account_id}


def _ensure_job(
    repo: JobRepository,
    session,
    job_name: str,
    cron: str,
    job_type: JobType,
    *,
    legacy_names: list[str] | None = None,
) -> None:
    names = [job_name, *(legacy_names or [])]
    record = session.scalars(select(JobRecord).where(JobRecord.name.in_(names))).first()
    if record is not None:
        repo.update(
            job_id=record.id,
            name=job_name,
            job_type=job_type,
            tickers=[],
            watchlist_id=None,
            schedule=cron,
            enabled=True,
        )
        return
    repo.create(
        name=job_name,
        job_type=job_type,
        tickers=[],
        watchlist_id=None,
        schedule=cron,
        enabled=True,
    )
