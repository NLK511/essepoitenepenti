from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import (
    PlanGenerationTuningEvent,
    PlanGenerationWalkForwardSummary,
)
from trade_proposer_app.persistence.models import PlanGenerationTuningEventRecord, RunRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.persistence.models import HistoricalReplayBatchRecord, HistoricalReplaySliceRecord, ReplayEligibilityRecord
from trade_proposer_app.services.plan_generation_tuning import (
    PlanGenerationTuningError,
    PlanGenerationTuningService,
)
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)
from trade_proposer_app.services.plan_generation_walk_forward import (
    PlanGenerationWalkForwardService,
)
from trade_proposer_app.services.replay_validation_efficiency import replay_candidate_efficiency_summary
from trade_proposer_app.services.settings_mutations import SettingsMutationService
from trade_proposer_app.utils.json_payloads import loads_json_list as _loads_json_list
from trade_proposer_app.utils.json_payloads import loads_json_object as _loads_json_object

router = APIRouter(prefix="/plan-generation-tuning", tags=["plan-generation-tuning"])

STANDARD_TUNING_SYSTEM_JOB_NAME = "plan-generation-tuning-standard-search"
LARGE_TUNING_SYSTEM_JOB_NAME = "plan-generation-tuning-large-search"


PROMOTION_EVENT_TYPES = {
    "baseline_seeded",
    "baseline_reseeded",
    "config_promoted",
    "config_promoted_manual",
    "config_promoted_manual_candidate",
}


class PlanGenerationWalkForwardRequest(BaseModel):
    candidate_config: dict[str, float] | None = None
    candidate_label: str | None = None
    candidate_config_version_id: int | None = None
    candidate_id: int | None = None
    baseline_config_version_id: int | None = None
    lookback_days: int = Field(default=365, ge=30, le=3650)
    validation_days: int = Field(default=90, ge=5, le=730)
    step_days: int = Field(default=30, ge=1, le=365)
    min_validation_resolved: int = Field(default=8, ge=1, le=500)
    limit: int | None = Field(default=None, ge=1, le=10000)


def _score_payload(
    service: PlanGenerationTuningService,
    records: list,
    config: dict[str, float],
) -> dict[str, object]:
    actionable, wins, expected_value, ambiguous = service._score_records(records, config)  # noqa: SLF001
    return {
        "actionable_count": actionable,
        "win_count": wins,
        "win_rate_percent": round((wins / actionable) * 100.0, 2) if actionable else None,
        "expected_value": round(expected_value, 4),
        "ambiguous_count": ambiguous,
        "record_count": len(records),
    }


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _run_summary_payload(row: RunRecord) -> dict[str, object]:
    summary = RunRepository._deserialize_json_object(row.summary_json) if row.summary_json else {}  # noqa: SLF001
    artifact = (
        RunRepository._deserialize_json_object(row.artifact_json) if row.artifact_json else {}
    )  # noqa: SLF001
    timing = RunRepository._deserialize_json_object(row.timing_json) if row.timing_json else {}  # noqa: SLF001
    request = artifact.get("plan_generation_tuning_request") if isinstance(artifact, dict) else None
    request = request if isinstance(request, dict) else {}
    best = summary.get("best_candidate") if isinstance(summary, dict) else None
    if best is None and isinstance(artifact, dict):
        large = artifact.get("large_plan_generation_tuning_search")
        if isinstance(large, dict):
            candidates = large.get("top_candidates")
            if isinstance(candidates, list) and candidates:
                best = candidates[0]
    return {
        "id": row.id,
        "job_id": row.job_id,
        "job_type": row.job_type,
        "status": row.status,
        "mode": (
            summary.get("mode") or request.get("mode") or request.get("search_kind") or "unknown"
        ),
        "search_kind": summary.get("search_kind") or request.get("search_kind"),
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "duration_seconds": row.duration_seconds,
        "error_message": row.error_message or None,
        "summary": summary,
        "timing": timing,
        "request": request,
        "artifact_path": summary.get("artifact_path") if isinstance(summary, dict) else None,
        "best_candidate": best,
        "artifact": artifact,
    }


@router.get("")
async def get_plan_generation_tuning_state(
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    return PlanGenerationTuningService(session).describe()


@router.get("/runs")
async def list_plan_generation_tuning_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = PlanGenerationTuningService(session).repository
    runs = repository.list_runs(limit=limit, offset=offset)
    return {"items": runs, "total": repository.count_runs(), "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
async def get_plan_generation_tuning_run(run_id: int, session: Session = Depends(get_db_session)):
    try:
        return PlanGenerationTuningService(session).repository.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/replay-artifacts")
async def get_plan_generation_tuning_replay_artifacts(run_id: int, session: Session = Depends(get_db_session)) -> dict[str, object]:
    try:
        run = PlanGenerationTuningService(session).repository.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    batches = session.query(HistoricalReplayBatchRecord).all()
    matched_batches = []
    for batch in batches:
        config = _loads_json_object(batch.config_json)
        if int(config.get("plan_generation_tuning_run_id") or 0) != run_id:
            continue
        slices = session.query(HistoricalReplaySliceRecord).filter(HistoricalReplaySliceRecord.replay_batch_id == batch.id).order_by(HistoricalReplaySliceRecord.as_of.asc()).all()
        eligibility_rows = session.query(ReplayEligibilityRecord).filter(ReplayEligibilityRecord.replay_batch_id == batch.id).order_by(ReplayEligibilityRecord.id.asc()).all()
        matched_batches.append(
            {
                "batch_id": batch.id,
                "status": batch.status,
                "candidate_id": config.get("plan_generation_tuning_candidate_id"),
                "candidate_rank": config.get("plan_generation_tuning_candidate_rank"),
                "candidate_config_hash": config.get("candidate_config_hash"),
                "slice_ids": [row.id for row in slices],
                "slices": [
                    {
                        "slice_id": row.id,
                        "as_of": row.as_of.isoformat(),
                        "status": row.status,
                        "run_id": row.run_id,
                        "coverage_url": f"/api/historical-replay/slices/{row.id}/coverage",
                    }
                    for row in slices
                ],
                "eligibility_records": [
                    {
                        "id": row.id,
                        "replay_slice_id": row.replay_slice_id,
                        "replay_plan_outcome_id": row.replay_plan_outcome_id,
                        "recommendation_plan_id": row.recommendation_plan_id,
                        "ticker": row.ticker,
                        "tier": row.tier,
                        "eligible_for_tuning": row.eligible_for_tuning,
                        "resolution_source": row.resolution_source,
                        "outcome": row.outcome,
                        "rejection_reasons": _loads_json_list(row.rejection_reasons_json),
                    }
                    for row in eligibility_rows
                ],
            }
        )
    return {"run_id": run.id, "mode": run.mode, "batch_count": len(matched_batches), "batches": matched_batches}


@router.post("/run")
async def run_plan_generation_tuning(
    ticker: str | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=5000),
    mode: str = Query(default="point_in_time_replay"),
    apply: bool = Query(default=False),
    session: Session = Depends(get_db_session),
):
    try:
        jobs = JobRepository(session)
        runs = RunRepository(session)
        runs.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
        existing_run = runs.get_active_run_for_job_type(JobType.PLAN_GENERATION_TUNING)
        if existing_run is not None:
            payload = existing_run.model_dump(mode="json")
            payload.update(
                {
                    "queued_new_run": False,
                    "reused_active_run": True,
                    "queue_message": f"A plan-generation tuning run is already {existing_run.status.value}; reusing run {existing_run.id} instead of queueing a duplicate.",
                }
            )
            return payload
        job = jobs.get_or_create_system_job(
            STANDARD_TUNING_SYSTEM_JOB_NAME, JobType.PLAN_GENERATION_TUNING
        )
        queued_run = JobExecutionService(jobs=jobs, runs=runs).enqueue_job(job.id or 0)
        runs.set_artifact(
            queued_run.id or 0,
            {
                "plan_generation_tuning_request": {
                    "mode": mode,
                    "tuning_source_mode": "stored_plan_rescore" if mode.strip().lower() in {"manual", "stored_plan_rescore"} else "point_in_time_replay",
                    "apply": apply,
                    "ticker": ticker.upper() if ticker else None,
                    "setup_family": setup_family.strip() if setup_family else None,
                    "limit": limit,
                }
            },
        )
        queued = runs.get_run(queued_run.id or 0)
        payload = queued.model_dump(mode="json")
        payload.update(
            {
                "queued_new_run": True,
                "reused_active_run": False,
                "queue_message": f"Queued plan-generation tuning run {queued.id}. A worker will execute it when available.",
            }
        )
        return payload
    except PlanGenerationTuningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/large-search/run")
async def run_large_plan_generation_tuning_search(
    coarse_candidates: int = Query(default=20_000, ge=1, le=1_000_000),
    fine_candidates: int = Query(default=5_000, ge=0, le=500_000),
    top_k: int = Query(default=100, ge=1, le=500),
    fine_seeds: int = Query(default=20, ge=1, le=100),
    seed: int = Query(default=20260614, ge=1),
    limit: int | None = Query(default=None, ge=1, le=5000),
    min_validation_actionable: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db_session),
):
    jobs = JobRepository(session)
    runs = RunRepository(session)
    runs.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
    existing_run = runs.get_active_run_for_job_type(JobType.PLAN_GENERATION_TUNING)
    if existing_run is not None:
        return existing_run
    job = jobs.get_or_create_system_job(
        LARGE_TUNING_SYSTEM_JOB_NAME, JobType.PLAN_GENERATION_TUNING
    )
    queued_run = JobExecutionService(jobs=jobs, runs=runs).enqueue_job(job.id or 0)
    runs.set_artifact(
        queued_run.id or 0,
        {
            "plan_generation_tuning_request": {
                "search_kind": "large",
                "mode": "large_tuning_search",
                "apply": False,
                "coarse_candidates": coarse_candidates,
                "fine_candidates": fine_candidates,
                "top_k": top_k,
                "fine_seeds": fine_seeds,
                "seed": seed,
                "limit": limit,
                "min_validation_actionable": min_validation_actionable,
                "batch_log_interval": 1000,
                "artifact_path": (
                    "artifacts/large-plan-generation-parameter-search-run-"
                    f"{queued_run.id or 'queued'}.json"
                ),
                "cache_path": (
                    "artifacts/large-plan-generation-parameter-search-run-"
                    f"{queued_run.id or 'queued'}.cache.jsonl"
                ),
            }
        },
    )
    return runs.get_run(queued_run.id or 0)


@router.get("/job-runs")
async def list_plan_generation_tuning_job_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    query = select(RunRecord).where(RunRecord.job_type == JobType.PLAN_GENERATION_TUNING.value)
    total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = session.scalars(
        query.order_by(desc(RunRecord.created_at), desc(RunRecord.id))
        .offset(max(0, offset))
        .limit(max(1, limit))
    ).all()
    return {
        "items": [_run_summary_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/configs/portfolio")
async def list_plan_generation_tuning_config_portfolio(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    service = PlanGenerationTuningService(session)
    repository = service.repository
    configs = repository.list_config_versions(limit=limit, offset=offset)
    records = service._eligible_records(ticker=None, setup_family=None, limit=None)  # noqa: SLF001
    described_state = service.describe()["state"]
    active_id = described_state.active_config_version_id
    promotion_rows = session.scalars(
        select(PlanGenerationTuningEventRecord)
        .where(PlanGenerationTuningEventRecord.event_type.in_(PROMOTION_EVENT_TYPES))
        .order_by(
            PlanGenerationTuningEventRecord.created_at.asc(),
            PlanGenerationTuningEventRecord.id.asc(),
        )
    ).all()
    active_periods_by_config: dict[int, list[dict[str, object]]] = {}
    for index, event in enumerate(promotion_rows):
        if event.config_version_id is None:
            continue
        next_event = promotion_rows[index + 1] if index + 1 < len(promotion_rows) else None
        active_periods_by_config.setdefault(event.config_version_id, []).append(
            {
                "started_at": event.created_at,
                "ended_at": next_event.created_at if next_event is not None else None,
                "event_type": event.event_type,
                "is_current": next_event is None,
            }
        )
    items: list[dict[str, object]] = []
    for config in configs:
        normalized = normalize_plan_generation_tuning_config(config.config)
        nominal: dict[str, object] | None = None
        if config.source_candidate_id is not None:
            try:
                candidate = repository.get_candidate(config.source_candidate_id)
                nominal = {
                    "candidate_id": candidate.id,
                    "run_id": candidate.run_id,
                    "rank": candidate.rank,
                    "promotion_eligible": candidate.promotion_eligible,
                    "metrics": candidate.metric_breakdown,
                    "rejection_reasons": candidate.rejection_reasons,
                }
            except ValueError:
                nominal = {"missing_source_candidate": config.source_candidate_id}
        periods = active_periods_by_config.get(config.id or 0, [])
        active_records = []
        for period in periods:
            raw_started_at = period.get("started_at")
            raw_ended_at = period.get("ended_at")
            started_at = _normalize_datetime(
                raw_started_at if isinstance(raw_started_at, datetime) else None
            )
            ended_at = _normalize_datetime(
                raw_ended_at if isinstance(raw_ended_at, datetime) else None
            )
            if started_at is None:
                continue
            for record in records:
                computed_at = _normalize_datetime(record.plan.computed_at)
                if (
                    computed_at is not None
                    and computed_at >= started_at
                    and (ended_at is None or computed_at < ended_at)
                ):
                    active_records.append(record)
        items.append(
            {
                "config": config,
                "is_current": config.id == active_id,
                "nominal_performance": nominal,
                "historical_performance": _score_payload(service, records, normalized),
                "active_period_performance": (
                    _score_payload(service, active_records, normalized) if active_records else None
                ),
                "active_periods": periods,
            }
        )
    return {
        "items": items,
        "total": repository.count_config_versions(),
        "limit": limit,
        "offset": offset,
    }


@router.post("/walk-forward")
async def compare_plan_generation_tuning_config_walk_forward(
    request: PlanGenerationWalkForwardRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    service = PlanGenerationTuningService(session)
    repository = service.repository
    baseline_version = (
        repository.get_config_version(request.baseline_config_version_id)
        if request.baseline_config_version_id
        else service._resolve_active_config_version()  # noqa: SLF001
    )
    if request.candidate_config is not None:
        candidate_config = normalize_plan_generation_tuning_config(request.candidate_config)
        candidate_label = request.candidate_label or "raw-config"
    elif request.candidate_config_version_id is not None:
        version = repository.get_config_version(request.candidate_config_version_id)
        candidate_config = normalize_plan_generation_tuning_config(version.config)
        candidate_label = version.version_label
    elif request.candidate_id is not None:
        candidate = repository.get_candidate(request.candidate_id)
        candidate_config = normalize_plan_generation_tuning_config(candidate.config)
        candidate_label = f"candidate-{candidate.id or candidate.rank or 'unknown'}"
    else:
        raise HTTPException(
            status_code=400,
            detail="candidate_config, candidate_config_version_id, or candidate_id is required",
        )
    records = service._eligible_records(  # noqa: SLF001
        ticker=None,
        setup_family=None,
        limit=request.limit,
    )
    summary = PlanGenerationWalkForwardService(service).summarize_records(
        records=records,
        candidate_config=candidate_config,
        baseline_config=normalize_plan_generation_tuning_config(baseline_version.config),
        candidate_label=candidate_label,
        baseline_label=baseline_version.version_label,
        lookback_days=request.lookback_days,
        validation_days=request.validation_days,
        step_days=request.step_days,
        min_validation_resolved=request.min_validation_resolved,
    )
    return {
        "summary": summary,
        "candidate_config": candidate_config,
        "baseline_config": normalize_plan_generation_tuning_config(baseline_version.config),
        "baseline_version": baseline_version,
        "candidate_label": candidate_label,
    }


@router.delete("/configs/{config_version_id}")
async def retire_plan_generation_tuning_config(
    config_version_id: int,
    session: Session = Depends(get_db_session),
):
    service = PlanGenerationTuningService(session)
    described_state = service.describe()["state"]
    active_id = described_state.active_config_version_id
    if config_version_id == active_id:
        raise HTTPException(status_code=400, detail="cannot delete the currently active config")
    try:
        version = service.repository.update_config_status(config_version_id, "deleted")
        service.repository.create_event(
            PlanGenerationTuningEvent(
                event_type="config_deleted_manual",
                config_version_id=version.id,
                payload={"version_label": version.version_label},
            )
        )
        return version
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/configs")
async def list_plan_generation_tuning_configs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = PlanGenerationTuningService(session).repository
    configs = repository.list_config_versions(limit=limit, offset=offset)
    return {
        "items": configs,
        "total": repository.count_config_versions(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/configs/{config_version_id}")
async def get_plan_generation_tuning_config(
    config_version_id: int, session: Session = Depends(get_db_session)
):
    repository = PlanGenerationTuningService(session).repository
    try:
        version = repository.get_config_version(config_version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "config": version,
        "events": repository.list_events(config_version_id=config_version_id, limit=50),
    }


@router.post("/configs/{config_version_id}/promote")
async def promote_plan_generation_tuning_config(
    config_version_id: int, session: Session = Depends(get_db_session)
):
    try:
        version = PlanGenerationTuningService(session).promote_config_version(config_version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanGenerationTuningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"config": version, "promoted": True}


@router.post("/runs/{run_id}/candidates/{candidate_id}/promote")
async def promote_plan_generation_tuning_candidate(
    run_id: int, candidate_id: int, session: Session = Depends(get_db_session)
):
    try:
        version = PlanGenerationTuningService(session).promote_candidate(run_id, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanGenerationTuningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"config": version, "promoted": True}


@router.post("/settings")
async def set_plan_generation_tuning_settings(
    auto_enabled: str = Form(default="false"),
    auto_promote_enabled: str = Form(default="false"),
    min_actionable_resolved: str = Form(default="20"),
    min_validation_resolved: str = Form(default="8"),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        settings_payload = SettingsMutationService(session).set_plan_generation_tuning_settings(
            auto_enabled=auto_enabled,
            auto_promote_enabled=auto_promote_enabled,
            min_actionable_resolved=min_actionable_resolved,
            min_validation_resolved=min_validation_resolved,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid plan generation tuning settings: {exc}"
        ) from exc
    return {"plan_generation_tuning": settings_payload}


@router.get("/parameters")
async def get_plan_generation_tuning_parameters(
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    state = PlanGenerationTuningService(session).describe()
    return {
        "objective_name": state["objective_name"],
        "parameter_schema_version": state["parameter_schema_version"],
        "parameters": state["parameters"],
    }


@router.get("/replay-batches/{replay_batch_id}/efficiency-summary")
async def replay_batch_efficiency_summary(
    replay_batch_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    batch_exists = session.scalar(select(func.count()).select_from(HistoricalReplayBatchRecord).where(HistoricalReplayBatchRecord.id == replay_batch_id))
    if not batch_exists:
        raise HTTPException(status_code=404, detail="replay batch not found")
    return replay_candidate_efficiency_summary(session, replay_batch_id)


@router.get("/validation")
async def validate_plan_generation_tuning(
    config_version_id: int | None = Query(default=None),
    baseline_config_version_id: int | None = Query(default=None),
    ticker: str | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    lookback_days: int = Query(default=365, ge=30, le=3650),
    validation_days: int = Query(default=90, ge=7, le=365),
    step_days: int = Query(default=30, ge=1, le=365),
    min_validation_resolved: int = Query(default=8, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    service = PlanGenerationTuningService(session)
    seed_version = service.ensure_baseline_config_version()
    current_active_id = (
        service.settings.get_plan_generation_active_config_version_id() or seed_version.id or 0
    )
    current_active_version = service.repository.get_config_version(current_active_id)
    candidate_version = (
        service.repository.get_config_version(config_version_id)
        if config_version_id is not None
        else current_active_version
    )
    if baseline_config_version_id is not None:
        baseline_version = service.repository.get_config_version(baseline_config_version_id)
    elif config_version_id is None:
        baseline_version = seed_version
    elif candidate_version.id == current_active_version.id:
        baseline_version = seed_version
    else:
        baseline_version = current_active_version
    candidate_config = normalize_plan_generation_tuning_config(candidate_version.config)
    baseline_config = normalize_plan_generation_tuning_config(baseline_version.config)
    try:
        summary = (
            PlanGenerationWalkForwardService(service)
            .summarize(
                candidate_config=candidate_config,
                baseline_config=baseline_config,
                candidate_label=candidate_version.version_label,
                baseline_label=baseline_version.version_label,
                ticker=ticker,
                setup_family=setup_family,
                limit=limit,
                lookback_days=lookback_days,
                validation_days=validation_days,
                step_days=step_days,
                min_validation_resolved=min_validation_resolved,
            )
            .model_dump(mode="json")
        )
    except ValueError as exc:
        summary = PlanGenerationWalkForwardSummary(
            total_slices=0,
            lookback_days=lookback_days,
            validation_days=validation_days,
            step_days=step_days,
            min_validation_resolved=min_validation_resolved,
            candidate_label=candidate_version.version_label,
            baseline_label=baseline_version.version_label,
            qualified_slices=0,
            candidate_wins=0,
            baseline_wins=0,
            ties=0,
            average_win_rate_delta=None,
            average_expected_value_delta=None,
            promotion_recommended=False,
            promotion_rationale=str(exc),
            slices=[],
        ).model_dump(mode="json")
    return {
        "summary": summary,
        "candidate_version": candidate_version,
        "baseline_version": baseline_version,
        "candidate_config": candidate_config,
        "baseline_config": baseline_config,
    }
