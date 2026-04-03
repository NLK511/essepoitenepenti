from datetime import datetime, timezone

from trade_proposer_app.config import settings
from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.builders import (
    create_industry_context_service,
    create_macro_context_service,
    create_watchlist_orchestration_service,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService
from trade_proposer_app.services.scheduling import (
    ScheduleParseError,
    latest_due_at,
    latest_due_at_in_timezone,
    normalize_schedule_time,
)
from trade_proposer_app.services.watchlist_policy import WatchlistPolicyService


def enqueue_enabled_jobs(now: datetime | None = None) -> int:
    session = SessionLocal()
    try:
        jobs_repository = JobRepository(session)
        runs_repository = RunRepository(session)
        watchlists_repository = WatchlistRepository(session)
        policy_service = WatchlistPolicyService()
        jobs = jobs_repository.list_enabled()
        service = JobExecutionService(
            jobs=jobs_repository,
            runs=runs_repository,
            evaluations=EvaluationExecutionService(
                recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
            ),
            plan_generation_tuning=PlanGenerationTuningService(session),
            watchlist_orchestration=create_watchlist_orchestration_service(session),
            recommendation_plans=RecommendationPlanRepository(session),
        )
        normalized_now = normalize_schedule_time(now or datetime.now(timezone.utc))
        runs_repository.recover_stale_running_runs(
            stale_after_seconds=settings.run_stale_after_seconds,
            now=normalized_now,
        )
        count = 0
        for job in jobs:
            watchlist = None
            if job.watchlist_id is not None:
                try:
                    watchlist = watchlists_repository.get(job.watchlist_id)
                except ValueError as exc:
                    print(f"scheduler: skipping job {job.id} ({job.name}) because watchlist lookup failed: {exc}")
                    continue
            resolved_schedule = policy_service.resolve_job_schedule(job, watchlist)
            if resolved_schedule is None:
                continue
            schedule_expression, schedule_timezone, schedule_source = resolved_schedule
            try:
                scheduled_for = (
                    latest_due_at(schedule_expression, normalized_now)
                    if schedule_timezone == "UTC"
                    else latest_due_at_in_timezone(schedule_expression, normalized_now, schedule_timezone)
                )
            except ScheduleParseError as exc:
                print(
                    f"scheduler: skipping job {job.id} ({job.name}) due to invalid schedule "
                    f"'{schedule_expression}' from {schedule_source}: {exc}"
                )
                continue
            if scheduled_for is None:
                continue
            if scheduled_for != normalized_now:
                continue
            if runs_repository.get_run_for_job_and_scheduled_for(job.id or 0, scheduled_for) is not None:
                continue
            if job.job_type == JobType.PLAN_GENERATION_TUNING and runs_repository.get_active_run_for_job_type(JobType.PLAN_GENERATION_TUNING) is not None:
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
