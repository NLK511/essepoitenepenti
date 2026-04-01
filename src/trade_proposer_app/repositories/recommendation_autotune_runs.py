from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationAutotuneRun
from trade_proposer_app.persistence.models import RecommendationAutotuneRunRecord


class RecommendationAutotuneRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, run: RecommendationAutotuneRun) -> RecommendationAutotuneRun:
        record = RecommendationAutotuneRunRecord()
        self._apply(record, run)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_runs(self, limit: int = 20) -> list[RecommendationAutotuneRun]:
        rows = self.session.scalars(
            select(RecommendationAutotuneRunRecord)
            .order_by(desc(RecommendationAutotuneRunRecord.created_at), desc(RecommendationAutotuneRunRecord.id))
            .limit(limit)
        ).all()
        return [self._to_model(row) for row in rows]

    def get_latest_run(self) -> RecommendationAutotuneRun | None:
        row = self.session.scalar(
            select(RecommendationAutotuneRunRecord)
            .order_by(desc(RecommendationAutotuneRunRecord.created_at), desc(RecommendationAutotuneRunRecord.id))
            .limit(1)
        )
        return self._to_model(row) if row is not None else None

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=RecommendationAutotuneRunRepository._json_default)

    @staticmethod
    def _json_default(value: object) -> object:
        if isinstance(value, datetime):
            normalized = RecommendationAutotuneRunRepository._normalize_datetime(value)
            return normalized.isoformat() if normalized is not None else None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    def _apply(self, record: RecommendationAutotuneRunRecord, run: RecommendationAutotuneRun) -> None:
        record.objective_name = run.objective_name
        record.status = run.status
        record.applied = run.applied
        record.filters_json = self._dump(run.filters)
        record.sample_count = run.sample_count
        record.resolved_sample_count = run.resolved_sample_count
        record.candidate_count = run.candidate_count
        record.baseline_threshold = run.baseline_threshold
        record.baseline_score = run.baseline_score
        record.best_threshold = run.best_threshold
        record.best_score = run.best_score
        record.winning_config_json = self._dump(run.winning_config)
        record.candidate_results_json = self._dump(run.candidate_results)
        record.summary_json = self._dump(run.summary)
        record.artifact_json = self._dump(run.artifact)
        record.error_message = run.error_message or ""
        record.started_at = self._normalize_datetime(run.started_at)
        record.completed_at = self._normalize_datetime(run.completed_at)

    def _to_model(self, record: RecommendationAutotuneRunRecord) -> RecommendationAutotuneRun:
        return RecommendationAutotuneRun(
            id=record.id,
            objective_name=record.objective_name,
            status=record.status,
            applied=record.applied,
            filters=self._load_json(record.filters_json),
            sample_count=record.sample_count,
            resolved_sample_count=record.resolved_sample_count,
            candidate_count=record.candidate_count,
            baseline_threshold=record.baseline_threshold,
            baseline_score=record.baseline_score,
            best_threshold=record.best_threshold,
            best_score=record.best_score,
            winning_config=self._load_json(record.winning_config_json),
            candidate_results=self._load_json_list(record.candidate_results_json),
            summary=self._load_json(record.summary_json),
            artifact=self._load_json(record.artifact_json),
            error_message=record.error_message or None,
            started_at=self._normalize_datetime(record.started_at),
            completed_at=self._normalize_datetime(record.completed_at),
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_json_list(raw: str | None) -> list[dict[str, object]]:
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []
