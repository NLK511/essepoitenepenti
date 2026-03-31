from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationDecisionSample
from trade_proposer_app.persistence.models import RecommendationDecisionSampleRecord


class RecommendationDecisionSampleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_sample(self, sample: RecommendationDecisionSample) -> RecommendationDecisionSample:
        record = self.session.scalar(
            select(RecommendationDecisionSampleRecord).where(
                RecommendationDecisionSampleRecord.recommendation_plan_id == sample.recommendation_plan_id
            )
        )
        if record is None:
            record = RecommendationDecisionSampleRecord(recommendation_plan_id=sample.recommendation_plan_id)
            self.session.add(record)
        record.ticker = sample.ticker.upper()
        record.horizon = sample.horizon
        record.action = sample.action
        record.decision_type = sample.decision_type
        record.decision_reason = sample.decision_reason
        record.shortlisted = sample.shortlisted
        record.shortlist_rank = sample.shortlist_rank
        record.shortlist_decision_json = self._dump(sample.shortlist_decision)
        record.confidence_percent = sample.confidence_percent
        record.calibrated_confidence_percent = sample.calibrated_confidence_percent
        record.effective_threshold_percent = sample.effective_threshold_percent
        record.confidence_gap_percent = sample.confidence_gap_percent
        record.setup_family = sample.setup_family
        record.transmission_bias = sample.transmission_bias
        record.context_regime = sample.context_regime
        record.review_priority = sample.review_priority
        record.review_label = sample.review_label
        record.review_notes = sample.review_notes
        record.reviewed_at = self._normalize_datetime(sample.reviewed_at)
        record.decision_context_json = self._dump(sample.decision_context)
        record.signal_breakdown_json = self._dump(sample.signal_breakdown)
        record.evidence_summary_json = self._dump(sample.evidence_summary)
        record.run_id = sample.run_id
        record.job_id = sample.job_id
        record.watchlist_id = sample.watchlist_id
        record.ticker_signal_snapshot_id = sample.ticker_signal_snapshot_id
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_samples(
        self,
        *,
        ticker: str | None = None,
        run_id: int | None = None,
        decision_type: str | None = None,
        review_priority: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationDecisionSample]:
        query = select(RecommendationDecisionSampleRecord)
        if ticker:
            query = query.where(RecommendationDecisionSampleRecord.ticker == ticker.upper())
        if run_id is not None:
            query = query.where(RecommendationDecisionSampleRecord.run_id == run_id)
        if decision_type:
            query = query.where(RecommendationDecisionSampleRecord.decision_type == decision_type)
        if review_priority:
            query = query.where(RecommendationDecisionSampleRecord.review_priority == review_priority)
        rows = self.session.scalars(
            query.order_by(RecommendationDecisionSampleRecord.created_at.desc()).limit(limit)
        ).all()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

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
    def _dump(value: object) -> str:
        return json.dumps(value, default=RecommendationDecisionSampleRepository._json_default)

    @staticmethod
    def _json_default(value: object) -> object:
        if isinstance(value, datetime):
            normalized = RecommendationDecisionSampleRepository._normalize_datetime(value)
            return normalized.isoformat() if normalized is not None else None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    def _to_model(self, record: RecommendationDecisionSampleRecord) -> RecommendationDecisionSample:
        return RecommendationDecisionSample(
            id=record.id,
            recommendation_plan_id=record.recommendation_plan_id,
            ticker=record.ticker,
            horizon=record.horizon,
            action=record.action,
            decision_type=record.decision_type,
            decision_reason=record.decision_reason,
            shortlisted=record.shortlisted,
            shortlist_rank=record.shortlist_rank,
            shortlist_decision=self._load_json(record.shortlist_decision_json),
            confidence_percent=record.confidence_percent,
            calibrated_confidence_percent=record.calibrated_confidence_percent,
            effective_threshold_percent=record.effective_threshold_percent,
            confidence_gap_percent=record.confidence_gap_percent,
            setup_family=record.setup_family,
            transmission_bias=record.transmission_bias,
            context_regime=record.context_regime,
            review_priority=record.review_priority,
            review_label=record.review_label,
            review_notes=record.review_notes,
            reviewed_at=self._normalize_datetime(record.reviewed_at),
            decision_context=self._load_json(record.decision_context_json),
            signal_breakdown=self._load_json(record.signal_breakdown_json),
            evidence_summary=self._load_json(record.evidence_summary_json),
            run_id=record.run_id,
            job_id=record.job_id,
            watchlist_id=record.watchlist_id,
            ticker_signal_snapshot_id=record.ticker_signal_snapshot_id,
            created_at=self._normalize_datetime(record.created_at) or datetime.now(timezone.utc),
            updated_at=self._normalize_datetime(record.updated_at) or datetime.now(timezone.utc),
        )
