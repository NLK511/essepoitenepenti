import logging
import os
import socket
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from trade_proposer_app.config import settings
from trade_proposer_app.db import SessionLocal
from trade_proposer_app.domain.models import WorkerHeartbeat
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.bars_refresh import BarsRefreshService
from trade_proposer_app.services.builders import (
    create_etoro_bar_shadow_comparison_service,
    create_historical_replay_service,
    create_industry_context_refresh_service,
    create_industry_context_service,
    create_macro_context_refresh_service,
    create_macro_context_service,
    create_proposal_service,
    create_watchlist_orchestration_service,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.recommendation_plan_evaluations import (
    RecommendationPlanEvaluationService,
)
from trade_proposer_app.services.runtime_supervision import RuntimeSupervisionService

logger = logging.getLogger(__name__)


@dataclass
class WorkerRuntimeState:
    active_run_id: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def set_active_run_id(self, run_id: int | None) -> None:
        with self.lock:
            self.active_run_id = run_id

    def get_active_run_id(self) -> int | None:
        with self.lock:
            return self.active_run_id


def _write_worker_heartbeat(worker_id: str, state: WorkerRuntimeState) -> None:
    session = SessionLocal()
    try:
        status = "running" if state.get_active_run_id() is not None else "idle"
        runs = RunRepository(session)
        runs.upsert_heartbeat(
            WorkerHeartbeat(
                worker_id=worker_id,
                hostname=socket.gethostname(),
                pid=os.getpid(),
                status=status,
                last_heartbeat_at=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc),
                active_run_id=state.get_active_run_id(),
            )
        )
        RuntimeSupervisionService(session).heartbeat(
            instance_id=worker_id,
            status="healthy" if status == "idle" else "running",
            metadata={"active_run_id": state.get_active_run_id()},
        )
    finally:
        session.close()


def _heartbeat_loop(worker_id: str, state: WorkerRuntimeState, stop_event: threading.Event) -> None:
    interval_seconds = max(2, int(settings.worker_heartbeat_interval_seconds))
    while not stop_event.wait(interval_seconds):
        try:
            _write_worker_heartbeat(worker_id, state)
        except Exception:
            logger.exception("worker heartbeat write failed")


def process_once(worker_id: str | None = None, state: WorkerRuntimeState | None = None) -> bool:
    session = SessionLocal()
    state = state or WorkerRuntimeState()
    try:
        proposal_service = create_proposal_service(session)
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
            watchlist_orchestration=create_watchlist_orchestration_service(
                session, proposal_service=proposal_service
            ),
            recommendation_plans=RecommendationPlanRepository(session),
            historical_replay=create_historical_replay_service(session),
            bars_refresh=BarsRefreshService(HistoricalMarketDataRepository(session)),
            etoro_bar_shadow_comparison=create_etoro_bar_shadow_comparison_service(session),
        )
        try:
            run = service.runs.claim_next_queued_run(worker_id=worker_id)
            if run is None:
                return False
            state.set_active_run_id(run.id)
            if worker_id:
                _write_worker_heartbeat(worker_id, state)
            try:
                service.execute_claimed_run(run, worker_id=worker_id)
            finally:
                state.set_active_run_id(None)
                if worker_id:
                    _write_worker_heartbeat(worker_id, state)
            return True
        except Exception as exc:
            logger.exception("worker run processing failed: worker_id=%s error=%s", worker_id, exc)
            traceback.print_exc()
            return True
    finally:
        session.close()


def _configure_logging(worker_id: str) -> None:
    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)

    log_file = os.getenv("WORKER_LOG_FILE")
    if not log_file:
        log_dir = os.getenv("WORKER_LOG_DIR", "/app/.prod-run/workers")
        log_file = os.path.join(log_dir, f"{worker_id}.log")
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        resolved_log_file = os.path.abspath(log_file)
        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == resolved_log_file:
                return
        file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception:  # noqa: BLE001
        root_logger.exception("failed to configure worker file logging: path=%s", log_file)


def main() -> None:
    worker_id = (
        os.getenv("WORKER_ID")
        or f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    _configure_logging(worker_id)
    state = WorkerRuntimeState()
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, args=(worker_id, state, stop_event), daemon=True
    )
    session = SessionLocal()
    try:
        RuntimeSupervisionService(session).register_process_start(
            role="worker",
            instance_id=worker_id,
            metadata={"worker_id": worker_id},
        )
    finally:
        session.close()
    logger.info("worker started: worker_id=%s", worker_id)
    _write_worker_heartbeat(worker_id, state)
    heartbeat_thread.start()
    try:
        while True:
            processed = process_once(worker_id=worker_id, state=state)
            if not processed:
                time.sleep(2)
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=5)
        session = SessionLocal()
        try:
            RuntimeSupervisionService(session).graceful_shutdown(instance_id=worker_id)
        finally:
            session.close()


if __name__ == "__main__":
    main()
