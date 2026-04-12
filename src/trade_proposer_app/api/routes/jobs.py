import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import Job, Run, Watchlist
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.watchlists import WatchlistRepository
from trade_proposer_app.services.builders import (
    create_industry_context_refresh_service,
    create_industry_context_service,
    create_macro_context_refresh_service,
    create_macro_context_service,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService
from trade_proposer_app.services.scheduling import CronSchedule, ScheduleParseError

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


def parse_tickers(raw: str) -> list[str]:
    return [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]


def normalize_optional_watchlist_id(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="watchlist_id must be an integer") from exc
    return value


def normalize_job_type(job_type: str | None) -> JobType:
    normalized = (job_type or JobType.PROPOSAL_GENERATION.value).strip()
    try:
        parsed = JobType.parse(normalized)
        if normalized in {"macro_sentiment_refresh", "industry_sentiment_refresh"}:
            logger.warning("deprecated job_type alias received: %s -> %s", normalized, parsed.value)
        return parsed
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid job_type: use proposal_generation, recommendation_evaluation, "
                "plan_generation_tuning, performance_assessment, "
                "macro_context_refresh, industry_context_refresh, or historical_replay"
            ),
        ) from exc


def normalize_optional_schedule(schedule: str | None) -> str | None:
    normalized = schedule.strip() if schedule else None
    if not normalized:
        return None
    try:
        CronSchedule(normalized)
    except ScheduleParseError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid schedule: use a supported 5-field cron expression "
                "with minute hour day-of-month month day-of-week"
            ),
        ) from exc
    return normalized


@router.get("")
async def list_jobs(session: Session = Depends(get_db_session)) -> list[Job]:
    return JobRepository(session).list_all()


@router.post("")
async def create_job(
    name: str = Form(...),
    job_type: str = Form(default=JobType.PROPOSAL_GENERATION.value),
    tickers: str = Form(default=""),
    watchlist_id: str | None = Form(default=None),
    schedule: str | None = Form(default=None),
    session: Session = Depends(get_db_session),
) -> Job:
    normalized_schedule = normalize_optional_schedule(schedule)
    normalized_job_type = normalize_job_type(job_type)
    try:
        return JobRepository(session).create(
            name=name.strip(),
            job_type=normalized_job_type,
            tickers=parse_tickers(tickers),
            watchlist_id=normalize_optional_watchlist_id(watchlist_id),
            schedule=normalized_schedule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{job_id}")
async def update_job(
    job_id: int,
    name: str = Form(...),
    job_type: str = Form(default=JobType.PROPOSAL_GENERATION.value),
    tickers: str = Form(default=""),
    watchlist_id: str | None = Form(default=None),
    schedule: str | None = Form(default=None),
    enabled: str = Form(default="true"),
    session: Session = Depends(get_db_session),
) -> Job:
    normalized_schedule = normalize_optional_schedule(schedule)
    normalized_job_type = normalize_job_type(job_type)
    normalized_enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
    try:
        return JobRepository(session).update(
            job_id=job_id,
            name=name.strip(),
            job_type=normalized_job_type,
            tickers=parse_tickers(tickers),
            watchlist_id=normalize_optional_watchlist_id(watchlist_id),
            schedule=normalized_schedule,
            enabled=normalized_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{job_id}/delete")
async def delete_job(job_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    try:
        JobRepository(session).delete(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "job_id": job_id}


@router.post("/{job_id}/execute")
async def execute_job(job_id: int, session: Session = Depends(get_db_session)) -> Run:
    service = JobExecutionService(
        jobs=JobRepository(session),
        runs=RunRepository(session),
        evaluations=EvaluationExecutionService(
            recommendation_plan_evaluations=RecommendationPlanEvaluationService(session),
        ),
        plan_generation_tuning=PlanGenerationTuningService(session),
        performance_assessment=PerformanceAssessmentService(session),
        macro_context_refresh=create_macro_context_refresh_service(session),
        industry_context_refresh=create_industry_context_refresh_service(session),
        macro_context=create_macro_context_service(session),
        industry_context=create_industry_context_service(session),
        recommendation_plans=RecommendationPlanRepository(session),
        historical_replay=HistoricalReplayService(
            historical_replays=HistoricalReplayRepository(session),
            jobs=JobRepository(session),
            runs=RunRepository(session),
            historical_market_data=HistoricalMarketDataService(HistoricalMarketDataRepository(session)),
        ),
    )
    return service.enqueue_job(job_id)


@router.post("/{job_id}/watchlist")
async def create_watchlist_from_job(job_id: int, session: Session = Depends(get_db_session)) -> Watchlist:
    jobs = JobRepository(session)
    watchlists = WatchlistRepository(session)
    job = jobs.get(job_id)
    if job.job_type != JobType.PROPOSAL_GENERATION:
        raise HTTPException(status_code=400, detail="watchlists can only be created from proposal_generation jobs")
    tickers = jobs.resolve_tickers(job_id)
    return watchlists.create_unique(f"{job.name} watchlist", tickers)
