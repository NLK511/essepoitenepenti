from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.services.builders import create_historical_replay_service
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


class TuningExperimentManualCandidatePayload(BaseModel):
    label: str = "manual candidate"
    config: dict[str, Any] = Field(default_factory=dict)


class TuningExperimentRejectCandidatePayload(BaseModel):
    reason: str = "operator rejected"


class TuningExperimentShortlistPayload(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)


class TuningExperimentBaselinePayload(BaseModel):
    replay_batch_id: int


class TuningExperimentReplayValidationPayload(BaseModel):
    batch_ids_by_candidate: dict[str, int] = Field(default_factory=dict)


class TuningExperimentStabilityPayload(BaseModel):
    candidate_id: str
    status: str = "warning"
    notes: str = ""


class TuningExperimentPromotionProposalPayload(BaseModel):
    candidate_id: str


class TuningExperimentPromotionExecutionPayload(BaseModel):
    reason: str = "workflow paper promotion"


class TuningExperimentPaperTrialExtensionPayload(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    reason: str = "extend paper trial"


class TuningExperimentRollbackPayload(BaseModel):
    reason: str = "workflow rollback"


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


def _workflow_service_with_replay(session: Session) -> TuningWorkflowService:
    return TuningWorkflowService(session, historical_replay_service=create_historical_replay_service(session, input_access_policy="cache_only"))


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


@router.delete("/experiments/{experiment_id}")
async def delete_tuning_experiment(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        return _service(session).delete_experiment(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc


@router.post("/experiments/{experiment_id}/autonomous-run")
async def run_tuning_experiment_autonomously(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        return _workflow_service_with_replay(session).run_autonomous_until_wait(experiment_id)
    except (TuningWorkflowError, ValueError) as exc:
        raise _to_http_error(TuningWorkflowError(str(exc))) from exc


@router.post("/experiments/{experiment_id}/readiness-audit")
async def run_tuning_experiment_readiness_audit(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).run_readiness_audit(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/candidate-pool/generate")
async def generate_tuning_experiment_candidate_pool(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).generate_candidate_pool(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/discovery/queue-large")
async def queue_tuning_experiment_large_discovery(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).queue_large_discovery_search(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/discovery/import")
async def import_tuning_experiment_discovery_candidates(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).import_discovery_job_candidates(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/candidate-pool/manual")
async def add_tuning_experiment_manual_candidate(
    experiment_id: int,
    payload: TuningExperimentManualCandidatePayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).add_manual_candidate(experiment_id, label=payload.label, config=payload.config)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/candidates/{candidate_id}/reject")
async def reject_tuning_experiment_candidate(
    experiment_id: int,
    candidate_id: str,
    payload: TuningExperimentRejectCandidatePayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).reject_candidate(experiment_id, candidate_id, reason=payload.reason)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/shortlist")
async def update_tuning_experiment_shortlist(
    experiment_id: int,
    payload: TuningExperimentShortlistPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).update_shortlist(experiment_id, payload.candidate_ids)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/baseline-replay/create")
async def create_tuning_experiment_baseline_replay(
    experiment_id: int,
    enqueue: bool = True,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _workflow_service_with_replay(session).create_baseline_replay_batch(experiment_id, enqueue=enqueue)
    except (TuningWorkflowError, ValueError) as exc:
        raise _to_http_error(TuningWorkflowError(str(exc))) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/holdout-replay/create")
async def create_tuning_experiment_holdout_replays(
    experiment_id: int,
    candidate_id: str,
    enqueue: bool = True,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _workflow_service_with_replay(session).create_holdout_replay_batches(experiment_id, candidate_id, enqueue=enqueue)
    except (TuningWorkflowError, ValueError) as exc:
        raise _to_http_error(TuningWorkflowError(str(exc))) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/candidate-replay/create")
async def create_tuning_experiment_candidate_replays(
    experiment_id: int,
    enqueue: bool = True,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _workflow_service_with_replay(session).create_candidate_replay_batches(experiment_id, enqueue=enqueue)
    except (TuningWorkflowError, ValueError) as exc:
        raise _to_http_error(TuningWorkflowError(str(exc))) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/baseline-replay/bind")
async def bind_tuning_experiment_baseline_replay(
    experiment_id: int,
    payload: TuningExperimentBaselinePayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).bind_baseline_replay_batch(experiment_id, payload.replay_batch_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/replay-summaries/refresh")
async def refresh_tuning_experiment_replay_summaries(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).refresh_replay_summaries(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/candidate-replay/stop-after-current-slice")
async def stop_tuning_experiment_candidate_replay_after_current_slice(
    experiment_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).stop_candidate_replay_after_current_slice(experiment_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/candidate-replay/record")
async def record_tuning_experiment_candidate_replay(
    experiment_id: int,
    payload: TuningExperimentReplayValidationPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).record_candidate_replay_validation(experiment_id, payload.batch_ids_by_candidate)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/stability-validation/record")
async def record_tuning_experiment_stability_validation(
    experiment_id: int,
    payload: TuningExperimentStabilityPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).record_stability_validation(experiment_id, payload.candidate_id, status=payload.status, notes=payload.notes)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/promotion-proposal")
async def create_tuning_experiment_promotion_proposal(
    experiment_id: int,
    payload: TuningExperimentPromotionProposalPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).create_promotion_proposal(experiment_id, payload.candidate_id)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/promotion-execution/paper")
async def execute_tuning_experiment_paper_promotion(
    experiment_id: int,
    payload: TuningExperimentPromotionExecutionPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).execute_paper_promotion(experiment_id, reason=payload.reason)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/paper-trial/extend")
async def extend_tuning_experiment_paper_trial(
    experiment_id: int,
    payload: TuningExperimentPaperTrialExtensionPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).extend_paper_trial(experiment_id, days=payload.days, reason=payload.reason)
    except TuningWorkflowError as exc:
        raise _to_http_error(exc) from exc
    return {"experiment": experiment}


@router.post("/experiments/{experiment_id}/rollback")
async def rollback_tuning_experiment_paper_promotion(
    experiment_id: int,
    payload: TuningExperimentRollbackPayload,
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        experiment = _service(session).rollback_paper_promotion(experiment_id, reason=payload.reason)
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
