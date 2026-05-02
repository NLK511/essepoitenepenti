from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.models import PlanGenerationWalkForwardSummary
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningError, PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config
from trade_proposer_app.services.plan_generation_walk_forward import PlanGenerationWalkForwardService
from trade_proposer_app.services.settings_mutations import SettingsMutationService

router = APIRouter(prefix="/plan-generation-tuning", tags=["plan-generation-tuning"])


@router.get("")
async def get_plan_generation_tuning_state(session: Session = Depends(get_db_session)) -> dict[str, object]:
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


@router.post("/run")
async def run_plan_generation_tuning(
    ticker: str | None = Query(default=None),
    setup_family: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    apply: bool = Query(default=False),
    session: Session = Depends(get_db_session),
):
    try:
        return PlanGenerationTuningService(session).run(
            mode="manual",
            apply=apply,
            ticker=ticker,
            setup_family=setup_family,
            limit=limit,
        )
    except PlanGenerationTuningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/configs")
async def list_plan_generation_tuning_configs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = PlanGenerationTuningService(session).repository
    configs = repository.list_config_versions(limit=limit, offset=offset)
    return {"items": configs, "total": repository.count_config_versions(), "limit": limit, "offset": offset}


@router.get("/configs/{config_version_id}")
async def get_plan_generation_tuning_config(config_version_id: int, session: Session = Depends(get_db_session)):
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
async def promote_plan_generation_tuning_config(config_version_id: int, session: Session = Depends(get_db_session)):
    try:
        version = PlanGenerationTuningService(session).promote_config_version(config_version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        raise HTTPException(status_code=400, detail=f"invalid plan generation tuning settings: {exc}") from exc
    return {"plan_generation_tuning": settings_payload}


@router.get("/parameters")
async def get_plan_generation_tuning_parameters(session: Session = Depends(get_db_session)) -> dict[str, object]:
    state = PlanGenerationTuningService(session).describe()
    return {
        "objective_name": state["objective_name"],
        "parameter_schema_version": state["parameter_schema_version"],
        "parameters": state["parameters"],
    }


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
    current_active_id = service.settings.get_plan_generation_active_config_version_id() or seed_version.id or 0
    current_active_version = service.repository.get_config_version(current_active_id)
    candidate_version = service.repository.get_config_version(config_version_id) if config_version_id is not None else current_active_version
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
        summary = PlanGenerationWalkForwardService(service).summarize(
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
        ).model_dump(mode="json")
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
