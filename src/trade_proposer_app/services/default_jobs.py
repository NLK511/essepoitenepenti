from __future__ import annotations

from sqlalchemy import select

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.persistence.models import JobRecord
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


def ensure_default_recommendation_evaluation_jobs(session) -> list[dict[str, str]]:
    job_repo = JobRepository(session)
    for spec in DEFAULT_RECOMMENDATION_EVALUATION_JOB_SPECS:
        _ensure_job(job_repo, session, spec["name"], spec["cron"], JobType.RECOMMENDATION_EVALUATION)
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


def _ensure_job(repo: JobRepository, session, job_name: str, cron: str, job_type: JobType) -> None:
    record = session.scalars(select(JobRecord).where(JobRecord.name == job_name)).first()
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
