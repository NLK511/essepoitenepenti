from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.tuning_workflow import TuningWorkflowError, TuningWorkflowService


router = APIRouter(prefix="/tuning-workflow", tags=["tuning-workflow"])


class TuningExperimentPayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    notes: str = ""
    hypothesis: str = ""
    universe: dict[str, Any] = Field(default_factory=dict)
    windows: dict[str, Any] = Field(default_factory=dict)
    discovery_settings: dict[str, Any] = Field(default_factory=dict)
    replay_settings: dict[str, Any] = Field(default_factory=dict)
    objective: str = "balanced_score"
    baseline: dict[str, Any] = Field(default_factory=dict)
    promotion_target: str = "paper_config"
    advanced_settings: dict[str, Any] = Field(default_factory=dict)


class TuningExperimentPatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    notes: str | None = None
    hypothesis: str | None = None
    universe: dict[str, Any] | None = None
    windows: dict[str, Any] | None = None
    discovery_settings: dict[str, Any] | None = None
    replay_settings: dict[str, Any] | None = None
    objective: str | None = None
    baseline: dict[str, Any] | None = None
    promotion_target: str | None = None
    advanced_settings: dict[str, Any] | None = None


def _service(session: Session) -> TuningWorkflowService:
    return TuningWorkflowService(session)


def _to_http_error(exc: TuningWorkflowError) -> HTTPException:
    message = str(exc)
    status = 404 if "not found" in message else 400
    return HTTPException(status_code=status, detail=message)


@router.get("/experiments")
async def list_tuning_experiments(
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    experiments = _service(session).list_experiments(include_archived=include_archived, limit=limit)
    return {"experiments": experiments, "count": len(experiments)}


@router.post("/experiments")
async def create_tuning_experiment(
    payload: TuningExperimentPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).create_experiment(payload.model_dump())
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.get("/experiments/{experiment_id}")
async def get_tuning_experiment(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    service = _service(session)
    try:
        experiment = service.experiment_detail(service.get_experiment(experiment_id))
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.patch("/experiments/{experiment_id}")
async def update_tuning_experiment(
    experiment_id: int,
    payload: TuningExperimentPatchPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    patch = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        experiment = _service(session).update_experiment(experiment_id, patch)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/archive")
async def archive_tuning_experiment(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).archive_experiment(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}
