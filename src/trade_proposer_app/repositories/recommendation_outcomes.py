from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import RecommendationPlanOutcome
from trade_proposer_app.persistence.models import RecommendationOutcomeRecord, RecommendationPlanRecord


class RecommendationOutcomeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_outcome(self, outcome: RecommendationPlanOutcome) -> RecommendationPlanOutcome:
        record = self.session.scalar(
            select(RecommendationOutcomeRecord).where(
                RecommendationOutcomeRecord.recommendation_plan_id == outcome.recommendation_plan_id
            )
        )
        if record is None:
            record = RecommendationOutcomeRecord(recommendation_plan_id=outcome.recommendation_plan_id)
            self.session.add(record)
        record.outcome = outcome.outcome
        record.status = outcome.status
        record.evaluated_at = outcome.evaluated_at
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
        limit: int = 50,
    ) -> list[RecommendationPlanOutcome]:
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
        rows = self.session.execute(
            query.order_by(RecommendationOutcomeRecord.evaluated_at.desc()).limit(limit)
        ).all()
        return [self._to_joined_model(outcome_record, plan_record) for outcome_record, plan_record in rows]

    def get_outcomes_by_plan_ids(self, plan_ids: list[int]) -> dict[int, RecommendationPlanOutcome]:
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
    def _to_model(record: RecommendationOutcomeRecord) -> RecommendationPlanOutcome:
        return RecommendationPlanOutcome(
            id=record.id,
            recommendation_plan_id=record.recommendation_plan_id,
            outcome=record.outcome,
            status=record.status,
            evaluated_at=record.evaluated_at,
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
        return model
