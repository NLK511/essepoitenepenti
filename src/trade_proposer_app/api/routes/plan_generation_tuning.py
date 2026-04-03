from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningError, PlanGenerationTuningService

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
    repository = PlanGenerationTuningService(session).settings
    try:
        settings_payload = repository.set_plan_generation_tuning_settings(
            auto_enabled=auto_enabled.strip().lower() in {"1", "true", "yes", "on"},
            auto_promote_enabled=auto_promote_enabled.strip().lower() in {"1", "true", "yes", "on"},
            min_actionable_resolved=int(min_actionable_resolved.strip() or "20"),
            min_validation_resolved=int(min_validation_resolved.strip() or "8"),
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
