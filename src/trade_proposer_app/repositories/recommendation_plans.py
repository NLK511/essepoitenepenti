import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.persistence.models import RecommendationPlanRecord


class RecommendationPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

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
            computed_at=plan.computed_at,
            watchlist_id=plan.watchlist_id,
            ticker_signal_snapshot_id=plan.ticker_signal_snapshot_id,
            job_id=plan.job_id,
            run_id=plan.run_id,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_plans(
        self,
        ticker: str | None = None,
        action: str | None = None,
        limit: int = 50,
        run_id: int | None = None,
    ) -> list[RecommendationPlan]:
        query = select(RecommendationPlanRecord)
        if ticker:
            query = query.where(RecommendationPlanRecord.ticker == ticker.upper())
        if action:
            query = query.where(RecommendationPlanRecord.action == action)
        if run_id is not None:
            query = query.where(RecommendationPlanRecord.run_id == run_id)
        rows = self.session.scalars(query.order_by(RecommendationPlanRecord.computed_at.desc()).limit(limit)).all()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value)

    @staticmethod
    def _load(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

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
            computed_at=record.computed_at,
            run_id=record.run_id,
            job_id=record.job_id,
            watchlist_id=record.watchlist_id,
            ticker_signal_snapshot_id=record.ticker_signal_snapshot_id,
        )
