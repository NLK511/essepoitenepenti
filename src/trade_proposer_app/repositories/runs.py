import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from trade_proposer_app.domain.enums import JobType, RecommendationState, RunStatus
from trade_proposer_app.domain.models import Recommendation, RecommendationHistoryItem, Run, RunDiagnostics, RunOutput
from trade_proposer_app.persistence.models import JobRecord, RecommendationRecord, RunRecord


ACTIVE_RUN_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
TERMINAL_RUN_STATUSES = (
    RunStatus.COMPLETED.value,
    RunStatus.COMPLETED_WITH_WARNINGS.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELED.value,
)


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        job_id: int,
        status: str,
        error_message: str | None = None,
        scheduled_for: datetime | None = None,
        job_type: JobType | None = None,
    ) -> Run:
        resolved_job_type = self._resolve_job_type(job_id, job_type)
        record = RunRecord(
            job_id=job_id,
            job_type=resolved_job_type.value,
            status=status,
            error_message=error_message or "",
            scheduled_for=scheduled_for,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def enqueue(
        self,
        job_id: int,
        scheduled_for: datetime | None = None,
        job_type: JobType | None = None,
    ) -> Run:
        return self.create(
            job_id=job_id,
            status=RunStatus.QUEUED.value,
            scheduled_for=scheduled_for,
            job_type=job_type,
        )

    def get_run(self, run_id: int) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        return self._to_run_model(record)

    def get_active_run_for_job(self, job_id: int) -> Run | None:
        record = self.session.scalars(
            select(RunRecord)
            .where(RunRecord.job_id == job_id)
            .where(RunRecord.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(RunRecord.created_at.desc())
            .limit(1)
        ).first()
        if record is None:
            return None
        return self._to_run_model(record)

    def get_run_for_job_and_scheduled_for(self, job_id: int, scheduled_for: datetime) -> Run | None:
        record = self.session.scalars(
            select(RunRecord)
            .where(RunRecord.job_id == job_id)
            .where(RunRecord.scheduled_for == scheduled_for)
            .order_by(RunRecord.created_at.desc())
            .limit(1)
        ).first()
        if record is None:
            return None
        return self._to_run_model(record)

    def get_active_run_for_job_type(self, job_type: JobType, exclude_run_id: int | None = None) -> Run | None:
        query = (
            select(RunRecord)
            .where(RunRecord.job_type == job_type.value)
            .where(RunRecord.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(RunRecord.created_at.desc())
            .limit(1)
        )
        if exclude_run_id is not None:
            query = query.where(RunRecord.id != exclude_run_id)
        record = self.session.scalars(query).first()
        if record is None:
            return None
        return self._to_run_model(record)

    def claim_next_queued_run(self) -> Run | None:
        while True:
            candidate_id = self.session.scalars(
                select(RunRecord.id)
                .where(RunRecord.status == RunStatus.QUEUED.value)
                .order_by(RunRecord.created_at.asc())
                .limit(1)
            ).first()
            if candidate_id is None:
                return None

            started_at = datetime.now(timezone.utc)
            result = self.session.execute(
                update(RunRecord)
                .where(RunRecord.id == candidate_id)
                .where(RunRecord.status == RunStatus.QUEUED.value)
                .values(
                    status=RunStatus.RUNNING.value,
                    error_message="",
                    started_at=started_at,
                    completed_at=None,
                    duration_seconds=None,
                )
            )
            self.session.commit()
            if result.rowcount == 1:
                record = self.session.get(RunRecord, candidate_id)
                if record is None:
                    return None
                return self._to_run_model(record)

    def update_status(
        self,
        run_id: int,
        status: str,
        error_message: str | None = None,
        timing: dict[str, object] | None = None,
    ) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.status = status
        record.error_message = error_message or ""
        if timing is not None:
            record.timing_json = self._serialize_timing(timing)
        if status in TERMINAL_RUN_STATUSES:
            record.completed_at = datetime.now(timezone.utc)
            if record.started_at is not None:
                completed_at = self._normalize_datetime(record.completed_at)
                started_at = self._normalize_datetime(record.started_at)
                record.duration_seconds = max(0.0, (completed_at - started_at).total_seconds())
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def list_latest_runs(self, limit: int = 20) -> list[Run]:
        rows = self.session.scalars(select(RunRecord).order_by(RunRecord.created_at.desc()).limit(limit)).all()
        return [self._to_run_model(row) for row in rows]

    def list_latest_runs_above_confidence_threshold(self, confidence_threshold: float, limit: int = 20) -> list[Run]:
        rows = self.session.scalars(
            select(RunRecord)
            .options(selectinload(RunRecord.recommendations))
            .order_by(RunRecord.created_at.desc())
        ).all()
        filtered: list[Run] = []
        for row in rows:
            if any(recommendation.confidence >= confidence_threshold for recommendation in row.recommendations):
                filtered.append(self._to_run_model(row))
            if len(filtered) >= limit:
                break
        return filtered

    def set_timing(self, run_id: int, timing: dict[str, object]) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.timing_json = self._serialize_timing(timing)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def set_summary(self, run_id: int, summary: dict[str, object]) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.summary_json = self._serialize_timing(summary)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def set_artifact(self, run_id: int, artifact: dict[str, object]) -> Run:
        record = self.session.get(RunRecord, run_id)
        if record is None:
            raise ValueError(f"Run {run_id} not found")
        record.artifact_json = self._serialize_timing(artifact)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run_model(record)

    def add_recommendation(self, run_id: int, recommendation: Recommendation, diagnostics: RunDiagnostics) -> Recommendation:
        record = RecommendationRecord(
            run_id=run_id,
            ticker=recommendation.ticker,
            direction=recommendation.direction.value,
            confidence=recommendation.confidence,
            entry_price=recommendation.entry_price,
            stop_loss=recommendation.stop_loss,
            take_profit=recommendation.take_profit,
            indicator_summary=recommendation.indicator_summary,
            evaluation_state=recommendation.state.value,
            evaluated_at=recommendation.evaluated_at,
            warnings_json="\n".join(diagnostics.warnings),
            provider_errors_json="\n".join(diagnostics.provider_errors),
            problems_json="\n".join(diagnostics.problems),
            news_feed_errors_json="\n".join(diagnostics.news_feed_errors),
            summary_error=diagnostics.summary_error or "",
            llm_error=diagnostics.llm_error or "",
            analysis_json=diagnostics.analysis_json or "",
            raw_output=diagnostics.raw_output or "",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_recommendation_model(record)

    def list_latest_recommendations(self, limit: int = 20) -> list[Recommendation]:
        rows = self.session.scalars(
            select(RecommendationRecord)
            .order_by(RecommendationRecord.created_at.desc())
            .limit(limit)
        ).all()
        return [self._to_recommendation_model(row) for row in rows]

    def get_recommendation(self, recommendation_id: int) -> Recommendation:
        record = self.session.get(RecommendationRecord, recommendation_id)
        if record is None:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        return self._to_recommendation_model(record)

    def get_recommendation_diagnostics(self, recommendation_id: int) -> RunDiagnostics:
        record = self.session.get(RecommendationRecord, recommendation_id)
        if record is None:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        return self._to_diagnostics_model(record)

    def list_outputs_for_run(self, run_id: int) -> list[RunOutput]:
        rows = self.session.scalars(
            select(RecommendationRecord)
            .where(RecommendationRecord.run_id == run_id)
            .order_by(RecommendationRecord.created_at.desc())
        ).all()
        return [RunOutput(recommendation=self._to_recommendation_model(row), diagnostics=self._to_diagnostics_model(row)) for row in rows]

    def list_recommendations_for_run(self, run_id: int) -> list[Recommendation]:
        return [output.recommendation for output in self.list_outputs_for_run(run_id)]

    def list_recommendation_history(self) -> list[RecommendationHistoryItem]:
        rows = self.session.execute(
            select(RecommendationRecord, RunRecord)
            .join(RunRecord, RecommendationRecord.run_id == RunRecord.id)
            .order_by(RecommendationRecord.created_at.desc())
        ).all()
        return [self._to_recommendation_history_item(recommendation_record, run_record) for recommendation_record, run_record in rows]

    def set_recommendation_state(
        self,
        recommendation_id: int,
        state: RecommendationState,
        evaluated_at: datetime | None = None,
    ) -> Recommendation:
        record = self.session.get(RecommendationRecord, recommendation_id)
        if record is None:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        record.evaluation_state = state.value
        record.evaluated_at = evaluated_at
        self.session.commit()
        self.session.refresh(record)
        return self._to_recommendation_model(record)

    def list_recommendation_history_for_ticker(self, ticker: str) -> list[RecommendationHistoryItem]:
        rows = self.session.execute(
            select(RecommendationRecord, RunRecord)
            .join(RunRecord, RecommendationRecord.run_id == RunRecord.id)
            .where(RecommendationRecord.ticker == ticker)
            .order_by(RecommendationRecord.created_at.desc())
        ).all()
        return [self._to_recommendation_history_item(recommendation_record, run_record) for recommendation_record, run_record in rows]

    @classmethod
    def _to_run_model(cls, record: RunRecord) -> Run:
        return Run(
            id=record.id,
            job_id=record.job_id,
            job_type=JobType(record.job_type or JobType.PROPOSAL_GENERATION.value),
            status=record.status,
            error_message=record.error_message or None,
            scheduled_for=cls._normalize_optional_datetime(record.scheduled_for),
            summary_json=record.summary_json or None,
            artifact_json=record.artifact_json or None,
            created_at=cls._normalize_datetime(record.created_at),
            updated_at=cls._normalize_datetime(record.updated_at),
            started_at=cls._normalize_optional_datetime(record.started_at),
            completed_at=cls._normalize_optional_datetime(record.completed_at),
            duration_seconds=record.duration_seconds,
            timing_json=record.timing_json or None,
        )

    @classmethod
    def _to_recommendation_model(cls, record: RecommendationRecord) -> Recommendation:
        return Recommendation(
            id=record.id,
            run_id=record.run_id,
            ticker=record.ticker,
            direction=record.direction,
            confidence=record.confidence,
            entry_price=record.entry_price,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            indicator_summary=record.indicator_summary or "",
            state=record.evaluation_state or RecommendationState.PENDING.value,
            created_at=record.created_at,
            evaluated_at=record.evaluated_at,
        )

    @classmethod
    def _to_diagnostics_model(cls, record: RecommendationRecord) -> RunDiagnostics:
        return RunDiagnostics(
            warnings=cls._split_lines(record.warnings_json),
            provider_errors=cls._split_lines(record.provider_errors_json),
            problems=cls._split_lines(record.problems_json),
            news_feed_errors=cls._split_lines(record.news_feed_errors_json),
            summary_error=record.summary_error or None,
            llm_error=record.llm_error or None,
            raw_output=record.raw_output or None,
            analysis_json=record.analysis_json or None,
        )

    @classmethod
    def _to_recommendation_history_item(
        cls,
        recommendation_record: RecommendationRecord,
        run_record: RunRecord,
    ) -> RecommendationHistoryItem:
        warnings = cls._split_lines(recommendation_record.warnings_json)
        provider_errors = cls._split_lines(recommendation_record.provider_errors_json)
        return RecommendationHistoryItem(
            recommendation_id=recommendation_record.id,
            run_id=run_record.id,
            run_status=run_record.status,
            ticker=recommendation_record.ticker,
            direction=recommendation_record.direction,
            confidence=recommendation_record.confidence,
            entry_price=recommendation_record.entry_price,
            stop_loss=recommendation_record.stop_loss,
            take_profit=recommendation_record.take_profit,
            indicator_summary=recommendation_record.indicator_summary or "",
            state=recommendation_record.evaluation_state or RecommendationState.PENDING.value,
            created_at=recommendation_record.created_at,
            evaluated_at=recommendation_record.evaluated_at,
            warnings=warnings,
            provider_errors=provider_errors,
            summary_error=recommendation_record.summary_error or None,
            llm_error=recommendation_record.llm_error or None,
        )

    def _resolve_job_type(self, job_id: int, job_type: JobType | None) -> JobType:
        if job_type is not None:
            return job_type
        job = self.session.get(JobRecord, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        return JobType(job.job_type or JobType.PROPOSAL_GENERATION.value)

    @staticmethod
    def _split_lines(value: str) -> list[str]:
        return [item for item in value.split("\n") if item]

    @staticmethod
    def _serialize_timing(timing: dict[str, object]) -> str:
        return json.dumps(timing, indent=2, sort_keys=True)

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _normalize_optional_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return cls._normalize_datetime(value)
