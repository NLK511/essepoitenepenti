import json
from datetime import datetime
from time import perf_counter

from trade_proposer_app.domain.enums import JobType, RunStatus, StrategyHorizon
from trade_proposer_app.domain.models import EvaluationRunResult, Recommendation, Run, Watchlist
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.industry_support import IndustrySupportRefreshService
from trade_proposer_app.services.macro_support import MacroSupportRefreshService
from trade_proposer_app.services.optimizations import WeightOptimizationService


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
        optimizations: WeightOptimizationService | None = None,
        macro_support: MacroSupportRefreshService | None = None,
        industry_support: IndustrySupportRefreshService | None = None,
        macro_context=None,
        industry_context=None,
        watchlist_orchestration=None,
        recommendation_plans=None,
    ) -> None:
        self.jobs = jobs
        self.runs = runs
        self.evaluations = evaluations
        self.optimizations = optimizations
        self.macro_support = macro_support
        self.industry_support = industry_support
        self.macro_context = macro_context
        self.industry_context = industry_context
        self.watchlist_orchestration = watchlist_orchestration
        self.recommendation_plans = recommendation_plans

    def enqueue_job(self, job_id: int, scheduled_for: datetime | None = None) -> Run:
        job = self.jobs.get(job_id)
        if scheduled_for is not None:
            existing_scheduled_run = self.runs.get_run_for_job_and_scheduled_for(job.id or job_id, scheduled_for)
            if existing_scheduled_run is not None:
                return existing_scheduled_run
        if job.job_type == JobType.WEIGHT_OPTIMIZATION:
            active_optimization_run = self.runs.get_active_run_for_job_type(JobType.WEIGHT_OPTIMIZATION)
            if active_optimization_run is not None:
                return active_optimization_run
        active_run = self.runs.get_active_run_for_job(job.id or job_id)
        if active_run is not None:
            return active_run
        queued_run = self.runs.enqueue(job.id or job_id, scheduled_for=scheduled_for, job_type=job.job_type)
        self.jobs.mark_enqueued(job.id or job_id)
        return queued_run

    def execute_run(self, run_id: int) -> tuple[list[Recommendation], dict[str, object]]:
        run = self.runs.get_run(run_id)
        if run.job_type == JobType.PROPOSAL_GENERATION:
            return self._execute_proposal_run(run)
        if run.job_type == JobType.RECOMMENDATION_EVALUATION:
            return self._execute_evaluation_run(run)
        if run.job_type == JobType.WEIGHT_OPTIMIZATION:
            return self._execute_optimization_run(run)
        if run.job_type == JobType.MACRO_CONTEXT_REFRESH:
            return self._execute_macro_sentiment_run(run)
        if run.job_type == JobType.INDUSTRY_CONTEXT_REFRESH:
            return self._execute_industry_sentiment_run(run)
        raise RuntimeError(f"unsupported job_type execution: {run.job_type.value}")

    def _execute_proposal_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
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
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        stored: list[Recommendation] = []
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        final_status = RunStatus.COMPLETED_WITH_WARNINGS.value if warnings_found else RunStatus.COMPLETED.value
        self._finalize_success(run.id or 0, final_status, timing, execution_started)
        return stored, timing

    def _execute_evaluation_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.evaluations is None:
            raise RuntimeError("recommendation evaluation execution service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "evaluation_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        evaluation_started = perf_counter()
        try:
            result = self.evaluations.execute(run)
            timing["evaluation_seconds"] = round(perf_counter() - evaluation_started, 6)
        except Exception as exc:
            timing["evaluation_seconds"] = round(perf_counter() - evaluation_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        summary = self._evaluation_result_to_summary(result)
        artifact = self._get_run_artifact(run)
        if artifact:
            summary["scope"] = artifact.get("scope")
            summary["trigger"] = artifact.get("trigger")
        self.runs.set_summary(run.id or 0, summary)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_optimization_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.optimizations is None:
            raise RuntimeError("weight optimization execution service is not configured")
        conflicting_run = self.runs.get_active_run_for_job_type(JobType.WEIGHT_OPTIMIZATION, exclude_run_id=run.id or 0)
        if conflicting_run is not None:
            raise RuntimeError(f"weight optimization already active in run {conflicting_run.id}")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "optimization_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        optimization_started = perf_counter()
        try:
            summary, artifact = self.optimizations.execute()
            timing["optimization_seconds"] = round(perf_counter() - optimization_started, 6)
        except Exception as exc:
            timing["optimization_seconds"] = round(perf_counter() - optimization_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, summary)
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        final_status = RunStatus.COMPLETED_WITH_WARNINGS.value if summary.get("weights_changed") is False else RunStatus.COMPLETED.value
        self._finalize_success(run.id or 0, final_status, timing, execution_started)
        return [], timing

    def _execute_macro_sentiment_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.macro_support is None:
            raise RuntimeError("macro support execution service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "macro_refresh_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        refresh_started = perf_counter()
        try:
            result = self.macro_support.refresh(job_id=run.job_id, run_id=run.id)
            timing["macro_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["macro_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        summary = dict(result.get("summary", {}))
        snapshot = result.get("snapshot")
        context_snapshot = None
        if snapshot is not None and self.macro_context is not None:
            context_snapshot = self.macro_context.create_from_support_snapshot(
                snapshot,
                job_id=run.job_id,
                run_id=run.id,
            )
            summary["macro_context_snapshot_id"] = getattr(context_snapshot, "id", None)
        self.runs.set_summary(run.id or 0, summary)
        artifact = {
            "snapshot_id": getattr(snapshot, "id", None),
            "scope": "macro",
            "subject_key": getattr(snapshot, "subject_key", None),
            "subject_label": getattr(snapshot, "subject_label", None),
            "macro_context_snapshot_id": getattr(context_snapshot, "id", None),
        }
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_industry_sentiment_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.industry_support is None:
            raise RuntimeError("industry support execution service is not configured")

        execution_started = perf_counter()
        timing: dict[str, object] = {
            "queue_wait_seconds": self._calculate_queue_wait_seconds(run),
            "industry_refresh_seconds": 0.0,
            "persistence_seconds": 0.0,
            "finalize_seconds": 0.0,
            "total_execution_seconds": 0.0,
        }

        refresh_started = perf_counter()
        try:
            result = self.industry_support.refresh_all(job_id=run.job_id, run_id=run.id)
            timing["industry_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["industry_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        summary = dict(result.get("summary", {}))
        snapshots = result.get("snapshots") or []
        context_snapshots = []
        if self.industry_context is not None:
            for snapshot in snapshots:
                context_snapshots.append(
                    self.industry_context.create_from_support_snapshot(
                        snapshot,
                        job_id=run.job_id,
                        run_id=run.id,
                    )
                )
            summary["industry_context_snapshot_count"] = len(context_snapshots)
            summary["industry_context_snapshot_ids"] = [getattr(snapshot, "id", None) for snapshot in context_snapshots]
        self.runs.set_summary(run.id or 0, summary)
        artifact = {
            "scope": "industry",
            "snapshot_count": len(snapshots),
            "snapshot_ids": [getattr(snapshot, "id", None) for snapshot in snapshots],
            "subject_keys": [getattr(snapshot, "subject_key", None) for snapshot in snapshots],
            "industry_context_snapshot_ids": [getattr(snapshot, "id", None) for snapshot in context_snapshots],
        }
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def process_next_queued_run(self) -> tuple[Run | None, list[Recommendation]]:
        run = self.runs.claim_next_queued_run()
        if run is None:
            return None, []
        return self.execute_claimed_run(run)

    def execute_claimed_run(self, run: Run) -> tuple[Run, list[Recommendation]]:
        try:
            recommendations, _timing = self.execute_run(run.id or 0)
            return self.runs.get_run(run.id or 0), recommendations
        except RunExecutionFailed as exc:
            finalize_started = perf_counter()
            exc.timing["finalize_seconds"] = 0.0
            exc.timing["total_execution_seconds"] = round(
                float(exc.timing.get("total_execution_seconds") or 0.0),
                6,
            )
            self.runs.update_status(run.id or 0, RunStatus.FAILED.value, error_message=str(exc.cause), timing=exc.timing)
            exc.timing["finalize_seconds"] = round(perf_counter() - finalize_started, 6)
            exc.timing["total_execution_seconds"] = round(
                float(exc.timing.get("total_execution_seconds") or 0.0) + float(exc.timing["finalize_seconds"]),
                6,
            )
            self.runs.set_timing(run.id or 0, exc.timing)
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

    @staticmethod
    def _get_run_artifact(run: Run) -> dict[str, object]:
        if not run.artifact_json:
            return {}
        try:
            parsed = json.loads(run.artifact_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _calculate_queue_wait_seconds(run: Run) -> float:
        if run.started_at is None:
            return 0.0
        started_at = run.started_at if run.started_at.tzinfo is not None else run.started_at.replace(tzinfo=None)
        created_at = run.created_at if run.created_at.tzinfo is not None else run.created_at.replace(tzinfo=None)
        if started_at.tzinfo is None and created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        if created_at.tzinfo is None and started_at.tzinfo is not None:
            started_at = started_at.replace(tzinfo=None)
        return round(max(0.0, (started_at - created_at).total_seconds()), 6)

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
