import hashlib
import json
import logging
import os
import socket
import traceback
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import select

from scripts.large_plan_generation_parameter_search import run_large_parameter_search
from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import JobType, RunStatus, StrategyHorizon
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.domain.models import (
    EvaluationRunResult,
    Recommendation,
    Run,
    Watchlist,
    WorkerHeartbeat,
)
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.observability_events import ObservabilityEventRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.bars_refresh import BarsRefreshService
from trade_proposer_app.services.broker_position_steering_workflow import BrokerSteeringService
from trade_proposer_app.services.actionability_floor_calibration import ActionabilityFloorCalibrationService
from trade_proposer_app.services.confidence_calibration_snapshots import (
    ConfidenceCalibrationSnapshotService,
)
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.fundamental_analysis_refresh import (
    FundamentalAnalysisRefreshService,
)
from trade_proposer_app.services.gating_severity_alerts import GatingSeverityAlertService
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.industry_context_refresh import IndustryContextRefreshService
from trade_proposer_app.services.macro_context_refresh import MacroContextRefreshService
from trade_proposer_app.services.order_execution import OrderExecutionService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.recommendation_plan_calibration import (
    RecommendationPlanCalibrationService,
)

logger = logging.getLogger(__name__)


class RunExecutionFailed(Exception):
    def __init__(self, cause: Exception, timing: dict[str, object]) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.timing = timing


class JobExecutionService:
    def __init__(
        self,
        jobs: JobRepository,
        runs: RunRepository,
        evaluations: EvaluationExecutionService | None = None,
        plan_generation_tuning: PlanGenerationTuningService | None = None,
        performance_assessment: PerformanceAssessmentService | None = None,
        macro_context_refresh: MacroContextRefreshService | None = None,
        industry_context_refresh: IndustryContextRefreshService | None = None,
        macro_context=None,
        industry_context=None,
        watchlist_orchestration=None,
        recommendation_plans=None,
        order_execution: OrderExecutionService | None = None,
        historical_replay: HistoricalReplayService | None = None,
        bars_refresh: BarsRefreshService | None = None,
        fundamental_analysis_refresh: FundamentalAnalysisRefreshService | None = None,
    ) -> None:
        self.jobs = jobs
        self.runs = runs
        self.evaluations = evaluations
        self.plan_generation_tuning = plan_generation_tuning
        self.performance_assessment = performance_assessment
        self.macro_context_refresh = macro_context_refresh
        self.industry_context_refresh = industry_context_refresh
        self.macro_context = macro_context
        self.industry_context = industry_context
        self.watchlist_orchestration = watchlist_orchestration
        self.recommendation_plans = recommendation_plans
        self.order_execution = order_execution
        self.historical_replay = historical_replay
        self.bars_refresh = bars_refresh
        self.fundamental_analysis_refresh = fundamental_analysis_refresh
        self.observability = (
            ObservabilityEventRepository(self.runs.session)
            if getattr(self.runs, "session", None) is not None
            else None
        )
        if self.order_execution is None and getattr(self.runs, "session", None) is not None:
            from trade_proposer_app.services.builders import create_order_execution_service

            self.order_execution = create_order_execution_service(self.runs.session)

    def enqueue_job(self, job_id: int, scheduled_for: datetime | None = None) -> Run:
        self.runs.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
        job = self.jobs.get(job_id)
        if scheduled_for is not None:
            existing_scheduled_run = self.runs.get_run_for_job_and_scheduled_for(
                job.id or job_id, scheduled_for
            )
            if existing_scheduled_run is not None:
                return existing_scheduled_run
        if job.job_type == JobType.PLAN_GENERATION_TUNING:
            active_tuning_run = self.runs.get_active_run_for_job_type(
                JobType.PLAN_GENERATION_TUNING
            )
            if active_tuning_run is not None:
                return active_tuning_run
        active_run = self.runs.get_active_run_for_job(job.id or job_id)
        if active_run is not None:
            return active_run
        queued_run = self.runs.enqueue(
            job.id or job_id, scheduled_for=scheduled_for, job_type=job.job_type
        )
        self.jobs.mark_enqueued(job.id or job_id)
        return queued_run

    def execute_run(
        self, run_id: int, worker_id: str | None = None
    ) -> tuple[list[Recommendation], dict[str, object]]:
        run = self.runs.get_run(run_id)
        logger.info(
            "job execution dispatch started: run_id=%s job_id=%s job_type=%s worker_id=%s correlation_id=%s",
            run.id,
            run.job_id,
            run.job_type.value,
            worker_id,
            run.correlation_id,
        )
        logger.debug(
            "job execution dispatch payload: run_id=%s scheduled_for=%s started_at=%s artifact=%s",
            run.id,
            self._normalize_datetime(run.scheduled_for),
            self._normalize_datetime(run.started_at),
            self._get_run_artifact(run),
        )
        self._record_observability_event(
            run,
            event_type="run.dispatch_started",
            message="Run dispatch started",
            payload={"worker_id": worker_id, "job_type": run.job_type.value},
        )
        if worker_id:
            self.runs.upsert_heartbeat(
                WorkerHeartbeat(
                    worker_id=worker_id,
                    hostname=socket.gethostname(),
                    pid=os.getpid(),
                    status="running",
                    last_heartbeat_at=datetime.now(timezone.utc),
                    started_at=datetime.now(timezone.utc),  # simplified
                    active_run_id=run_id,
                )
            )
        if run.job_type == JobType.PROPOSAL_GENERATION:
            return self._execute_proposal_run(run)
        if run.job_type == JobType.RECOMMENDATION_EVALUATION:
            return self._execute_evaluation_run(run)
        if run.job_type == JobType.PLAN_GENERATION_TUNING:
            return self._execute_plan_generation_tuning_run(run)
        if run.job_type == JobType.PERFORMANCE_ASSESSMENT:
            return self._execute_performance_assessment_run(run)
        if run.job_type == JobType.MACRO_CONTEXT_REFRESH:
            return self._execute_macro_context_refresh_run(run)
        if run.job_type == JobType.INDUSTRY_CONTEXT_REFRESH:
            return self._execute_industry_context_refresh_run(run)
        if run.job_type == JobType.HISTORICAL_REPLAY:
            return self._execute_historical_replay_run(run)
        if run.job_type == JobType.BARS_DATA_REFRESH:
            return self._execute_bars_data_refresh_run(run)
        if run.job_type == JobType.BROKER_STEERING:
            return self._execute_broker_steering_run(run)
        if run.job_type == JobType.FUNDAMENTAL_ANALYSIS_REFRESH:
            return self._execute_fundamental_analysis_refresh_run(run)
        if run.job_type == JobType.GATING_SEVERITY_CHECK:
            return self._execute_gating_severity_check_run(run)
        if run.job_type == JobType.RECOMMENDATION_CALIBRATION_REFRESH:
            return self._execute_recommendation_calibration_refresh_run(run)
        raise RuntimeError(f"unsupported job_type execution: {run.job_type.value}")

    def _execute_proposal_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        logger.info(
            "job execution proposal started: run_id=%s job_id=%s worker=%s correlation_id=%s",
            run.id,
            run.job_id,
            socket.gethostname(),
            run.correlation_id,
        )
        logger.debug(
            "job execution proposal run payload: run_id=%s scheduled_for=%s started_at=%s artifact=%s",
            run.id,
            self._normalize_datetime(run.scheduled_for),
            self._normalize_datetime(run.started_at),
            self._get_run_artifact(run),
        )
        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "resolve_tickers_seconds": 0.0,
            "recommendation_generation_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
            "ticker_generation": [],
        }

        resolve_started = perf_counter()
        job = self.jobs.get(run.job_id)
        tickers = self.jobs.resolve_tickers(run.job_id)
        watchlist = self._resolve_execution_watchlist(job, tickers)
        logger.info(
            "job execution proposal inputs resolved: run_id=%s job_id=%s ticker_count=%s source_kind=%s watchlist_id=%s",
            run.id,
            run.job_id,
            len(tickers),
            getattr(watchlist, "source_kind", None),
            getattr(watchlist, "id", None),
        )
        logger.debug(
            "job execution proposal watchlist payload: run_id=%s watchlist=%s",
            run.id,
            watchlist,
        )
        timing["resolve_tickers_seconds"] = round(perf_counter() - resolve_started, 6)

        warnings_found = False
        generation_started = perf_counter()

        try:
            ticker_generation = self._get_ticker_generation_list(timing)
            if self.watchlist_orchestration is None:
                raise RuntimeError(
                    "proposal_generation runs require the redesign watchlist orchestration service"
                )

            # Use scheduled_for as the 'as_of' time if provided (for replays/simulations)
            as_of = self._normalize_datetime(run.scheduled_for)

            orchestration = self._execute_watchlist_orchestration(
                run, watchlist, tickers, as_of=as_of
            )
            ticker_generation.extend(orchestration.get("ticker_generation", []))
            warnings_found = bool(orchestration.get("warnings_found"))
            summary = orchestration.get("summary")
            artifact = orchestration.get("artifact")
            self._persist_orchestration_payloads(
                run, watchlist, job, summary=summary, artifact=artifact
            )
            timing["recommendation_generation_seconds"] = round(
                perf_counter() - generation_started, 6
            )

            order_execution_started = perf_counter()
            order_execution_summary = self._execute_proposal_order_submission(
                run, summary=summary, artifact=artifact
            )
            if order_execution_summary is not None:
                warnings_found = warnings_found or bool(
                    order_execution_summary.get("warnings_found")
                )
            timing["order_execution_seconds"] = round(perf_counter() - order_execution_started, 6)
            if isinstance(summary, dict):
                source_kind = str(summary.get("source_kind") or "").strip().lower()
                ticker_count = int(summary.get("ticker_count", 0) or 0)
                if source_kind == "manual_tickers" and ticker_count <= 1:
                    warnings_found = True
            if not warnings_found and self.recommendation_plans is not None:
                persisted_plans = self.recommendation_plans.list_plans(
                    run_id=run.id or 0, limit=1000
                )
                warnings_found = any(bool(plan.warnings) for plan in persisted_plans)
        except Exception as exc:
            timing["recommendation_generation_seconds"] = round(
                perf_counter() - generation_started, 6
            )
            partial_ticker_generation = getattr(exc, "ticker_generation", None)
            if isinstance(partial_ticker_generation, list):
                self._get_ticker_generation_list(timing).extend(partial_ticker_generation)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            logger.exception(
                "job execution proposal failed: run_id=%s job_id=%s elapsed_seconds=%s",
                run.id,
                run.job_id,
                timing["recommendation_generation_seconds"],
            )
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        stored: list[Recommendation] = []
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        final_status = (
            RunStatus.COMPLETED_WITH_WARNINGS.value if warnings_found else RunStatus.COMPLETED.value
        )
        self._finalize_success(run.id or 0, final_status, timing, execution_started)
        logger.info(
            "job execution proposal finished: run_id=%s job_id=%s final_status=%s warnings_found=%s total_execution_seconds=%s",
            run.id,
            run.job_id,
            final_status,
            warnings_found,
            timing["total_execution_seconds"],
        )
        logger.debug(
            "job execution proposal timing: run_id=%s timing=%s",
            run.id,
            timing,
        )
        return stored, timing

    def _execute_watchlist_orchestration(
        self, run: Run, watchlist: object, tickers: list[str], *, as_of: datetime | None
    ) -> dict[str, object]:
        if self.watchlist_orchestration is None:
            raise RuntimeError(
                "proposal_generation runs require the redesign watchlist orchestration service"
            )
        orchestration = self.watchlist_orchestration.execute(
            watchlist,
            tickers,
            job_id=run.job_id,
            run_id=run.id,
            as_of=as_of,
        )
        logger.info(
            "job execution proposal orchestration finished: run_id=%s job_id=%s warnings_found=%s",
            run.id,
            run.job_id,
            bool(orchestration.get("warnings_found")),
        )
        logger.debug(
            "job execution proposal orchestration payload: run_id=%s keys=%s summary_keys=%s artifact_keys=%s",
            run.id,
            sorted(orchestration.keys()),
            sorted(orchestration.get("summary", {}).keys())
            if isinstance(orchestration.get("summary"), dict)
            else None,
            sorted(orchestration.get("artifact", {}).keys())
            if isinstance(orchestration.get("artifact"), dict)
            else None,
        )
        return orchestration

    def _persist_orchestration_payloads(
        self, run: Run, watchlist: object, job: object, *, summary: object, artifact: object
    ) -> None:
        if isinstance(summary, dict):
            self._annotate_orchestration_payload(summary, watchlist, job)
            self.runs.set_summary(run.id or 0, summary)
        if isinstance(artifact, dict):
            self._annotate_orchestration_payload(artifact, watchlist, job)
            self.runs.set_artifact(run.id or 0, artifact)

    def _execute_proposal_order_submission(
        self, run: Run, *, summary: object, artifact: object
    ) -> dict[str, object] | None:
        if self.order_execution is None or self.recommendation_plans is None:
            return None
        actionable_plans = self.recommendation_plans.list_plans(run_id=run.id or 0, limit=1000)
        actionable_plans = [plan for plan in actionable_plans if plan.action in {"long", "short"}]
        order_execution_result = self.order_execution.execute_plans(
            actionable_plans, run_id=run.id, job_id=run.job_id
        )
        order_execution_summary = order_execution_result.summary
        if isinstance(summary, dict):
            summary["order_execution"] = order_execution_summary
            self.runs.set_summary(run.id or 0, summary)
        if isinstance(artifact, dict):
            artifact["order_execution"] = order_execution_summary
            self.runs.set_artifact(run.id or 0, artifact)
        return order_execution_summary

    def _execute_evaluation_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.evaluations is None:
            raise RuntimeError("recommendation evaluation execution service is not configured")

        logger.info(
            "job execution evaluation started: run_id=%s job_id=%s job_type=%s",
            run.id,
            run.job_id,
            run.job_type.value,
        )
        logger.debug(
            "job execution evaluation run payload: run_id=%s scheduled_for=%s artifact=%s",
            run.id,
            self._normalize_datetime(run.scheduled_for),
            self._get_run_artifact(run),
        )

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "evaluation_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        evaluation_started = perf_counter()
        evaluation_as_of = (
            self._normalize_datetime(run.scheduled_for)
            or self._normalize_datetime(run.started_at)
            or datetime.now(timezone.utc)
        )
        logger.debug(
            "job execution evaluation as_of resolved: run_id=%s scheduled_for=%s started_at=%s as_of=%s",
            run.id,
            self._normalize_datetime(run.scheduled_for),
            self._normalize_datetime(run.started_at),
            evaluation_as_of,
        )
        try:
            result = self.evaluations.execute(run, as_of=evaluation_as_of)
            timing["evaluation_seconds"] = round(perf_counter() - evaluation_started, 6)
        except Exception as exc:
            timing["evaluation_seconds"] = round(perf_counter() - evaluation_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            logger.exception(
                "job execution evaluation failed: run_id=%s job_id=%s elapsed_seconds=%s",
                run.id,
                run.job_id,
                timing["evaluation_seconds"],
            )
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        summary = self._evaluation_result_to_summary(result)
        artifact = self._get_run_artifact(run)
        if artifact:
            summary["scope"] = artifact.get("scope")
            summary["trigger"] = artifact.get("trigger")
        timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
        debug_bundle = self._build_evaluation_debug_bundle(run, result, timing, summary, artifact)
        summary["debug_bundle"] = debug_bundle
        artifact["debug_bundle"] = debug_bundle
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        logger.info(
            "job execution evaluation finished: run_id=%s job_id=%s evaluation_seconds=%s persistence_seconds=%s total_execution_seconds=%s debug_bundle_chars=%s",
            run.id,
            run.job_id,
            timing["evaluation_seconds"],
            timing["persistence_seconds"],
            timing["total_execution_seconds"],
            len(debug_bundle),
        )
        return [], timing

    def _execute_plan_generation_tuning_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.plan_generation_tuning is None:
            raise RuntimeError("plan generation tuning execution service is not configured")
        conflicting_run = self.runs.get_active_run_for_job_type(
            JobType.PLAN_GENERATION_TUNING, exclude_run_id=run.id or 0
        )
        if conflicting_run is not None:
            raise RuntimeError(f"plan generation tuning already active in run {conflicting_run.id}")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "plan_generation_tuning_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        tuning_started = perf_counter()
        request = self._plan_generation_tuning_request(run)
        plan_generation_tuning_limit = self._plan_generation_tuning_int(request.get("limit"), None)
        if str(request.get("search_kind") or "").strip().lower() == "large":
            return self._execute_large_plan_generation_tuning_search(run, request)
        if str(request.get("mode") or "").strip().lower() == "actionability_floor_calibration":
            return self._execute_actionability_floor_calibration_run(run, request)
        logger.info(
            "job execution plan generation tuning started: run_id=%s job_id=%s worker=%s mode=%s apply=%s limit=%s ticker=%s setup_family=%s",
            run.id,
            run.job_id,
            socket.gethostname(),
            request.get("mode") or "scheduled",
            bool(request.get("apply", False)),
            plan_generation_tuning_limit,
            self._plan_generation_tuning_string(request.get("ticker")),
            self._plan_generation_tuning_string(request.get("setup_family")),
        )
        try:
            requested_mode = str(request.get("mode") or "point_in_time_replay")
            tuning_run = self.plan_generation_tuning.run(
                mode=requested_mode,
                apply=bool(request.get("apply", False)),
                ticker=self._plan_generation_tuning_string(request.get("ticker")),
                setup_family=self._plan_generation_tuning_string(request.get("setup_family")),
                limit=plan_generation_tuning_limit,
                execute_replay_candidates=bool(request.get("execute_replay_candidates", False)),
                replay_candidate_limit=self._plan_generation_tuning_int(request.get("replay_candidate_limit"), 3) or 3,
            )
            summary = tuning_run.summary
            summary = dict(summary)
            summary["plan_generation_tuning_request"] = request
            artifact = {
                "plan_generation_tuning_request": request,
                "plan_generation_tuning_run_id": tuning_run.id,
                "winner_candidate_id": tuning_run.winning_candidate_id,
                "promoted_config_version_id": tuning_run.promoted_config_version_id,
            }
            timing["plan_generation_tuning_seconds"] = round(perf_counter() - tuning_started, 6)
        except Exception as exc:
            tuning_run_seconds = round(perf_counter() - tuning_started, 6)
            timing["plan_generation_tuning_seconds"] = tuning_run_seconds
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            logger.exception(
                "job execution plan generation tuning failed: run_id=%s job_id=%s worker=%s seconds=%.3f error=%s",
                run.id,
                run.job_id,
                socket.gethostname(),
                tuning_run_seconds,
                exc,
            )
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        logger.info(
            "job execution plan generation tuning finished: run_id=%s job_id=%s worker=%s tuning_run_id=%s winner_candidate_id=%s promoted_config_version_id=%s seconds=%.3f",
            run.id,
            run.job_id,
            socket.gethostname(),
            tuning_run.id,
            tuning_run.winning_candidate_id,
            tuning_run.promoted_config_version_id,
            timing["plan_generation_tuning_seconds"],
        )
        return [], timing

    def _execute_actionability_floor_calibration_run(
        self, run: Run, request: dict[str, object]
    ) -> tuple[list[Recommendation], dict[str, object]]:
        execution_started = perf_counter()
        floors = request.get("floors")
        if isinstance(floors, list):
            floor_values = [float(value) for value in floors if isinstance(value, (int, float))]
        else:
            floor_values = list(ActionabilityFloorCalibrationService.DEFAULT_FLOORS)
        report = ActionabilityFloorCalibrationService(self.runs.session).run(
            replay_batch_id=self._plan_generation_tuning_int(request.get("replay_batch_id"), None),
            floors=floor_values,
            min_resolved_trades=self._plan_generation_tuning_int(request.get("min_resolved_trades"), 10) or 10,
        )
        summary = {
            "mode": "actionability_floor_calibration",
            "status": report.get("status"),
            "replay_batch": report.get("replay_batch"),
            "active_floor": report.get("active_floor"),
            "best_floor": report.get("best_floor"),
            "recommendation": report.get("recommendation"),
            "plan_count": report.get("plan_count", 0),
        }
        artifact = {
            "plan_generation_tuning_request": request,
            "actionability_floor_calibration": report,
        }
        timing = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "actionability_floor_calibration_seconds": round(perf_counter() - execution_started, 6),
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)
        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_large_plan_generation_tuning_search(
        self, run: Run, request: dict[str, object]
    ) -> tuple[list[Recommendation], dict[str, object]]:
        from pathlib import Path

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "large_plan_generation_tuning_search_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        search_started = perf_counter()
        artifact_path = str(request.get("artifact_path") or "").strip() or None
        cache_path = str(request.get("cache_path") or "").strip() or None
        summary = run_large_parameter_search(
            self.runs.session,
            coarse_candidates_count=self._plan_generation_tuning_int(
                request.get("coarse_candidates"), 200_000
            )
            or 200_000,
            fine_candidates_count=self._plan_generation_tuning_int(
                request.get("fine_candidates"), 50_000
            )
            or 50_000,
            top_k=self._plan_generation_tuning_int(request.get("top_k"), 100) or 100,
            fine_seeds=self._plan_generation_tuning_int(request.get("fine_seeds"), 20) or 20,
            seed=self._plan_generation_tuning_int(request.get("seed"), 20260614) or 20260614,
            limit=self._plan_generation_tuning_int(request.get("limit"), None),
            min_validation_actionable=self._plan_generation_tuning_int(
                request.get("min_validation_actionable"), 50
            )
            or 50,
            batch_log_interval=self._plan_generation_tuning_int(
                request.get("batch_log_interval"), 1000
            )
            or 1000,
            artifact_path=Path(artifact_path) if artifact_path else None,
            cache_path=Path(cache_path) if cache_path else None,
        )
        timing["large_plan_generation_tuning_search_seconds"] = round(
            perf_counter() - search_started, 6
        )
        persistence_started = perf_counter()
        top_candidates = summary.get("top_candidates")
        best = top_candidates[0] if isinstance(top_candidates, list) and top_candidates else None
        run_summary = {
            "mode": "large_tuning_search",
            "search_kind": "large",
            "requested": summary.get("requested", {}),
            "evaluated": summary.get("evaluated", {}),
            "eligible_record_count": summary.get("eligible_record_count"),
            "validation_record_count": summary.get("validation_record_count"),
            "best_candidate": best,
            "artifact_path": summary.get("artifact_path"),
        }
        self.runs.set_summary(run.id or 0, run_summary)
        self.runs.set_artifact(
            run.id or 0,
            {
                "plan_generation_tuning_request": request,
                "large_plan_generation_tuning_search": summary,
            },
        )
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)
        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_performance_assessment_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.performance_assessment is None:
            raise RuntimeError("performance assessment execution service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "performance_assessment_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        assessment_started = perf_counter()
        try:
            result = self.performance_assessment.run()
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
            warnings_found = bool(result.get("warnings_found"))
            timing["performance_assessment_seconds"] = round(perf_counter() - assessment_started, 6)
        except Exception as exc:
            timing["performance_assessment_seconds"] = round(perf_counter() - assessment_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        final_status = (
            RunStatus.COMPLETED_WITH_WARNINGS.value if warnings_found else RunStatus.COMPLETED.value
        )
        self._finalize_success(run.id or 0, final_status, timing, execution_started)
        return [], timing

    def _execute_macro_context_refresh_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.macro_context_refresh is None:
            raise RuntimeError("macro context refresh service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "macro_context_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        refresh_started = perf_counter()
        try:
            result = self.macro_context_refresh.refresh(job_id=run.job_id, run_id=run.id)
            timing["macro_context_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["macro_context_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        payload = result.get("payload") if isinstance(result, dict) else result
        context_snapshot = None
        summary = {
            "scope": "macro",
            "subject_key": getattr(payload, "subject_key", None),
            "subject_label": getattr(payload, "subject_label", None),
            "score": getattr(payload, "score", 0.0),
            "label": getattr(payload, "label", "NEUTRAL"),
            "computed_at": (
                payload.computed_at.isoformat()
                if payload and getattr(payload, "computed_at", None)
                else None
            ),
        }
        if payload is not None and self.macro_context is not None:
            context_snapshot = self.macro_context.create_from_refresh_payload(
                payload, job_id=run.job_id, run_id=run.id
            )
            summary["macro_context_snapshot_id"] = getattr(context_snapshot, "id", None)
        self.runs.set_summary(run.id or 0, summary)
        artifact = {
            "scope": "macro",
            "subject_key": getattr(payload, "subject_key", None),
            "subject_label": getattr(payload, "subject_label", None),
            "macro_context_snapshot_id": getattr(context_snapshot, "id", None),
        }
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_industry_context_refresh_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.industry_context_refresh is None:
            raise RuntimeError("industry context refresh service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "industry_context_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        refresh_started = perf_counter()
        try:
            result = self.industry_context_refresh.refresh_all(job_id=run.job_id, run_id=run.id)
            timing["industry_context_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["industry_context_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        if isinstance(result, dict):
            payloads = list(result.get("payloads") or [])
            refresh_summary = (
                result.get("summary") if isinstance(result.get("summary"), dict) else {}
            )
        else:
            payloads = list(result or [])
            refresh_summary = {}
        summary = {
            "scope": "industry",
            "snapshot_count": len(payloads),
            "industries": [
                {
                    "subject_key": getattr(p, "subject_key", None),
                    "subject_label": getattr(p, "subject_label", None),
                    "score": getattr(p, "score", 0.0),
                    "label": getattr(p, "label", "NEUTRAL"),
                }
                for p in payloads
            ],
        }
        summary.update({k: v for k, v in refresh_summary.items() if k not in summary})
        context_snapshots = []
        if self.industry_context is not None:
            for payload in payloads:
                context_snapshots.append(
                    self.industry_context.create_from_refresh_payload(
                        payload, job_id=run.job_id, run_id=run.id
                    )
                )
            summary["industry_context_snapshot_count"] = len(context_snapshots)
            summary["industry_context_snapshot_ids"] = [
                getattr(snapshot, "id", None) for snapshot in context_snapshots
            ]
        self.runs.set_summary(run.id or 0, summary)
        artifact = {
            "scope": "industry",
            "snapshot_count": len(payloads),
            "subject_keys": [getattr(payload, "subject_key", None) for payload in payloads],
            "industry_context_snapshot_ids": [
                getattr(snapshot, "id", None) for snapshot in context_snapshots
            ],
        }
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_historical_replay_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.historical_replay is None:
            raise RuntimeError("historical replay service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "replay_setup_seconds": 0.0,
            "replay_execution_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        artifact = self._get_run_artifact(run)
        replay_payload = (
            artifact.get("historical_replay")
            if isinstance(artifact.get("historical_replay"), dict)
            else {}
        )
        batch_id = replay_payload.get("batch_id")
        slice_id = replay_payload.get("slice_id")
        if not isinstance(batch_id, int) or not isinstance(slice_id, int):
            raise RuntimeError(
                "historical replay run is missing batch_id or slice_id artifact metadata"
            )

        setup_started = perf_counter()
        self.historical_replay.mark_slice_running(slice_id)
        timing["replay_setup_seconds"] = round(perf_counter() - setup_started, 6)

        execution_phase_started = perf_counter()
        try:
            input_summary, output_summary = self.historical_replay.build_slice_execution_payload(
                batch_id, slice_id
            )
            plan_generation_summary = self._execute_historical_replay_plan_generation(
                run,
                input_summary=input_summary,
            )
            if plan_generation_summary is not None:
                output_summary["plan_generation"] = plan_generation_summary
                replay_resolution_summary = self._resolve_historical_replay_generated_plans(
                    run,
                    input_summary=input_summary,
                    candidate_config_hash=plan_generation_summary.get("candidate_config_override_hash")
                    if isinstance(plan_generation_summary, dict)
                    else None,
                )
                output_summary["replay_resolution"] = replay_resolution_summary
                output_summary["pipeline_stage"] = "plans_resolved"
                output_summary["next_step"] = "build replay eligibility records from replay-generated plans and outcomes"
            timing["replay_execution_seconds"] = round(perf_counter() - execution_phase_started, 6)
        except Exception as exc:
            timing["replay_execution_seconds"] = round(perf_counter() - execution_phase_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            self.historical_replay.fail_slice(slice_id, error_message=str(exc), timing=timing)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        summary = {
            "replay_batch_id": batch_id,
            "replay_slice_id": slice_id,
            "as_of": input_summary.get("as_of"),
            "mode": input_summary.get("mode"),
            "cadence": input_summary.get("cadence"),
            "entry_timing": input_summary.get("entry_timing"),
            "price_provider": input_summary.get("price_provider"),
            "price_source_tier": input_summary.get("price_source_tier"),
            "status": "completed",
            "message": output_summary.get("message"),
            "coverage_ratio": output_summary.get("coverage_ratio"),
            "pipeline_stage": output_summary.get("pipeline_stage"),
            "plan_generation": output_summary.get("plan_generation"),
            "replay_resolution": output_summary.get("replay_resolution"),
        }
        replay_artifact = {
            **artifact,
            "historical_replay_result": {
                "input_summary": input_summary,
                "output_summary": output_summary,
            },
        }
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, replay_artifact)
        self.historical_replay.complete_slice(
            slice_id,
            input_summary=input_summary,
            output_summary=output_summary,
            timing=timing,
        )
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _resolve_historical_replay_generated_plans(
        self,
        run: Run,
        *,
        input_summary: dict[str, object],
        candidate_config_hash: object,
    ) -> dict[str, object]:
        if getattr(self.runs, "session", None) is None or run.id is None:
            return {"status": "skipped", "reason": "session_or_run_missing"}
        from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
        from trade_proposer_app.repositories.replay_eligibility import ReplayEligibilityRepository
        from trade_proposer_app.repositories.replay_plan_outcomes import ReplayPlanOutcomeRepository
        from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService

        plans = RecommendationPlanRepository(self.runs.session).list_plans(run_id=run.id, limit=None)
        if not plans:
            return {"status": "skipped", "reason": "no_replay_generated_plans", "plan_count": 0}
        replay_batch_id = input_summary.get("replay_batch_id")
        replay_slice_id = input_summary.get("replay_slice_id")
        if not isinstance(replay_batch_id, int) or not isinstance(replay_slice_id, int):
            return {"status": "skipped", "reason": "missing_replay_ids", "plan_count": len(plans)}
        replay_as_of = self._parse_datetime(input_summary.get("as_of"))
        coverage = input_summary.get("replay_coverage_report")
        resolution_days = int(coverage.get("resolution_days", 5)) if isinstance(coverage, dict) else 5
        resolution_as_of = (replay_as_of + timedelta(days=resolution_days)) if replay_as_of else None
        evaluator = RecommendationPlanEvaluationService(self.runs.session)
        price_history_cache, price_errors = evaluator._prepare_price_histories(plans, as_of=resolution_as_of)  # noqa: SLF001
        replay_outcomes = ReplayPlanOutcomeRepository(self.runs.session)
        replay_eligibility = ReplayEligibilityRepository(self.runs.session)
        coverage_by_ticker = self._replay_coverage_by_ticker(coverage)
        stored = []
        eligibility_records = []
        source_counts: dict[str, int] = {}
        outcome_counts: dict[str, int] = {}
        for plan in plans:
            ticker = (plan.ticker or "").strip().upper()
            daily_data = price_history_cache.get((ticker, False))
            intraday_data = price_history_cache.get((ticker, True))
            outcome, source_mode = evaluator._resolve_plan_outcome(  # noqa: SLF001
                plan,
                daily_data,
                intraday_data,
                run_id=run.id,
                as_of=resolution_as_of,
            )
            stored_outcome = replay_outcomes.upsert_outcome(
                replay_batch_id=replay_batch_id,
                replay_slice_id=replay_slice_id,
                run_id=run.id,
                recommendation_plan_id=plan.id or 0,
                candidate_config_hash=str(candidate_config_hash or ""),
                resolution_source=source_mode,
                outcome=outcome,
            )
            stored.append(stored_outcome)
            candidate_hash = str(candidate_config_hash or "")
            signal_breakdown = self._model_or_dict_to_dict(plan.signal_breakdown)
            replay_provenance = signal_breakdown.get("replay_provenance") if isinstance(signal_breakdown, dict) else None
            if replay_provenance is None and plan.id is not None:
                raw_plan = self.runs.session.get(RecommendationPlanRecord, plan.id)
                raw_signal_breakdown = self._loads_json_object(raw_plan.signal_breakdown_json if raw_plan else None)
                replay_provenance = raw_signal_breakdown.get("replay_provenance")
            eligibility = self._classify_replay_eligibility(
                ticker=ticker,
                coverage=coverage_by_ticker.get(ticker),
                resolution_source=source_mode,
                outcome=stored_outcome,
                candidate_config_hash=candidate_hash,
                replay_provenance=replay_provenance if isinstance(replay_provenance, dict) else {},
            )
            eligibility_records.append(
                replay_eligibility.upsert_record(
                    replay_batch_id=replay_batch_id,
                    replay_slice_id=replay_slice_id,
                    replay_plan_outcome_id=stored_outcome.get("id") if isinstance(stored_outcome.get("id"), int) else None,
                    recommendation_plan_id=plan.id or 0,
                    run_id=run.id,
                    ticker=ticker,
                    candidate_config_hash=candidate_hash,
                    tier=eligibility["tier"],
                    eligible_for_tuning=bool(eligibility["eligible_for_tuning"]),
                    resolution_source=source_mode,
                    outcome=outcome.outcome,
                    rejection_reasons=list(eligibility["rejection_reasons"]),
                    diagnostics=dict(eligibility["diagnostics"]),
                )
            )
            source_counts[source_mode] = source_counts.get(source_mode, 0) + 1
            outcome_counts[outcome.outcome] = outcome_counts.get(outcome.outcome, 0) + 1
        return {
            "status": "completed",
            "plan_count": len(plans),
            "stored_outcome_count": len(stored),
            "resolution_as_of": resolution_as_of.isoformat() if resolution_as_of else None,
            "source_counts": source_counts,
            "outcome_counts": outcome_counts,
            "price_errors": price_errors,
            "stored_outcome_ids": [item.get("id") for item in stored],
            "eligibility_record_count": len(eligibility_records),
            "eligibility_tier_counts": self._count_values(eligibility_records, "tier"),
            "eligible_for_tuning_count": sum(1 for item in eligibility_records if item.get("eligible_for_tuning")),
        }

    @staticmethod
    def _model_or_dict_to_dict(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {}
        legacy_dict = getattr(value, "dict", None)
        if callable(legacy_dict):
            dumped = legacy_dict()
            return dumped if isinstance(dumped, dict) else {}
        return {}

    @staticmethod
    def _replay_coverage_by_ticker(coverage: object) -> dict[str, dict[str, object]]:
        if not isinstance(coverage, dict):
            return {}
        tickers = coverage.get("tickers")
        if not isinstance(tickers, list):
            return {}
        result: dict[str, dict[str, object]] = {}
        for item in tickers:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip().upper()
            if ticker:
                result[ticker] = item
        return result

    @staticmethod
    def _classify_replay_eligibility(
        *,
        ticker: str,
        coverage: dict[str, object] | None,
        resolution_source: str,
        outcome: dict[str, object],
        candidate_config_hash: str,
        replay_provenance: dict[str, object],
    ) -> dict[str, object]:
        coverage_tier = str((coverage or {}).get("tier") or "ineligible")
        blockers = [str(item) for item in ((coverage or {}).get("blockers") or [])]
        warnings = [str(item) for item in ((coverage or {}).get("warnings") or [])]
        outcome_label = str(outcome.get("outcome") or "")
        status = str(outcome.get("status") or "")
        reasons = list(blockers)
        if not coverage:
            reasons.append("missing_coverage_report")
        mandatory_provenance_keys = ("as_of", "code_version", "settings_hash", "input_coverage_hash")
        missing_provenance = [key for key in mandatory_provenance_keys if not replay_provenance.get(key)]
        if missing_provenance:
            reasons.extend(f"missing_replay_provenance:{key}" for key in missing_provenance)
        if status != "resolved":
            reasons.append("unresolved_open_outcome")
        provenance_valid = not missing_provenance
        if resolution_source == "intraday" and coverage_tier == "tier_a" and status == "resolved" and not blockers and provenance_valid:
            tier = "tier_a"
            eligible = True
        elif coverage_tier in {"tier_a", "tier_b"} and resolution_source in {"daily_prefilter", "none"} and status == "resolved" and not blockers and provenance_valid:
            tier = "tier_b"
            eligible = True
            if resolution_source == "daily_prefilter":
                reasons.append("accepted_daily_prefilter_resolution")
            if resolution_source == "none":
                reasons.append("non_trade_replay_outcome")
        else:
            tier = "tier_c" if coverage_tier != "ineligible" else "ineligible"
            eligible = False
            if resolution_source != "intraday" and resolution_source not in {"daily_prefilter", "none"}:
                reasons.append(f"unaccepted_resolution_source:{resolution_source or 'missing'}")
        return {
            "tier": tier,
            "eligible_for_tuning": eligible,
            "rejection_reasons": sorted(set(reasons)),
            "diagnostics": {
                "ticker": ticker,
                "coverage_tier": coverage_tier,
                "coverage_blockers": blockers,
                "coverage_warnings": warnings,
                "resolution_source": resolution_source,
                "outcome": outcome_label,
                "status": status,
                "artifact_key": {
                    "as_of": replay_provenance.get("as_of"),
                    "ticker": ticker,
                    "candidate_config_hash": candidate_config_hash,
                    "input_coverage_hash": replay_provenance.get("input_coverage_hash"),
                },
                "artifact_versions": {
                    "code_version": replay_provenance.get("code_version"),
                    "settings_hash": replay_provenance.get("settings_hash"),
                    "input_coverage_hash": replay_provenance.get("input_coverage_hash"),
                },
            },
        }

    @staticmethod
    def _count_values(items: list[dict[str, object]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            value = str(item.get(key) or "")
            if value:
                counts[value] = counts.get(value, 0) + 1
        return counts

    def _execute_historical_replay_plan_generation(
        self,
        run: Run,
        *,
        input_summary: dict[str, object],
    ) -> dict[str, object] | None:
        if self.watchlist_orchestration is None:
            return None
        raw_tickers = input_summary.get("tickers")
        if not isinstance(raw_tickers, list):
            return None
        tickers = [str(item).strip().upper() for item in raw_tickers if str(item).strip()]
        if not tickers:
            return None
        as_of = self._parse_datetime(input_summary.get("as_of"))
        watchlist = Watchlist(
            id=None,
            name=f"Historical replay slice {input_summary.get('as_of') or ''}".strip(),
            tickers=tickers,
            description="Synthetic watchlist for point-in-time historical replay plan generation.",
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=True,
            optimize_evaluation_timing=False,
        )
        provenance = self._build_historical_replay_provenance(run, input_summary=input_summary)
        set_provenance = getattr(self.watchlist_orchestration, "set_replay_provenance", None)
        set_config_override = getattr(
            self.watchlist_orchestration,
            "set_plan_generation_tuning_override",
            None,
        )
        config_override = input_summary.get("plan_generation_tuning_config_override")
        if callable(set_provenance):
            set_provenance(provenance)
        if callable(set_config_override) and isinstance(config_override, dict):
            set_config_override(config_override)
        try:
            orchestration = self._execute_watchlist_orchestration(
                run,
                watchlist,
                tickers,
                as_of=as_of,
            )
        finally:
            if callable(set_config_override):
                set_config_override(None)
            if callable(set_provenance):
                set_provenance(None)
        self._ensure_replay_provenance_on_generated_plans(run, provenance)
        summary = orchestration.get("summary") if isinstance(orchestration, dict) else None
        artifact = orchestration.get("artifact") if isinstance(orchestration, dict) else None
        plan_count = self._safe_nested_int(summary, "plan_count")
        signal_count = self._safe_nested_int(summary, "signal_count")
        return {
            "status": "completed",
            "as_of": as_of.isoformat() if as_of else None,
            "ticker_count": len(tickers),
            "signal_count": signal_count,
            "plan_count": plan_count,
            "summary": summary if isinstance(summary, dict) else {},
            "artifact_keys": sorted(artifact.keys()) if isinstance(artifact, dict) else [],
            "candidate_config_override_applied": isinstance(config_override, dict),
            "candidate_config_override_hash": self._stable_hash(config_override) if isinstance(config_override, dict) else None,
            "replay_provenance": provenance,
        }

    def _ensure_replay_provenance_on_generated_plans(self, run: Run, provenance: dict[str, object]) -> None:
        if getattr(self.runs, "session", None) is None or run.id is None:
            return
        rows = self.runs.session.scalars(
            select(RecommendationPlanRecord).where(RecommendationPlanRecord.run_id == run.id)
        ).all()
        changed = False
        for row in rows:
            signal_breakdown = self._loads_json_object(row.signal_breakdown_json)
            evidence_summary = self._loads_json_object(row.evidence_summary_json)
            if not isinstance(signal_breakdown.get("replay_provenance"), dict):
                signal_breakdown["replay_provenance"] = dict(provenance)
                row.signal_breakdown_json = json.dumps(signal_breakdown, sort_keys=True, default=str)
                changed = True
            if not isinstance(evidence_summary.get("replay_provenance"), dict):
                evidence_summary["replay_provenance"] = dict(provenance)
                row.evidence_summary_json = json.dumps(evidence_summary, sort_keys=True, default=str)
                changed = True
        if changed:
            self.runs.session.commit()

    @staticmethod
    def _loads_json_object(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _build_historical_replay_provenance(
        self,
        run: Run,
        *,
        input_summary: dict[str, object],
    ) -> dict[str, object]:
        coverage = input_summary.get("replay_coverage_report")
        coverage_summary = self._compact_replay_coverage_summary(coverage if isinstance(coverage, dict) else {})
        payload = {
            "source": "historical_replay",
            "replay_batch_id": input_summary.get("replay_batch_id"),
            "replay_slice_id": input_summary.get("replay_slice_id"),
            "as_of": input_summary.get("as_of"),
            "run_id": run.id,
            "job_id": run.job_id,
            "code_version": os.environ.get("GIT_COMMIT") or os.environ.get("SOURCE_VERSION") or "unknown",
            "settings_hash": self._stable_hash({"weights_file_path": settings.weights_file_path}),
            "input_coverage_summary": coverage_summary,
            "input_coverage_hash": str(coverage.get("input_coverage_hash") or self._stable_hash(coverage)) if isinstance(coverage, dict) else self._stable_hash(coverage),
            "plan_generation_config_hash": self._stable_hash(input_summary.get("plan_generation_tuning_config_override") or {}),
            "warnings": self._collect_replay_input_warnings(coverage if isinstance(coverage, dict) else {}),
        }
        return payload

    @staticmethod
    def _compact_replay_coverage_summary(coverage: dict[str, object]) -> dict[str, object]:
        news = coverage.get("news_coverage") if isinstance(coverage.get("news_coverage"), dict) else {}
        context = coverage.get("context_coverage") if isinstance(coverage.get("context_coverage"), dict) else {}
        fundamentals = coverage.get("fundamental_coverage") if isinstance(coverage.get("fundamental_coverage"), dict) else {}
        return {
            "ticker_count": coverage.get("ticker_count"),
            "tier_counts": coverage.get("tier_counts"),
            "tier_a_ratio": coverage.get("tier_a_ratio"),
            "news_coverage_ratio": news.get("coverage_ratio") if isinstance(news, dict) else None,
            "context_industry_coverage_ratio": context.get("industry_coverage_ratio") if isinstance(context, dict) else None,
            "fundamental_coverage_ratio": fundamentals.get("coverage_ratio") if isinstance(fundamentals, dict) else None,
        }

    @staticmethod
    def _collect_replay_input_warnings(coverage: dict[str, object]) -> list[str]:
        warnings: list[str] = []
        ticker_rows = coverage.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if not isinstance(row, dict):
                    continue
                ticker = row.get("ticker")
                for warning in row.get("warnings") or []:
                    warnings.append(f"{ticker}: {warning}")
                for blocker in row.get("blockers") or []:
                    warnings.append(f"{ticker}: {blocker}")
        return warnings[:50]

    @staticmethod
    def _stable_hash(payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _safe_nested_int(payload: object, key: str) -> int | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get(key)
        if isinstance(value, int):
            return value
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _execute_broker_steering_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "broker_steering_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        steering_started = perf_counter()
        service = BrokerSteeringService(self.runs.session)
        summary = service.run_once(
            run_id=run.id, job_id=run.job_id, correlation_id=run.correlation_id
        )
        timing["broker_steering_seconds"] = round(perf_counter() - steering_started, 6)
        persistence_started = perf_counter()
        run_summary = {
            "candidate_count": summary.total_candidates,
            "decision_counts": summary.decisions,
            "execution_status": summary.execution_status,
        }
        self.runs.set_summary(run.id or 0, run_summary)
        self.runs.set_artifact(
            run.id or 0,
            {
                "broker_steering": run_summary,
            },
        )
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)
        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_fundamental_analysis_refresh_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.fundamental_analysis_refresh is None:
            if getattr(self.runs, "session", None) is None:
                raise RuntimeError("fundamental analysis refresh service is not configured")
            self.fundamental_analysis_refresh = FundamentalAnalysisRefreshService(self.runs.session)
        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "fundamental_analysis_refresh_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        refresh_started = perf_counter()
        summary = self.fundamental_analysis_refresh.refresh_due_monitored_tickers(
            run_id=run.id, job_id=run.job_id
        )
        timing["fundamental_analysis_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
        persistence_started = perf_counter()
        run_summary = {
            "mode": "fundamental_analysis_refresh",
            "monitored_count": summary.get("monitored_count", 0),
            "refreshed_count": summary.get("refreshed_count", 0),
            "skipped_fresh_count": summary.get("skipped_fresh_count", 0),
            "failed_count": summary.get("failed_count", 0),
        }
        self.runs.set_summary(run.id or 0, run_summary)
        self.runs.set_artifact(run.id or 0, {"fundamental_analysis_refresh": summary})
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)
        status = (
            RunStatus.COMPLETED_WITH_WARNINGS.value
            if int(summary.get("failed_count", 0) or 0)
            else RunStatus.COMPLETED.value
        )
        self._finalize_success(run.id or 0, status, timing, execution_started)
        return [], timing

    def _execute_recommendation_calibration_refresh_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "calibration_refresh_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        refresh_started = perf_counter()
        service = ConfidenceCalibrationSnapshotService(
            self.runs,
            RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(self.runs.session)),
        )
        snapshot = service.refresh()
        timing["calibration_refresh_seconds"] = round(perf_counter() - refresh_started, 6)

        persistence_started = perf_counter()
        execution_report = snapshot.get("reports", {}).get("execution_only", {}) if isinstance(snapshot.get("reports"), dict) else {}
        execution_summary = execution_report.get("summary", {}) if isinstance(execution_report, dict) else {}
        run_summary = {
            "mode": "recommendation_calibration_refresh",
            "live_mode": snapshot.get("live_mode", "execution_only"),
            "limit": snapshot.get("limit"),
            "sample_status": execution_summary.get("sample_status"),
            "included_outcomes": execution_summary.get("included_outcomes"),
            "success_rate_percent": execution_summary.get("success_rate_percent"),
            "warnings": snapshot.get("warnings", []),
        }
        self.runs.set_summary(run.id or 0, run_summary)
        self.runs.set_artifact(run.id or 0, {ConfidenceCalibrationSnapshotService.ARTIFACT_KEY: snapshot})
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)
        status = RunStatus.COMPLETED_WITH_WARNINGS.value if snapshot.get("warnings") else RunStatus.COMPLETED.value
        self._finalize_success(run.id or 0, status, timing, execution_started)
        return [], timing

    def _execute_gating_severity_check_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "gating_severity_check_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }
        check_started = perf_counter()
        summary = GatingSeverityAlertService(self.runs.session).evaluate(
            window_days=7,
            record_event=True,
        )
        timing["gating_severity_check_seconds"] = round(perf_counter() - check_started, 6)
        persistence_started = perf_counter()
        run_summary = {
            "mode": "gating_severity_check",
            "window_days": summary.get("window_days", 7),
            "severity": summary.get("severity", "info"),
            "reasons": summary.get("reasons", []),
            "metrics": summary.get("metrics", {}),
        }
        self.runs.set_summary(run.id or 0, run_summary)
        self.runs.set_artifact(run.id or 0, {"gating_severity_check": summary})
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)
        status = (
            RunStatus.COMPLETED_WITH_WARNINGS.value
            if summary.get("severity") in {"warning", "critical"}
            else RunStatus.COMPLETED.value
        )
        self._finalize_success(run.id or 0, status, timing, execution_started)
        return [], timing

    def _execute_bars_data_refresh_run(
        self, run: Run
    ) -> tuple[list[Recommendation], dict[str, object]]:
        if self.bars_refresh is None:
            raise RuntimeError("bars data refresh service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "bars_refresh_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        refresh_started = perf_counter()
        try:
            tickers = self.jobs.resolve_tickers(run.job_id)
            result = self.bars_refresh.refresh_bars(tickers)
            timing["bars_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["bars_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        warnings = result.get("warnings", [])
        summary = {
            "total_ingested": result.get("total_ingested"),
            "refreshed_at": result.get("refreshed_at"),
            "warning_count": len(warnings),
            "warnings": warnings,
        }
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, result)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        final_status = (
            RunStatus.COMPLETED_WITH_WARNINGS.value if warnings else RunStatus.COMPLETED.value
        )
        self._finalize_success(run.id or 0, final_status, timing, execution_started)
        return [], timing

    def process_next_queued_run(
        self, worker_id: str | None = None
    ) -> tuple[Run | None, list[Recommendation]]:
        self.runs.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
        run = self.runs.claim_next_queued_run(worker_id=worker_id)
        if run is None:
            return None, []
        return self.execute_claimed_run(run, worker_id=worker_id)

    def execute_claimed_run(
        self, run: Run, worker_id: str | None = None
    ) -> tuple[Run, list[Recommendation]]:
        try:
            recommendations, _timing = self.execute_run(run.id or 0, worker_id=worker_id)
            return self.runs.get_run(run.id or 0), recommendations
        except RunExecutionFailed as exc:
            finalize_started = perf_counter()
            exc.timing["finalize_seconds"] = 0.0
            exc.timing["total_execution_seconds"] = round(
                float(exc.timing.get("total_execution_seconds") or 0.0),
                6,
            )
            try:
                self.runs.session.rollback()
                current_run = self.runs.get_run(run.id or 0)
                self.runs.set_artifact(
                    run.id or 0,
                    self._build_failure_artifact(current_run, run, exc),
                )
                self.runs.update_status(
                    run.id or 0,
                    RunStatus.FAILED.value,
                    error_message=str(exc.cause),
                    timing=exc.timing,
                )
                exc.timing["finalize_seconds"] = round(perf_counter() - finalize_started, 6)
                exc.timing["total_execution_seconds"] = round(
                    float(exc.timing.get("total_execution_seconds") or 0.0)
                    + float(exc.timing["finalize_seconds"]),
                    6,
                )
                self.runs.set_timing(run.id or 0, exc.timing)
                self._record_observability_event(
                    current_run,
                    event_type="run.failed",
                    severity="error",
                    message=str(exc.cause),
                    payload={"timing": exc.timing, "cause_type": type(exc.cause).__name__},
                )
            except Exception as finalize_exc:
                self.runs.session.rollback()
                print(f"failed to finalize run {run.id}: {finalize_exc}")
                traceback.print_exc()
            raise exc.cause

    def _finalize_success(
        self,
        run_id: int,
        final_status: str,
        timing: dict[str, object],
        execution_started: float,
    ) -> None:
        finalize_started = perf_counter()
        timing["finalize_seconds"] = 0.0
        timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
        self.runs.update_status(run_id, final_status, timing=timing)
        timing["finalize_seconds"] = round(perf_counter() - finalize_started, 6)
        timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
        self.runs.set_timing(run_id, timing)
        run = self.runs.get_run(run_id)
        self._record_observability_event(
            run,
            event_type="run.finished",
            severity="warning"
            if final_status == RunStatus.COMPLETED_WITH_WARNINGS.value
            else "info",
            message=f"Run finished with status {final_status}",
            payload={"final_status": final_status, "timing": timing},
        )

    def _record_observability_event(
        self,
        run: Run,
        *,
        event_type: str,
        severity: str = "info",
        message: str = "",
        payload: dict[str, object] | None = None,
    ) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record(
                run_id=run.id,
                job_id=run.job_id,
                correlation_id=run.correlation_id,
                event_type=event_type,
                severity=severity,
                source="job_execution",
                message=message,
                payload=payload or {},
            )
        except Exception as exc:  # pragma: no cover - observability must not break trading work
            try:
                self.runs.session.rollback()
            except Exception:
                pass
            logger.warning(
                "failed to record observability event: run_id=%s event_type=%s error=%s",
                run.id,
                event_type,
                exc,
            )

    def enqueue_manual_evaluation(
        self,
        recommendation_plan_id: int | None = None,
        recommendation_plan_scope: bool = False,
    ) -> Run:
        job_name = "manual evaluation"
        if recommendation_plan_id is not None:
            job_name = "manual recommendation plan evaluation"
        job = self.jobs.get_or_create_system_job(job_name, JobType.RECOMMENDATION_EVALUATION)
        run = self.runs.enqueue(job.id or 0, job_type=JobType.RECOMMENDATION_EVALUATION)
        trigger_mode = "manual_global"
        trigger_source = "recommendation_plans_ui"
        if recommendation_plan_id is not None:
            trigger_mode = "manual_recommendation_plan"
        artifact: dict[str, object] = {
            "trigger": {
                "mode": trigger_mode,
                "source": trigger_source,
            }
        }
        if recommendation_plan_scope:
            artifact["scope"] = {
                "type": "all_recommendation_plans",
            }
        if recommendation_plan_id is not None:
            if self.recommendation_plans is None:
                raise RuntimeError("recommendation plan repository is not configured")
            plan = self.recommendation_plans.get_plan(recommendation_plan_id)
            artifact["scope"] = {
                "type": "recommendation_plan_ids",
                "recommendation_plan_ids": [recommendation_plan_id],
                "ticker": plan.ticker,
            }
        self.runs.set_artifact(run.id or 0, artifact)
        self.jobs.mark_enqueued(job.id or 0)
        return self.runs.get_run(run.id or 0)

    @staticmethod
    def _evaluation_result_to_summary(result: EvaluationRunResult) -> dict[str, object]:
        return {
            "evaluated_recommendation_plans": result.evaluated_recommendation_plans,
            "synced_recommendation_plan_outcomes": result.synced_recommendation_plan_outcomes,
            "pending_recommendation_plan_outcomes": result.pending_recommendation_plan_outcomes,
            "win_recommendation_plan_outcomes": result.win_recommendation_plan_outcomes,
            "loss_recommendation_plan_outcomes": result.loss_recommendation_plan_outcomes,
            "no_action_recommendation_plan_outcomes": result.no_action_recommendation_plan_outcomes,
            "watchlist_recommendation_plan_outcomes": result.watchlist_recommendation_plan_outcomes,
            "output": result.output,
        }

    @classmethod
    def _build_evaluation_debug_bundle(
        cls,
        run: Run,
        result: EvaluationRunResult,
        timing: dict[str, object],
        summary: dict[str, object],
        artifact: dict[str, object],
    ) -> str:
        scheduled_for = cls._normalize_datetime(run.scheduled_for)
        lines: list[str] = [
            f"run_id={run.id}",
            f"job_id={run.job_id}",
            f"job_type={run.job_type.value}",
            f"scheduled_for={scheduled_for.isoformat() if scheduled_for is not None else 'None'}",
            f"summary={json.dumps(summary, sort_keys=True, default=str)}",
            f"artifact={json.dumps(artifact, sort_keys=True, default=str)}",
            f"timing={json.dumps(timing, sort_keys=True, default=str)}",
            "decision_trace:",
        ]
        output = (result.output or "").strip()
        if output:
            lines.append(output)
        else:
            lines.append("<empty>")
        return "\n".join(lines)

    @staticmethod
    def _get_run_summary(run: Run) -> dict[str, object]:
        if not run.summary_json:
            return {}
        try:
            parsed = json.loads(run.summary_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _get_run_artifact(run: Run) -> dict[str, object]:
        if not run.artifact_json:
            return {}
        try:
            parsed = json.loads(run.artifact_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _plan_generation_tuning_request(cls, run: Run) -> dict[str, object]:
        artifact = cls._get_run_artifact(run)
        request = artifact.get("plan_generation_tuning_request")
        if isinstance(request, dict):
            return request
        if (run.job_name or "").strip() == "Auto: Actionability Floor Calibration Weekly":
            return {
                "mode": "actionability_floor_calibration",
                "floors": [float(value) for value in range(40, 61)],
                "min_resolved_trades": 10,
            }
        return {}

    @staticmethod
    def _plan_generation_tuning_string(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _plan_generation_tuning_int(value: object, default: int | None) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @classmethod
    def _build_failure_artifact(
        cls, current_run: Run, claimed_run: Run, exc: RunExecutionFailed
    ) -> dict[str, object]:
        artifact = cls._get_run_artifact(current_run)
        existing_failure = (
            artifact.get("failure") if isinstance(artifact.get("failure"), dict) else {}
        )
        artifact["failure"] = {
            **existing_failure,
            "job_type": claimed_run.job_type.value,
            "message": str(exc.cause),
            "failed_after_phase": cls._infer_failure_phase(exc.timing),
            "had_summary_before_failure": bool(current_run.summary_json),
            "had_artifact_before_failure": bool(current_run.artifact_json),
        }
        return artifact

    @staticmethod
    def _infer_failure_phase(timing: dict[str, object]) -> str:
        ordered_phases = [
            "resolve_tickers_seconds",
            "recommendation_generation_seconds",
            "macro_context_seconds",
            "industry_context_seconds",
            "evaluation_seconds",
            "optimization_seconds",
            "replay_setup_seconds",
            "replay_execution_seconds",
            "persistence_seconds",
            "order_execution_seconds",
            "finalize_seconds",
        ]
        for phase in reversed(ordered_phases):
            value = timing.get(phase)
            if isinstance(value, (int, float)) and float(value) > 0:
                return phase.removesuffix("_seconds")
        return "startup"

    @staticmethod
    def _calculate_queue_wait_seconds(run: Run) -> float:
        if run.started_at is None:
            return 0.0
        started_at = JobExecutionService._normalize_datetime(run.started_at)
        created_at = JobExecutionService._normalize_datetime(run.created_at)
        if started_at is None or created_at is None:
            return 0.0
        return round(max(0.0, (started_at - created_at).total_seconds()), 6)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _get_ticker_generation_list(timing: dict[str, object]) -> list[dict[str, object]]:
        ticker_generation = timing.get("ticker_generation")
        if isinstance(ticker_generation, list):
            return ticker_generation
        normalized: list[dict[str, object]] = []
        timing["ticker_generation"] = normalized
        return normalized

    @staticmethod
    def _extract_watchlist(job) -> Watchlist | None:
        watchlist_name = getattr(job, "watchlist_name", None)
        watchlist_id = getattr(job, "watchlist_id", None)
        if watchlist_id is None or not watchlist_name:
            return None
        tickers = getattr(job, "tickers", [])
        default_horizon = getattr(job, "watchlist_default_horizon", None)
        if default_horizon is None:
            return None
        return Watchlist(
            id=watchlist_id,
            name=watchlist_name,
            tickers=tickers,
            description=getattr(job, "watchlist_description", ""),
            region=getattr(job, "watchlist_region", ""),
            exchange=getattr(job, "watchlist_exchange", ""),
            timezone=getattr(job, "watchlist_timezone", ""),
            default_horizon=default_horizon,
            allow_shorts=getattr(job, "watchlist_allow_shorts", True),
            optimize_evaluation_timing=getattr(job, "watchlist_optimize_evaluation_timing", False),
        )

    def _resolve_execution_watchlist(self, job, tickers: list[str]) -> Watchlist | None:
        watchlist = self._extract_watchlist(job)
        if watchlist is not None:
            return watchlist
        if getattr(job, "job_type", None) != JobType.PROPOSAL_GENERATION:
            return None
        if not tickers:
            return None
        return Watchlist(
            id=None,
            name=f"Manual ticker job: {getattr(job, 'name', 'proposal_generation')}",
            tickers=tickers,
            description="Synthetic watchlist wrapper for redesign-native manual proposal execution.",
            region="",
            exchange="",
            timezone="",
            default_horizon=StrategyHorizon.ONE_WEEK,
            allow_shorts=True,
            optimize_evaluation_timing=False,
        )

    @staticmethod
    def _annotate_orchestration_payload(
        payload: dict[str, object], watchlist: Watchlist, job
    ) -> None:
        source_kind = "watchlist" if watchlist.id is not None else "manual_tickers"
        payload["source_kind"] = source_kind
        payload["execution_path"] = "redesign_orchestration"
        payload["effective_horizon"] = watchlist.default_horizon.value
        if source_kind == "manual_tickers":
            payload["manual_job_defaults"] = {
                "default_horizon": watchlist.default_horizon.value,
                "allow_shorts": watchlist.allow_shorts,
                "optimize_evaluation_timing": watchlist.optimize_evaluation_timing,
                "job_name": getattr(job, "name", "proposal_generation"),
            }
