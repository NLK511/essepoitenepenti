import json
from collections import Counter
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

    def latest_macro_context_snapshots_by_run(self, run_ids: list[int]) -> dict[int, MacroContextSnapshot]:
        wanted = [run_id for run_id in dict.fromkeys(run_ids) if run_id > 0]
        if not wanted:
            return {}
        rows = self.session.scalars(
            select(MacroContextSnapshotRecord)
            .where(MacroContextSnapshotRecord.run_id.in_(wanted))
            .order_by(MacroContextSnapshotRecord.run_id.asc(), MacroContextSnapshotRecord.computed_at.desc())
        ).all()
        snapshots: dict[int, MacroContextSnapshot] = {}
        for row in rows:
            if row.run_id is None or row.run_id in snapshots:
                continue
            snapshots[row.run_id] = self._to_macro_model(row)
            if len(snapshots) == len(wanted):
                break
        return snapshots

    def get_latest_macro_context_snapshot_before(self, as_of: datetime) -> MacroContextSnapshot | None:
        record = self.session.scalar(
            select(MacroContextSnapshotRecord)
            .where(MacroContextSnapshotRecord.computed_at <= self._normalize_datetime(as_of))
            .order_by(MacroContextSnapshotRecord.computed_at.desc())
            .limit(1)
        )
        if record is None:
            return None
        return self._to_macro_model(record)

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

    def latest_industry_context_snapshots_by_run(self, run_ids: list[int]) -> dict[int, IndustryContextSnapshot]:
        wanted = [run_id for run_id in dict.fromkeys(run_ids) if run_id > 0]
        if not wanted:
            return {}
        rows = self.session.scalars(
            select(IndustryContextSnapshotRecord)
            .where(IndustryContextSnapshotRecord.run_id.in_(wanted))
            .order_by(IndustryContextSnapshotRecord.run_id.asc(), IndustryContextSnapshotRecord.computed_at.desc())
        ).all()
        snapshots: dict[int, IndustryContextSnapshot] = {}
        for row in rows:
            if row.run_id is None or row.run_id in snapshots:
                continue
            snapshots[row.run_id] = self._to_industry_model(row)
            if len(snapshots) == len(wanted):
                break
        return snapshots

    def get_latest_industry_context_snapshot_before(self, industry_key: str, as_of: datetime) -> IndustryContextSnapshot | None:
        record = self.session.scalar(
            select(IndustryContextSnapshotRecord)
            .where(IndustryContextSnapshotRecord.industry_key == industry_key)
            .where(IndustryContextSnapshotRecord.computed_at <= self._normalize_datetime(as_of))
            .order_by(IndustryContextSnapshotRecord.computed_at.desc())
            .limit(1)
        )
        if record is None:
            return None
        return self._to_industry_model(record)

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

    def industry_context_summary(self) -> dict[str, Any]:
        rows = self.session.scalars(select(IndustryContextSnapshotRecord)).all()
        status_counts = Counter(str(row.status or "unknown") for row in rows)
        evidence_counts = Counter()
        coverage_counts = Counter()
        quality_counts = Counter()
        neutral_reasons = Counter()
        warnings = Counter()
        missing_inputs = Counter()
        stale_count = 0
        decision_usable_count = 0
        now = datetime.now(timezone.utc)
        for row in rows:
            source_breakdown = self._load(row.source_breakdown_json, {})
            active_drivers = self._load(row.active_drivers_json, [])
            evidence_state = str(source_breakdown.get("evidence_state") or "missing")
            coverage_state = str(source_breakdown.get("coverage_state") or "missing")
            quality_status = str(source_breakdown.get("context_quality_status") or "unknown")
            evidence_counts[evidence_state] += 1
            coverage_counts[coverage_state] += 1
            quality_counts[quality_status] += 1
            if row.expires_at is not None and self._normalize_datetime(row.expires_at) < now:
                stale_count += 1
            if quality_status == "usable" and evidence_state == "usable" and active_drivers:
                decision_usable_count += 1
            if float(row.confidence_percent or 0.0) == 0.0 or not active_drivers or quality_status != "usable":
                reason = self._industry_neutral_reason(source_breakdown, active_drivers, quality_status, evidence_state, coverage_state)
                neutral_reasons[reason] += 1
            for warning in self._load(row.warnings_json, []):
                if isinstance(warning, str) and warning.strip():
                    warnings[warning.strip()] += 1
            for input_name in self._load(row.missing_inputs_json, []):
                if isinstance(input_name, str) and input_name.strip():
                    missing_inputs[input_name.strip()] += 1
        active_driver_count = sum(1 for row in rows if self._load(row.active_drivers_json, []))
        zero_confidence_count = sum(1 for row in rows if float(row.confidence_percent or 0.0) == 0.0)
        total = len(rows)
        return {
            "total_count": total,
            "status_counts": dict(status_counts),
            "evidence_state_counts": dict(evidence_counts),
            "coverage_state_counts": dict(coverage_counts),
            "quality_status_counts": dict(quality_counts),
            "active_driver_count": active_driver_count,
            "empty_driver_count": total - active_driver_count,
            "zero_confidence_count": zero_confidence_count,
            "stale_count": stale_count,
            "decision_usable_count": decision_usable_count,
            "decision_usable_rate_percent": round((decision_usable_count / total * 100.0) if total else 0.0, 1),
            "usable_rate_percent": round((quality_counts.get("usable", 0) / total * 100.0) if total else 0.0, 1),
            "active_driver_rate_percent": round((active_driver_count / total * 100.0) if total else 0.0, 1),
            "warning_count": sum(status_counts.values()) - status_counts.get("ok", 0),
            "neutral_reason_counts": dict(neutral_reasons),
            "top_neutral_reasons": neutral_reasons.most_common(5),
            "top_warnings": warnings.most_common(5),
            "top_missing_inputs": missing_inputs.most_common(5),
        }

    @staticmethod
    def _industry_neutral_reason(
        source_breakdown: dict[str, Any],
        active_drivers: list[Any],
        quality_status: str,
        evidence_state: str,
        coverage_state: str,
    ) -> str:
        if quality_status in {"blocked", "failed"}:
            return "context_quality_blocked"
        if quality_status in {"degraded", "partial"}:
            return "context_quality_degraded"
        if evidence_state in {"missing", "missing_snapshot"}:
            return "missing_industry_evidence"
        if coverage_state == "missing":
            return "missing_industry_coverage"
        if not active_drivers:
            return "no_salient_industry_drivers"
        for reason in source_breakdown.get("score_reasons") or []:
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
        return "true_neutral_or_balanced_context"

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
        snapshot_id: int | None = None,
        computed_after: datetime | None = None,
    ) -> list[TickerSignalSnapshot]:
        query = select(TickerSignalSnapshotRecord)
        if snapshot_id is not None:
            query = query.where(TickerSignalSnapshotRecord.id == snapshot_id)
        if ticker:
            query = query.where(TickerSignalSnapshotRecord.ticker == ticker.upper())
        if run_id is not None:
            query = query.where(TickerSignalSnapshotRecord.run_id == run_id)
        if computed_after is not None:
            query = query.where(TickerSignalSnapshotRecord.computed_at >= self._normalize_datetime(computed_after))
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
