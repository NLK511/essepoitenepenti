import json
import logging
import os
import socket
from datetime import datetime, timezone
from time import perf_counter

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import JobType, RunStatus, StrategyHorizon
from trade_proposer_app.domain.models import EvaluationRunResult, Recommendation, Run, Watchlist, WorkerHeartbeat
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.industry_context_refresh import IndustryContextRefreshService
from trade_proposer_app.services.macro_context_refresh import MacroContextRefreshService
from trade_proposer_app.services.performance_assessment import PerformanceAssessmentService
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService


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
        historical_replay: HistoricalReplayService | None = None,
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
        self.historical_replay = historical_replay

    def enqueue_job(self, job_id: int, scheduled_for: datetime | None = None) -> Run:
        self.runs.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
        job = self.jobs.get(job_id)
        if scheduled_for is not None:
            existing_scheduled_run = self.runs.get_run_for_job_and_scheduled_for(job.id or job_id, scheduled_for)
            if existing_scheduled_run is not None:
                return existing_scheduled_run
        if job.job_type == JobType.PLAN_GENERATION_TUNING:
            active_tuning_run = self.runs.get_active_run_for_job_type(JobType.PLAN_GENERATION_TUNING)
            if active_tuning_run is not None:
                return active_tuning_run
        active_run = self.runs.get_active_run_for_job(job.id or job_id)
        if active_run is not None:
            return active_run
        queued_run = self.runs.enqueue(job.id or job_id, scheduled_for=scheduled_for, job_type=job.job_type)
        self.jobs.mark_enqueued(job.id or job_id)
        return queued_run

    def execute_run(self, run_id: int, worker_id: str | None = None) -> tuple[list[Recommendation], dict[str, object]]:
        run = self.runs.get_run(run_id)
        logger.info(
            "job execution dispatch started: run_id=%s job_id=%s job_type=%s worker_id=%s",
            run.id,
            run.job_id,
            run.job_type.value,
            worker_id,
        )
        logger.debug(
            "job execution dispatch payload: run_id=%s scheduled_for=%s started_at=%s artifact=%s",
            run.id,
            self._normalize_datetime(run.scheduled_for),
            self._normalize_datetime(run.started_at),
            self._get_run_artifact(run),
        )
        if worker_id:
            self.runs.upsert_heartbeat(WorkerHeartbeat(
                worker_id=worker_id,
                hostname=socket.gethostname(),
                pid=os.getpid(),
                status="running",
                last_heartbeat_at=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc), # simplified
                active_run_id=run_id,
            ))
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
        raise RuntimeError(f"unsupported job_type execution: {run.job_type.value}")

    def _execute_proposal_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        logger.info(
            "job execution proposal started: run_id=%s job_id=%s worker=%s",
            run.id,
            run.job_id,
            socket.gethostname(),
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
                raise RuntimeError("proposal_generation runs require the redesign watchlist orchestration service")
            orchestration = self.watchlist_orchestration.execute(
                watchlist,
                tickers,
                job_id=run.job_id,
                run_id=run.id,
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
                sorted(orchestration.get("summary", {}).keys()) if isinstance(orchestration.get("summary"), dict) else None,
                sorted(orchestration.get("artifact", {}).keys()) if isinstance(orchestration.get("artifact"), dict) else None,
            )
            ticker_generation.extend(orchestration.get("ticker_generation", []))
            warnings_found = bool(orchestration.get("warnings_found"))
            summary = orchestration.get("summary")
            artifact = orchestration.get("artifact")
            if isinstance(summary, dict):
                self._annotate_orchestration_payload(summary, watchlist, job)
                self.runs.set_summary(run.id or 0, summary)
            if isinstance(artifact, dict):
                self._annotate_orchestration_payload(artifact, watchlist, job)
                self.runs.set_artifact(run.id or 0, artifact)
            timing["recommendation_generation_seconds"] = round(perf_counter() - generation_started, 6)
        except Exception as exc:
            timing["recommendation_generation_seconds"] = round(perf_counter() - generation_started, 6)
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

        final_status = RunStatus.COMPLETED_WITH_WARNINGS.value if warnings_found else RunStatus.COMPLETED.value
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
        evaluation_as_of = self._normalize_datetime(run.scheduled_for) or self._normalize_datetime(run.started_at) or datetime.now(timezone.utc)
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

    def _execute_plan_generation_tuning_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.plan_generation_tuning is None:
            raise RuntimeError("plan generation tuning execution service is not configured")
        conflicting_run = self.runs.get_active_run_for_job_type(JobType.PLAN_GENERATION_TUNING, exclude_run_id=run.id or 0)
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
        try:
            tuning_run = self.plan_generation_tuning.run(mode="scheduled", apply=False)
            summary = tuning_run.summary
            artifact = {
                "plan_generation_tuning_run_id": tuning_run.id,
                "winner_candidate_id": tuning_run.winning_candidate_id,
                "promoted_config_version_id": tuning_run.promoted_config_version_id,
            }
            timing["plan_generation_tuning_seconds"] = round(perf_counter() - tuning_started, 6)
        except Exception as exc:
            timing["plan_generation_tuning_seconds"] = round(perf_counter() - tuning_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_performance_assessment_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
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

        final_status = RunStatus.COMPLETED_WITH_WARNINGS.value if warnings_found else RunStatus.COMPLETED.value
        self._finalize_success(run.id or 0, final_status, timing, execution_started)
        return [], timing

    def _execute_macro_context_refresh_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
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
            "computed_at": (payload.computed_at.isoformat() if payload and getattr(payload, "computed_at", None) else None),
        }
        if payload is not None and self.macro_context is not None:
            context_snapshot = self.macro_context.create_from_refresh_payload(payload, job_id=run.job_id, run_id=run.id)
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

    def _execute_industry_context_refresh_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
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
            refresh_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
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
                    self.industry_context.create_from_refresh_payload(payload, job_id=run.job_id, run_id=run.id)
                )
            summary["industry_context_snapshot_count"] = len(context_snapshots)
            summary["industry_context_snapshot_ids"] = [getattr(snapshot, "id", None) for snapshot in context_snapshots]
        self.runs.set_summary(run.id or 0, summary)
        artifact = {
            "scope": "industry",
            "snapshot_count": len(payloads),
            "subject_keys": [getattr(payload, "subject_key", None) for payload in payloads],
            "industry_context_snapshot_ids": [getattr(snapshot, "id", None) for snapshot in context_snapshots],
        }
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_historical_replay_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
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
        replay_payload = artifact.get("historical_replay") if isinstance(artifact.get("historical_replay"), dict) else {}
        batch_id = replay_payload.get("batch_id")
        slice_id = replay_payload.get("slice_id")
        if not isinstance(batch_id, int) or not isinstance(slice_id, int):
            raise RuntimeError("historical replay run is missing batch_id or slice_id artifact metadata")

        setup_started = perf_counter()
        self.historical_replay.mark_slice_running(slice_id)
        timing["replay_setup_seconds"] = round(perf_counter() - setup_started, 6)

        execution_phase_started = perf_counter()
        try:
            input_summary, output_summary = self.historical_replay.build_slice_execution_payload(batch_id, slice_id)
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

    def process_next_queued_run(self, worker_id: str | None = None) -> tuple[Run | None, list[Recommendation]]:
        self.runs.recover_stale_running_runs(stale_after_seconds=settings.run_stale_after_seconds)
        run = self.runs.claim_next_queued_run(worker_id=worker_id)
        if run is None:
            return None, []
        return self.execute_claimed_run(run, worker_id=worker_id)

    def execute_claimed_run(self, run: Run, worker_id: str | None = None) -> tuple[Run, list[Recommendation]]:
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
                self.runs.update_status(run.id or 0, RunStatus.FAILED.value, error_message=str(exc.cause), timing=exc.timing)
                exc.timing["finalize_seconds"] = round(perf_counter() - finalize_started, 6)
                exc.timing["total_execution_seconds"] = round(
                    float(exc.timing.get("total_execution_seconds") or 0.0) + float(exc.timing["finalize_seconds"]),
                    6,
                )
                self.runs.set_timing(run.id or 0, exc.timing)
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
    def _get_run_artifact(run: Run) -> dict[str, object]:
        if not run.artifact_json:
            return {}
        try:
            parsed = json.loads(run.artifact_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _build_failure_artifact(cls, current_run: Run, claimed_run: Run, exc: RunExecutionFailed) -> dict[str, object]:
        artifact = cls._get_run_artifact(current_run)
        existing_failure = artifact.get("failure") if isinstance(artifact.get("failure"), dict) else {}
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
    def _annotate_orchestration_payload(payload: dict[str, object], watchlist: Watchlist, job) -> None:
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
