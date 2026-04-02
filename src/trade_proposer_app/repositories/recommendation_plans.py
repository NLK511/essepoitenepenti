import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import KeyLabelDetail, RecommendationPlan
from trade_proposer_app.persistence.models import RecommendationPlanRecord
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from datetime import datetime, timezone

from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class RecommendationPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.outcomes = RecommendationOutcomeRepository(session)
        self.taxonomy_service = TickerTaxonomyService()

    def create_plan(self, plan: RecommendationPlan) -> RecommendationPlan:
        record = RecommendationPlanRecord(
            ticker=plan.ticker,
            horizon=plan.horizon.value,
            action=plan.action,
            status=plan.status,
            confidence_percent=plan.confidence_percent,
            entry_price_low=plan.entry_price_low,
            entry_price_high=plan.entry_price_high,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            holding_period_days=plan.holding_period_days,
            risk_reward_ratio=plan.risk_reward_ratio,
            thesis_summary=plan.thesis_summary,
            rationale_summary=plan.rationale_summary,
            risks_json=self._dump(plan.risks),
            warnings_json=self._dump(plan.warnings),
            missing_inputs_json=self._dump(plan.missing_inputs),
            evidence_summary_json=self._dump(plan.evidence_summary),
            signal_breakdown_json=self._dump(plan.signal_breakdown),
            computed_at=self._normalize_datetime(plan.computed_at),
            watchlist_id=plan.watchlist_id,
            ticker_signal_snapshot_id=plan.ticker_signal_snapshot_id,
            job_id=plan.job_id,
            run_id=plan.run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def get_plan(self, plan_id: int) -> RecommendationPlan:
        record = self.session.get(RecommendationPlanRecord, plan_id)
        if record is None:
            raise ValueError(f"Recommendation plan {plan_id} not found")
        plan = self._to_model(record)
        outcome_map = self.outcomes.get_outcomes_by_plan_ids([record.id])
        plan.latest_outcome = outcome_map.get(record.id)
        return plan

    def _base_plan_query(
        self,
        ticker: str | None = None,
        action: str | None = None,
        run_id: int | None = None,
        plan_id: int | None = None,
    ):
        query = select(RecommendationPlanRecord)
        if ticker:
            query = query.where(RecommendationPlanRecord.ticker == ticker.upper())
        if action:
            query = query.where(RecommendationPlanRecord.action == action)
        if run_id is not None:
            query = query.where(RecommendationPlanRecord.run_id == run_id)
        if plan_id is not None:
            query = query.where(RecommendationPlanRecord.id == plan_id)
        return query

    def _record_setup_family(self, record: RecommendationPlanRecord) -> str:
        signal_breakdown = self._load(record.signal_breakdown_json, {})
        if not isinstance(signal_breakdown, dict):
            return ""
        return str(signal_breakdown.get("setup_family") or "").strip().lower()

    def count_plans(
        self,
        ticker: str | None = None,
        action: str | None = None,
        run_id: int | None = None,
        setup_family: str | None = None,
        plan_id: int | None = None,
    ) -> int:
        query = self._base_plan_query(ticker=ticker, action=action, run_id=run_id, plan_id=plan_id)
        if setup_family:
            rows = self.session.scalars(query).all()
            normalized_setup_family = setup_family.strip().lower()
            return sum(1 for row in rows if self._record_setup_family(row) == normalized_setup_family)
        count_query = select(func.count()).select_from(query.subquery())
        return int(self.session.scalar(count_query) or 0)

    def list_plans(
        self,
        ticker: str | None = None,
        action: str | None = None,
        limit: int = 50,
        offset: int = 0,
        run_id: int | None = None,
        setup_family: str | None = None,
        plan_id: int | None = None,
    ) -> list[RecommendationPlan]:
        normalized_limit = max(1, limit)
        normalized_offset = max(0, offset)
        query = self._base_plan_query(ticker=ticker, action=action, run_id=run_id, plan_id=plan_id)
        if setup_family:
            rows = self.session.scalars(query.order_by(RecommendationPlanRecord.computed_at.desc())).all()
            normalized_setup_family = setup_family.strip().lower()
            plans = [
                self._to_model(row)
                for row in rows
                if self._record_setup_family(row) == normalized_setup_family
            ]
            plans = plans[normalized_offset : normalized_offset + normalized_limit]
        else:
            rows = self.session.scalars(
                query.order_by(RecommendationPlanRecord.computed_at.desc()).offset(normalized_offset).limit(normalized_limit)
            ).all()
            plans = [self._to_model(row) for row in rows]
        outcome_map = self.outcomes.get_outcomes_by_plan_ids([plan.id for plan in plans if plan.id is not None])
        for plan in plans:
            if plan.id is not None:
                plan.latest_outcome = outcome_map.get(plan.id)
        return plans

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

    def _to_model(self, record: RecommendationPlanRecord) -> RecommendationPlan:
        try:
            horizon = StrategyHorizon(record.horizon)
        except ValueError:
            horizon = StrategyHorizon.ONE_WEEK
        return RecommendationPlan(
            id=record.id,
            ticker=record.ticker,
            horizon=horizon,
            action=record.action,
            status=record.status,
            confidence_percent=record.confidence_percent,
            entry_price_low=record.entry_price_low,
            entry_price_high=record.entry_price_high,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            holding_period_days=record.holding_period_days,
            risk_reward_ratio=record.risk_reward_ratio,
            thesis_summary=record.thesis_summary,
            rationale_summary=record.rationale_summary,
            risks=self._load(record.risks_json, []),
            warnings=self._load(record.warnings_json, []),
            missing_inputs=self._load(record.missing_inputs_json, []),
            evidence_summary=self._load(record.evidence_summary_json, {}),
            signal_breakdown=self._load(record.signal_breakdown_json, {}),
            computed_at=self._normalize_datetime(record.computed_at),
            run_id=record.run_id,
            job_id=record.job_id,
            watchlist_id=record.watchlist_id,
            ticker_signal_snapshot_id=record.ticker_signal_snapshot_id,
        )
