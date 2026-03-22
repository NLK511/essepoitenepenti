import json
from datetime import datetime
from time import perf_counter

from trade_proposer_app.domain.enums import JobType, RunStatus
from trade_proposer_app.domain.models import EvaluationRunResult, Recommendation, Run, RunOutput
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.evaluation_execution import EvaluationExecutionService
from trade_proposer_app.services.industry_sentiment import IndustrySentimentService
from trade_proposer_app.services.macro_sentiment import MacroSentimentService
from trade_proposer_app.services.optimizations import WeightOptimizationError, WeightOptimizationService
from trade_proposer_app.services.proposals import ProposalExecutionError, ProposalService


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
        proposals: ProposalService,
        evaluations: EvaluationExecutionService | None = None,
        optimizations: WeightOptimizationService | None = None,
        macro_sentiment: MacroSentimentService | None = None,
        industry_sentiment: IndustrySentimentService | None = None,
    ) -> None:
        self.jobs = jobs
        self.runs = runs
        self.proposals = proposals
        self.evaluations = evaluations
        self.optimizations = optimizations
        self.macro_sentiment = macro_sentiment
        self.industry_sentiment = industry_sentiment

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
        if run.job_type == JobType.MACRO_SENTIMENT_REFRESH:
            return self._execute_macro_sentiment_run(run)
        if run.job_type == JobType.INDUSTRY_SENTIMENT_REFRESH:
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
        tickers = self.jobs.resolve_tickers(run.job_id)
        timing["resolve_tickers_seconds"] = round(perf_counter() - resolve_started, 6)

        generated: list[RunOutput] = []
        warnings_found = False
        generation_started = perf_counter()

        try:
            ticker_generation = self._get_ticker_generation_list(timing)
            for ticker in tickers:
                ticker_started = perf_counter()
                try:
                    output = self.proposals.generate(ticker)
                except ProposalExecutionError as exc:
                    ticker_generation.append(
                        {
                            "ticker": ticker,
                            "duration_seconds": round(perf_counter() - ticker_started, 6),
                            "status": "failed",
                            "error_message": str(exc),
                        }
                    )
                    warnings_found = True
                    continue
                except Exception as exc:
                    ticker_generation.append(
                        {
                            "ticker": ticker,
                            "duration_seconds": round(perf_counter() - ticker_started, 6),
                            "status": "failed",
                            "error_message": str(exc),
                        }
                    )
                    raise
                ticker_duration = round(perf_counter() - ticker_started, 6)
                ticker_generation.append(
                    {
                        "ticker": ticker,
                        "duration_seconds": ticker_duration,
                        "status": "completed",
                    }
                )
                if output.diagnostics.warnings:
                    warnings_found = True
                generated.append(output)
            timing["recommendation_generation_seconds"] = round(perf_counter() - generation_started, 6)
        except Exception as exc:
            timing["recommendation_generation_seconds"] = round(perf_counter() - generation_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        stored: list[Recommendation] = []
        for output in generated:
            stored.append(
                self.runs.add_recommendation(
                    run.id or 0,
                    output.recommendation,
                    output.diagnostics,
                )
            )
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
        if self.macro_sentiment is None:
            raise RuntimeError("macro sentiment execution service is not configured")

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
            result = self.macro_sentiment.refresh(job_id=run.job_id, run_id=run.id)
            timing["macro_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["macro_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, result.get("summary", {}))
        snapshot = result.get("snapshot")
        artifact = {
            "snapshot_id": getattr(snapshot, "id", None),
            "scope": "macro",
            "subject_key": getattr(snapshot, "subject_key", None),
            "subject_label": getattr(snapshot, "subject_label", None),
        }
        self.runs.set_artifact(run.id or 0, artifact)
        timing["persistence_seconds"] = round(perf_counter() - persistence_started, 6)

        self._finalize_success(run.id or 0, RunStatus.COMPLETED.value, timing, execution_started)
        return [], timing

    def _execute_industry_sentiment_run(self, run: Run) -> tuple[list[Recommendation], dict[str, object]]:
        if self.industry_sentiment is None:
            raise RuntimeError("industry sentiment execution service is not configured")

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
            result = self.industry_sentiment.refresh_all(job_id=run.job_id, run_id=run.id)
            timing["industry_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
        except Exception as exc:
            timing["industry_refresh_seconds"] = round(perf_counter() - refresh_started, 6)
            timing["total_execution_seconds"] = round(perf_counter() - execution_started, 6)
            raise RunExecutionFailed(exc, timing) from exc

        persistence_started = perf_counter()
        self.runs.set_summary(run.id or 0, result.get("summary", {}))
        snapshots = result.get("snapshots") or []
        artifact = {
            "scope": "industry",
            "snapshot_count": len(snapshots),
            "snapshot_ids": [getattr(snapshot, "id", None) for snapshot in snapshots],
            "subject_keys": [getattr(snapshot, "subject_key", None) for snapshot in snapshots],
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

    def enqueue_manual_evaluation(self, recommendation_id: int | None = None) -> Run:
        job_name = "manual recommendation evaluation" if recommendation_id is not None else "manual evaluation"
        job = self.jobs.get_or_create_system_job(job_name, JobType.RECOMMENDATION_EVALUATION)
        run = self.runs.enqueue(job.id or 0, job_type=JobType.RECOMMENDATION_EVALUATION)
        artifact: dict[str, object] = {
            "trigger": {
                "mode": "manual_recommendation" if recommendation_id is not None else "manual_global",
                "source": "recommendations_ui",
            }
        }
        if recommendation_id is not None:
            recommendation = self.runs.get_recommendation(recommendation_id)
            artifact["scope"] = {
                "type": "recommendation_ids",
                "recommendation_ids": [recommendation_id],
                "ticker": recommendation.ticker,
            }
        self.runs.set_artifact(run.id or 0, artifact)
        self.jobs.mark_enqueued(job.id or 0)
        return self.runs.get_run(run.id or 0)

    @staticmethod
    def _evaluation_result_to_summary(result: EvaluationRunResult) -> dict[str, object]:
        return {
            "evaluated_trade_log_entries": result.evaluated_trade_log_entries,
            "synced_recommendations": result.synced_recommendations,
            "pending_recommendations": result.pending_recommendations,
            "win_recommendations": result.win_recommendations,
            "loss_recommendations": result.loss_recommendations,
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
