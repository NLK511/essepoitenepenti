from datetime import datetime, timezone

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.builders import create_proposal_service
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.evaluations import RecommendationEvaluationService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.optimizations import WeightOptimizationService
from trade_proposer_app.services.scheduling import ScheduleParseError, latest_due_at, normalize_schedule_time


def enqueue_enabled_jobs(now: datetime | None = None) -> int:
    session = SessionLocal()
    try:
        jobs_repository = JobRepository(session)
        runs_repository = RunRepository(session)
        settings_repository = SettingsRepository(session)
        jobs = jobs_repository.list_enabled()
        service = JobExecutionService(
            jobs=jobs_repository,
            runs=runs_repository,
            proposals=create_proposal_service(session),
            evaluations=EvaluationExecutionService(RecommendationEvaluationService(session)),
            optimizations=WeightOptimizationService(
                session=session,
                minimum_resolved_trades=settings_repository.get_optimization_minimum_resolved_trades(),
            ),
        )
        normalized_now = normalize_schedule_time(now or datetime.now(timezone.utc))
        count = 0
        for job in jobs:
            if not job.cron:
                continue
            try:
                scheduled_for = latest_due_at(job.cron, normalized_now)
            except ScheduleParseError as exc:
                print(f"scheduler: skipping job {job.id} ({job.name}) due to invalid schedule '{job.cron}': {exc}")
                continue
            if scheduled_for is None:
                continue
            if scheduled_for != normalized_now:
                continue
            if runs_repository.get_run_for_job_and_scheduled_for(job.id or 0, scheduled_for) is not None:
                continue
            if job.job_type == JobType.WEIGHT_OPTIMIZATION and runs_repository.get_active_run_for_job_type(JobType.WEIGHT_OPTIMIZATION) is not None:
                continue
            if runs_repository.get_active_run_for_job(job.id or 0) is not None:
                continue
            service.enqueue_job(job.id or 0, scheduled_for=scheduled_for)
            count += 1
        return count
    finally:
        session.close()


def main() -> None:
    count = enqueue_enabled_jobs()
    print(f"scheduler: enqueued {count} scheduled job(s)")


if __name__ == "__main__":
    main()
