import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import IndustryContextSnapshot, KeyLabelDetail, MacroContextSnapshot, TickerSignalSnapshot
from trade_proposer_app.persistence.models import (
    IndustryContextSnapshotRecord,
    MacroContextSnapshotRecord,
    TickerSignalSnapshotRecord,
)
from datetime import datetime, timezone

from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class ContextSnapshotRepository:
    def __init__(self, session: Session, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.session = session
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def create_macro_context_snapshot(self, snapshot: MacroContextSnapshot) -> MacroContextSnapshot:
        record = MacroContextSnapshotRecord(
            computed_at=self._normalize_datetime(snapshot.computed_at),
            expires_at=self._normalize_datetime(snapshot.expires_at) if snapshot.expires_at else None,
            status=snapshot.status,
            summary_text=snapshot.summary_text,
            saliency_score=snapshot.saliency_score,
            confidence_percent=snapshot.confidence_percent,
            active_themes_json=self._dump(snapshot.active_themes),
            regime_tags_json=self._dump(snapshot.regime_tags),
            warnings_json=self._dump(snapshot.warnings),
            missing_inputs_json=self._dump(snapshot.missing_inputs),
            source_breakdown_json=self._dump(snapshot.source_breakdown),
            metadata_json=self._dump(snapshot.metadata),
            job_id=snapshot.job_id,
            run_id=snapshot.run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_macro_model(record)

    def list_macro_context_snapshots(self, limit: int = 20, run_id: int | None = None) -> list[MacroContextSnapshot]:
        query = select(MacroContextSnapshotRecord)
        if run_id is not None:
            query = query.where(MacroContextSnapshotRecord.run_id == run_id)
        rows = self.session.scalars(
            query.order_by(MacroContextSnapshotRecord.computed_at.desc()).limit(limit)
        ).all()
        return [self._to_macro_model(row) for row in rows]

    def get_latest_macro_context_snapshot(self) -> MacroContextSnapshot | None:
        record = self.session.scalar(
            select(MacroContextSnapshotRecord).order_by(MacroContextSnapshotRecord.computed_at.desc()).limit(1)
        )
        if record is None:
            return None
        return self._to_macro_model(record)

    def get_macro_context_snapshot(self, snapshot_id: int) -> MacroContextSnapshot | None:
        record = self.session.get(MacroContextSnapshotRecord, snapshot_id)
        if record is None:
            return None
        return self._to_macro_model(record)

    def create_industry_context_snapshot(self, snapshot: IndustryContextSnapshot) -> IndustryContextSnapshot:
        record = IndustryContextSnapshotRecord(
            industry_key=snapshot.industry_key,
            industry_label=snapshot.industry_label,
            computed_at=self._normalize_datetime(snapshot.computed_at),
            expires_at=self._normalize_datetime(snapshot.expires_at) if snapshot.expires_at else None,
            status=snapshot.status,
            summary_text=snapshot.summary_text,
            direction=snapshot.direction,
            saliency_score=snapshot.saliency_score,
            confidence_percent=snapshot.confidence_percent,
            active_drivers_json=self._dump(snapshot.active_drivers),
            linked_macro_themes_json=self._dump(snapshot.linked_macro_themes),
            linked_industry_themes_json=self._dump(snapshot.linked_industry_themes),
            warnings_json=self._dump(snapshot.warnings),
            missing_inputs_json=self._dump(snapshot.missing_inputs),
            source_breakdown_json=self._dump(snapshot.source_breakdown),
            metadata_json=self._dump(snapshot.metadata),
            job_id=snapshot.job_id,
            run_id=snapshot.run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_industry_model(record)

    def list_industry_context_snapshots(
        self,
        industry_key: str | None = None,
        limit: int = 50,
        run_id: int | None = None,
    ) -> list[IndustryContextSnapshot]:
        query = select(IndustryContextSnapshotRecord)
        if industry_key:
            query = query.where(IndustryContextSnapshotRecord.industry_key == industry_key)
        if run_id is not None:
            query = query.where(IndustryContextSnapshotRecord.run_id == run_id)
        rows = self.session.scalars(query.order_by(IndustryContextSnapshotRecord.computed_at.desc()).limit(limit)).all()
        return [self._to_industry_model(row) for row in rows]

    def get_latest_industry_context_snapshot(self, industry_key: str) -> IndustryContextSnapshot | None:
        record = self.session.scalar(
            select(IndustryContextSnapshotRecord)
            .where(IndustryContextSnapshotRecord.industry_key == industry_key)
            .order_by(IndustryContextSnapshotRecord.computed_at.desc())
            .limit(1)
        )
        if record is None:
            return None
        return self._to_industry_model(record)

    def get_industry_context_snapshot(self, snapshot_id: int) -> IndustryContextSnapshot | None:
        record = self.session.get(IndustryContextSnapshotRecord, snapshot_id)
        if record is None:
            return None
        return self._to_industry_model(record)

    def create_ticker_signal_snapshot(self, snapshot: TickerSignalSnapshot) -> TickerSignalSnapshot:
        record = TickerSignalSnapshotRecord(
            ticker=snapshot.ticker,
            horizon=snapshot.horizon.value,
            computed_at=self._normalize_datetime(snapshot.computed_at),
            status=snapshot.status,
            direction=snapshot.direction,
            swing_probability_percent=snapshot.swing_probability_percent,
            confidence_percent=snapshot.confidence_percent,
            attention_score=snapshot.attention_score,
            macro_exposure_score=snapshot.macro_exposure_score,
            industry_alignment_score=snapshot.industry_alignment_score,
            ticker_sentiment_score=snapshot.ticker_sentiment_score,
            technical_setup_score=snapshot.technical_setup_score,
            catalyst_score=snapshot.catalyst_score,
            expected_move_score=snapshot.expected_move_score,
            execution_quality_score=snapshot.execution_quality_score,
            warnings_json=self._dump(snapshot.warnings),
            missing_inputs_json=self._dump(snapshot.missing_inputs),
            source_breakdown_json=self._dump(snapshot.source_breakdown),
            diagnostics_json=self._dump(snapshot.diagnostics),
            job_id=snapshot.job_id,
            run_id=snapshot.run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_ticker_signal_model(record)

    def list_ticker_signal_snapshots(
        self,
        ticker: str | None = None,
        limit: int = 50,
        run_id: int | None = None,
    ) -> list[TickerSignalSnapshot]:
        query = select(TickerSignalSnapshotRecord)
        if ticker:
            query = query.where(TickerSignalSnapshotRecord.ticker == ticker.upper())
        if run_id is not None:
            query = query.where(TickerSignalSnapshotRecord.run_id == run_id)
        rows = self.session.scalars(query.order_by(TickerSignalSnapshotRecord.computed_at.desc()).limit(limit)).all()
        return [self._to_ticker_signal_model(row) for row in rows]

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @classmethod
    def _dump(cls, value: Any) -> str:
        return json.dumps(value, default=cls._json_default)

    @staticmethod
    def _load(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _transmission_bias_detail(self, value: object) -> KeyLabelDetail | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_transmission_bias_definition(value)
        key = str(definition.get("key", value)).strip() or value.strip()
        label = str(definition.get("label", value)).strip() or value.strip()
        return KeyLabelDetail(key=key, label=label)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _to_macro_model(self, record: MacroContextSnapshotRecord) -> MacroContextSnapshot:
        return MacroContextSnapshot(
            id=record.id,
            computed_at=self._normalize_datetime(record.computed_at),
            expires_at=self._normalize_datetime(record.expires_at) if record.expires_at else None,
            status=record.status,
            summary_text=record.summary_text,
            saliency_score=record.saliency_score,
            confidence_percent=record.confidence_percent,
            active_themes=self._load(record.active_themes_json, []),
            regime_tags=self._load(record.regime_tags_json, []),
            warnings=self._load(record.warnings_json, []),
            missing_inputs=self._load(record.missing_inputs_json, []),
            source_breakdown=self._load(record.source_breakdown_json, {}),
            metadata=self._load(record.metadata_json, {}),
            job_id=record.job_id,
            run_id=record.run_id,
        )

    def _to_industry_model(self, record: IndustryContextSnapshotRecord) -> IndustryContextSnapshot:
        return IndustryContextSnapshot(
            id=record.id,
            industry_key=record.industry_key,
            industry_label=record.industry_label,
            computed_at=self._normalize_datetime(record.computed_at),
            expires_at=self._normalize_datetime(record.expires_at) if record.expires_at else None,
            status=record.status,
            summary_text=record.summary_text,
            direction=record.direction,
            saliency_score=record.saliency_score,
            confidence_percent=record.confidence_percent,
            active_drivers=self._load(record.active_drivers_json, []),
            linked_macro_themes=self._load(record.linked_macro_themes_json, []),
            linked_industry_themes=self._load(record.linked_industry_themes_json, []),
            warnings=self._load(record.warnings_json, []),
            missing_inputs=self._load(record.missing_inputs_json, []),
            source_breakdown=self._load(record.source_breakdown_json, {}),
            metadata=self._load(record.metadata_json, {}),
            job_id=record.job_id,
            run_id=record.run_id,
        )

    def _to_ticker_signal_model(self, record: TickerSignalSnapshotRecord) -> TickerSignalSnapshot:
        try:
            horizon = StrategyHorizon(record.horizon)
        except ValueError:
            horizon = StrategyHorizon.ONE_WEEK
        return TickerSignalSnapshot(
            id=record.id,
            ticker=record.ticker,
            horizon=horizon,
            computed_at=self._normalize_datetime(record.computed_at),
            status=record.status,
            direction=record.direction,
            swing_probability_percent=record.swing_probability_percent,
            confidence_percent=record.confidence_percent,
            attention_score=record.attention_score,
            macro_exposure_score=record.macro_exposure_score,
            industry_alignment_score=record.industry_alignment_score,
            ticker_sentiment_score=record.ticker_sentiment_score,
            technical_setup_score=record.technical_setup_score,
            catalyst_score=record.catalyst_score,
            expected_move_score=record.expected_move_score,
            execution_quality_score=record.execution_quality_score,
            warnings=self._load(record.warnings_json, []),
            missing_inputs=self._load(record.missing_inputs_json, []),
            source_breakdown=self._load(record.source_breakdown_json, {}),
            diagnostics=self._load(record.diagnostics_json, {}),
            job_id=record.job_id,
            run_id=record.run_id,
        )
