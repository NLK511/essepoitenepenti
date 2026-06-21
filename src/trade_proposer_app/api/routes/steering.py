from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.repositories.broker_steering_decisions import BrokerSteeringDecisionRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.broker_position_steering_workflow import BrokerSteeringService
from trade_proposer_app.services.default_jobs import DEFAULT_BROKER_STEERING_JOB_SPEC
from trade_proposer_app.services.job_execution import JobExecutionService

router = APIRouter(prefix="/steering", tags=["steering"])


@router.get("/decisions")
async def list_steering_decisions(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    repository = BrokerSteeringDecisionRepository(session)
    return {"items": repository.list_all(limit=limit), "limit": limit}


@router.post("/run-now")
async def run_steering_now(session: Session = Depends(get_db_session)) -> dict[str, object]:
    jobs = JobRepository(session)
    runs = RunRepository(session)
    service = JobExecutionService(jobs=jobs, runs=runs)
    job = jobs.get_or_create_system_job(DEFAULT_BROKER_STEERING_JOB_SPEC["name"], JobType.BROKER_STEERING)
    queued_run = service.enqueue_job(job.id or 0)
    claimed_run = runs.claim_queued_run(queued_run.id or 0)
    if claimed_run is None:
        latest_run = runs.get_run(queued_run.id or 0)
        return {"run": latest_run, "executed": False, "reason": f"run {latest_run.id} is already {latest_run.status}"}
    completed_run, _recommendations = service.execute_claimed_run(claimed_run)
    payload: dict[str, object] = {"run": completed_run, "executed": True}
    if completed_run.summary_json:
        payload["summary"] = _parse_json(completed_run.summary_json, {})
    if completed_run.artifact_json:
        payload["artifact"] = _parse_json(completed_run.artifact_json, {})
    return payload


@router.get("/config")
async def get_steering_config(session: Session = Depends(get_db_session)) -> dict[str, object]:
    return {"steering": BrokerSteeringService(session).settings}


def _parse_json(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
