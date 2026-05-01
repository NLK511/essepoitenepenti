from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import KeyLabelDetail, RecommendationPlanOutcome
from trade_proposer_app.domain.statuses import BROKER_RESOLVED_POSITION_STATUSES, OutcomeStatus, TradeOutcome
from trade_proposer_app.persistence.models import BrokerPositionRecord, RecommendationOutcomeRecord, RecommendationPlanRecord
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class EffectivePlanOutcomeRepository:
    """Canonical broker-preferred outcome view for recommendation plans."""

    BROKER_RESOLVED = BROKER_RESOLVED_POSITION_STATUSES

    def __init__(self, session: Session, taxonomy_service: TickerTaxonomyService | None = None) -> None:
        self.session = session
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def list_outcomes(
        self,
        *,
        ticker: str | None = None,
        outcome: str | None = None,
        recommendation_plan_id: int | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        resolved: str | None = None,
        entry_touched: bool | None = None,
        near_entry_miss: bool | None = None,
        direction_worked_without_entry: bool | None = None,
        evaluated_after: datetime | None = None,
        evaluated_before: datetime | None = None,
        limit: int = 50,
    ) -> list[RecommendationPlanOutcome]:
        self.session.rollback()
        query = select(RecommendationPlanRecord)
        if ticker:
            query = query.where(RecommendationPlanRecord.ticker == ticker.upper())
        if recommendation_plan_id is not None:
            query = query.where(RecommendationPlanRecord.id == recommendation_plan_id)
        if run_id is not None:
            query = query.where(RecommendationPlanRecord.run_id == run_id)
        plans = self.session.scalars(query.order_by(RecommendationPlanRecord.computed_at.desc()).limit(max(limit * 5, limit))).all()
        if not plans:
            return []
        plan_ids = [int(plan.id) for plan in plans if plan.id is not None]
        broker_by_plan = self._broker_positions_by_plan(plan_ids)
        simulated_by_plan = self._simulated_outcomes_by_plan(plan_ids)
        results: list[RecommendationPlanOutcome] = []
        for plan in plans:
            if plan.id is None:
                continue
            item = self._effective_for_plan(plan, broker_by_plan.get(int(plan.id), []), simulated_by_plan.get(int(plan.id)))
            if outcome and item.outcome != outcome:
                continue
            if setup_family and item.setup_family != setup_family:
                continue
            if resolved == "resolved" and item.status != "resolved":
                continue
            if resolved == "unresolved" and item.status == "resolved":
                continue
            if entry_touched is not None and item.entry_touched is not entry_touched:
                continue
            if near_entry_miss is not None and item.near_entry_miss is not near_entry_miss:
                continue
            if direction_worked_without_entry is not None and item.direction_worked_without_entry is not direction_worked_without_entry:
                continue
            if evaluated_after is not None and self._normalize_datetime(item.evaluated_at) < self._normalize_datetime(evaluated_after):
                continue
            if evaluated_before is not None and self._normalize_datetime(item.evaluated_at) > self._normalize_datetime(evaluated_before):
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def get_outcomes_by_plan_ids(self, plan_ids: list[int]) -> dict[int, RecommendationPlanOutcome]:
        self.session.rollback()
        normalized = [plan_id for plan_id in plan_ids if isinstance(plan_id, int)]
        if not normalized:
            return {}
        plans = self.session.scalars(select(RecommendationPlanRecord).where(RecommendationPlanRecord.id.in_(normalized))).all()
        broker_by_plan = self._broker_positions_by_plan(normalized)
        simulated_by_plan = self._simulated_outcomes_by_plan(normalized)
        return {
            int(plan.id): self._effective_for_plan(plan, broker_by_plan.get(int(plan.id), []), simulated_by_plan.get(int(plan.id)))
            for plan in plans
            if plan.id is not None
        }

    def _broker_positions_by_plan(self, plan_ids: list[int]) -> dict[int, list[BrokerPositionRecord]]:
        rows = self.session.scalars(
            select(BrokerPositionRecord)
            .where(BrokerPositionRecord.recommendation_plan_id.in_(plan_ids))
            .order_by(BrokerPositionRecord.updated_at.desc())
        ).all()
        grouped: dict[int, list[BrokerPositionRecord]] = {}
        for row in rows:
            grouped.setdefault(int(row.recommendation_plan_id), []).append(row)
        return grouped

    def _simulated_outcomes_by_plan(self, plan_ids: list[int]) -> dict[int, RecommendationOutcomeRecord]:
        rows = self.session.scalars(select(RecommendationOutcomeRecord).where(RecommendationOutcomeRecord.recommendation_plan_id.in_(plan_ids))).all()
        return {int(row.recommendation_plan_id): row for row in rows}

    def _effective_for_plan(
        self,
        plan: RecommendationPlanRecord,
        broker_positions: list[BrokerPositionRecord],
        simulated: RecommendationOutcomeRecord | None,
    ) -> RecommendationPlanOutcome:
        broker = self._preferred_broker_position(broker_positions)
        if broker is not None:
            return self._from_broker(plan, broker)
        if simulated is not None:
            return self._from_simulation(plan, simulated)
        return self._from_plan(plan)

    def _preferred_broker_position(self, positions: list[BrokerPositionRecord]) -> BrokerPositionRecord | None:
        closed = [position for position in positions if position.status in self.BROKER_RESOLVED]
        if closed:
            return sorted(closed, key=lambda item: item.exit_filled_at or item.updated_at or datetime.min, reverse=True)[0]
        return positions[0] if positions else None

    def _from_broker(self, plan: RecommendationPlanRecord, broker: BrokerPositionRecord) -> RecommendationPlanOutcome:
        outcome = broker.status if broker.status in self.BROKER_RESOLVED else TradeOutcome.OPEN.value
        model = self._base_model(plan, outcome=outcome, status=OutcomeStatus.RESOLVED.value if outcome in self.BROKER_RESOLVED else broker.status, evaluated_at=broker.exit_filled_at or broker.updated_at or plan.computed_at)
        model.outcome_source = "broker"
        model.broker_position_id = broker.id
        model.realized_pnl = broker.realized_pnl
        model.realized_return_pct = broker.realized_return_pct
        model.realized_r_multiple = broker.realized_r_multiple
        model.horizon_return_1d = broker.realized_return_pct
        model.horizon_return_3d = broker.realized_return_pct
        model.horizon_return_5d = broker.realized_return_pct
        return model

    def _from_simulation(self, plan: RecommendationPlanRecord, record: RecommendationOutcomeRecord) -> RecommendationPlanOutcome:
        model = self._base_model(plan, outcome=record.outcome, status=record.status, evaluated_at=record.evaluated_at)
        model.id = record.id
        model.outcome_source = "simulation"
        model.entry_touched = record.entry_touched
        model.stop_loss_hit = record.stop_loss_hit
        model.take_profit_hit = record.take_profit_hit
        model.horizon_return_1d = record.horizon_return_1d
        model.horizon_return_3d = record.horizon_return_3d
        model.horizon_return_5d = record.horizon_return_5d
        model.entry_miss_distance_percent = record.entry_miss_distance_percent
        model.near_entry_miss = record.near_entry_miss
        model.direction_worked_without_entry = record.direction_worked_without_entry
        model.max_favorable_excursion = record.max_favorable_excursion
        model.max_adverse_excursion = record.max_adverse_excursion
        model.realized_holding_period_days = record.realized_holding_period_days
        model.direction_correct = record.direction_correct
        model.confidence_bucket = record.confidence_bucket or self._confidence_bucket(plan.confidence_percent)
        model.setup_family = record.setup_family or self._record_setup_family(plan)
        model.notes = record.notes
        return model

    def _from_plan(self, plan: RecommendationPlanRecord) -> RecommendationPlanOutcome:
        model = self._base_model(plan, outcome=TradeOutcome.OPEN.value, status=OutcomeStatus.OPEN.value, evaluated_at=plan.computed_at)
        model.outcome_source = "plan"
        return model

    def _base_model(self, plan: RecommendationPlanRecord, *, outcome: str, status: str, evaluated_at: datetime) -> RecommendationPlanOutcome:
        model = RecommendationPlanOutcome(
            recommendation_plan_id=int(plan.id or 0),
            ticker=plan.ticker,
            action=plan.action,
            outcome=outcome,
            status=status,
            evaluated_at=self._normalize_datetime(evaluated_at),
            confidence_percent=plan.confidence_percent,
            confidence_bucket=self._confidence_bucket(plan.confidence_percent),
            setup_family=self._record_setup_family(plan),
            horizon=plan.horizon,
            run_id=plan.run_id,
        )
        transmission_summary = self._transmission_summary(plan)
        model.transmission_bias = self.taxonomy_service.derive_transmission_bias(transmission_summary)
        transmission_bias_definition = self.taxonomy_service.get_transmission_bias_definition(model.transmission_bias)
        model.transmission_bias_label = transmission_bias_definition.get("label", model.transmission_bias)
        model.transmission_bias_detail = KeyLabelDetail(key=str(transmission_bias_definition.get("key", model.transmission_bias)).strip() or str(model.transmission_bias or "unknown"), label=str(transmission_bias_definition.get("label", model.transmission_bias)).strip() or str(model.transmission_bias or "unknown"))
        model.context_regime = self.taxonomy_service.derive_transmission_context_regime(transmission_summary)
        context_regime_definition = self.taxonomy_service.get_transmission_context_regime_definition(model.context_regime)
        model.context_regime_label = context_regime_definition.get("label", model.context_regime)
        model.context_regime_detail = KeyLabelDetail(key=str(context_regime_definition.get("key", model.context_regime)).strip() or str(model.context_regime or "mixed_context"), label=str(context_regime_definition.get("label", model.context_regime)).strip() or str(model.context_regime or "mixed_context"))
        return model

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _confidence_bucket(confidence: float | None) -> str:
        if confidence is None:
            return "unknown"
        if confidence < 50:
            return "below_50"
        if confidence < 65:
            return "50_to_64"
        if confidence < 80:
            return "65_to_79"
        return "80_plus"

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, object]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _record_setup_family(self, record: RecommendationPlanRecord) -> str:
        signal_breakdown = self._load_json(record.signal_breakdown_json)
        value = signal_breakdown.get("setup_family")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        evidence_summary = self._load_json(record.evidence_summary_json)
        value = evidence_summary.get("setup_family")
        return value.strip().lower() if isinstance(value, str) and value.strip() else "uncategorized"

    def _transmission_summary(self, plan_record: RecommendationPlanRecord) -> dict[str, object]:
        signal_breakdown = self._load_json(plan_record.signal_breakdown_json)
        evidence_summary = self._load_json(plan_record.evidence_summary_json)
        candidate = signal_breakdown.get("transmission_summary")
        if isinstance(candidate, dict):
            return candidate
        candidate = evidence_summary.get("transmission_summary")
        return candidate if isinstance(candidate, dict) else {}
