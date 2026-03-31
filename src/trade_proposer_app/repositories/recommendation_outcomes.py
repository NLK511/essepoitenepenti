import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import KeyLabelDetail, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import RecommendationOutcomeRecord, RecommendationPlanRecord
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationOutcomeRepository:
    def __init__(self, session: Session, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.session = session
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def upsert_outcome(self, outcome: RecommendationPlanOutcome) -> RecommendationPlanOutcome:
        self.session.rollback()
        try:
            record = self.session.scalar(
                select(RecommendationOutcomeRecord).where(
                    RecommendationOutcomeRecord.recommendation_plan_id == outcome.recommendation_plan_id
                )
            )
            if record is None:
                record = RecommendationOutcomeRecord(recommendation_plan_id=outcome.recommendation_plan_id)
                self.session.add(record)
            self._apply_outcome(record, outcome)
            self.session.commit()
            self.session.refresh(record)
            return self._to_model(record)
        except IntegrityError:
            self.session.rollback()
            record = self.session.scalar(
                select(RecommendationOutcomeRecord).where(
                    RecommendationOutcomeRecord.recommendation_plan_id == outcome.recommendation_plan_id
                )
            )
            if record is None:
                raise
            self._apply_outcome(record, outcome)
            self.session.commit()
            self.session.refresh(record)
            return self._to_model(record)

    def list_outcomes(
        self,
        *,
        ticker: str | None = None,
        outcome: str | None = None,
        recommendation_plan_id: int | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationPlanOutcome]:
        self.session.rollback()
        query = select(RecommendationOutcomeRecord, RecommendationPlanRecord).join(
            RecommendationPlanRecord,
            RecommendationOutcomeRecord.recommendation_plan_id == RecommendationPlanRecord.id,
        )
        if ticker:
            query = query.where(RecommendationPlanRecord.ticker == ticker.upper())
        if outcome:
            query = query.where(RecommendationOutcomeRecord.outcome == outcome)
        if recommendation_plan_id is not None:
            query = query.where(RecommendationOutcomeRecord.recommendation_plan_id == recommendation_plan_id)
        if run_id is not None:
            query = query.where(RecommendationOutcomeRecord.run_id == run_id)
        if setup_family:
            query = query.where(RecommendationOutcomeRecord.setup_family == setup_family)
        rows = self.session.execute(
            query.order_by(RecommendationOutcomeRecord.evaluated_at.desc()).limit(limit)
        ).all()
        return [self._to_joined_model(outcome_record, plan_record) for outcome_record, plan_record in rows]

    def get_outcomes_by_plan_ids(self, plan_ids: list[int]) -> dict[int, RecommendationPlanOutcome]:
        self.session.rollback()
        normalized = [plan_id for plan_id in plan_ids if isinstance(plan_id, int)]
        if not normalized:
            return {}
        rows = self.session.execute(
            select(RecommendationOutcomeRecord, RecommendationPlanRecord)
            .join(RecommendationPlanRecord, RecommendationOutcomeRecord.recommendation_plan_id == RecommendationPlanRecord.id)
            .where(RecommendationOutcomeRecord.recommendation_plan_id.in_(normalized))
        ).all()
        return {
            outcome_record.recommendation_plan_id: self._to_joined_model(outcome_record, plan_record)
            for outcome_record, plan_record in rows
        }

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _apply_outcome(self, record: RecommendationOutcomeRecord, outcome: RecommendationPlanOutcome) -> None:
        record.outcome = outcome.outcome
        record.status = outcome.status
        record.evaluated_at = self._normalize_datetime(outcome.evaluated_at)
        record.entry_touched = outcome.entry_touched
        record.stop_loss_hit = outcome.stop_loss_hit
        record.take_profit_hit = outcome.take_profit_hit
        record.horizon_return_1d = outcome.horizon_return_1d
        record.horizon_return_3d = outcome.horizon_return_3d
        record.horizon_return_5d = outcome.horizon_return_5d
        record.max_favorable_excursion = outcome.max_favorable_excursion
        record.max_adverse_excursion = outcome.max_adverse_excursion
        record.realized_holding_period_days = outcome.realized_holding_period_days
        record.direction_correct = outcome.direction_correct
        record.confidence_bucket = outcome.confidence_bucket
        record.setup_family = outcome.setup_family
        record.notes = outcome.notes
        record.run_id = outcome.run_id

    def _to_model(self, record: RecommendationOutcomeRecord) -> RecommendationPlanOutcome:
        return RecommendationPlanOutcome(
            id=record.id,
            recommendation_plan_id=record.recommendation_plan_id,
            outcome=record.outcome,
            status=record.status,
            evaluated_at=self._normalize_datetime(record.evaluated_at),
            entry_touched=record.entry_touched,
            stop_loss_hit=record.stop_loss_hit,
            take_profit_hit=record.take_profit_hit,
            horizon_return_1d=record.horizon_return_1d,
            horizon_return_3d=record.horizon_return_3d,
            horizon_return_5d=record.horizon_return_5d,
            max_favorable_excursion=record.max_favorable_excursion,
            max_adverse_excursion=record.max_adverse_excursion,
            realized_holding_period_days=record.realized_holding_period_days,
            direction_correct=record.direction_correct,
            confidence_bucket=record.confidence_bucket,
            setup_family=record.setup_family,
            notes=record.notes,
            run_id=record.run_id,
        )

    def _to_joined_model(
        self,
        record: RecommendationOutcomeRecord,
        plan_record: RecommendationPlanRecord,
    ) -> RecommendationPlanOutcome:
        model = self._to_model(record)
        model.ticker = plan_record.ticker
        model.action = plan_record.action
        model.horizon = plan_record.horizon
        transmission_summary = self._transmission_summary(plan_record)
        model.transmission_bias = self.taxonomy_service.derive_transmission_bias(transmission_summary)
        transmission_bias_definition = self.taxonomy_service.get_transmission_bias_definition(model.transmission_bias)
        model.transmission_bias_label = transmission_bias_definition.get("label", model.transmission_bias)
        model.transmission_bias_detail = KeyLabelDetail(
            key=str(transmission_bias_definition.get("key", model.transmission_bias)).strip() or str(model.transmission_bias or "unknown"),
            label=str(transmission_bias_definition.get("label", model.transmission_bias)).strip() or str(model.transmission_bias or "unknown"),
        )
        model.context_regime = self._context_regime(transmission_summary)
        context_regime_definition = self.taxonomy_service.get_transmission_context_regime_definition(model.context_regime)
        model.context_regime_label = context_regime_definition.get("label", model.context_regime)
        model.context_regime_detail = KeyLabelDetail(
            key=str(context_regime_definition.get("key", model.context_regime)).strip() or str(model.context_regime or "mixed_context"),
            label=str(context_regime_definition.get("label", model.context_regime)).strip() or str(model.context_regime or "mixed_context"),
        )
        return model

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _transmission_summary(self, plan_record: RecommendationPlanRecord) -> dict[str, object]:
        signal_breakdown = self._load_json(plan_record.signal_breakdown_json)
        evidence_summary = self._load_json(plan_record.evidence_summary_json)
        candidate = signal_breakdown.get("transmission_summary")
        if isinstance(candidate, dict):
            return candidate
        candidate = evidence_summary.get("transmission_summary")
        return candidate if isinstance(candidate, dict) else {}

    @staticmethod
    def _string_value(value: object, *, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    def _context_regime(self, transmission_summary: dict[str, object]) -> str:
        return self.taxonomy_service.derive_transmission_context_regime(transmission_summary)
