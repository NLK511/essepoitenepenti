import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_setup_family_reviews import RecommendationSetupFamilyReviewService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class RecommendationSetupFamilyReviewServiceTests(unittest.TestCase):
    def test_summarize_groups_family_specific_slices(self) -> None:
        session = create_session()
        plans = RecommendationPlanRepository(session)
        outcomes = RecommendationOutcomeRepository(session)

        breakout_plan = plans.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=75.0,
                computed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "breakout", "transmission_summary": {"context_bias": "tailwind", "transmission_tags": ["macro_dominant", "catalyst_active"]}},
            )
        )
        continuation_plan = plans.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=71.0,
                computed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "continuation", "transmission_summary": {"context_bias": "headwind", "transmission_tags": ["industry_dominant"]}},
            )
        )
        mean_reversion_plan = plans.create_plan(
            RecommendationPlan(
                ticker="TSLA",
                horizon=StrategyHorizon.ONE_DAY,
                action="short",
                confidence_percent=63.0,
                computed_at=datetime(2024, 1, 3, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "mean_reversion", "transmission_summary": {"context_bias": "mixed", "transmission_tags": []}},
            )
        )

        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=breakout_plan.id or 0,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                horizon=StrategyHorizon.ONE_WEEK.value,
                setup_family="breakout",
                transmission_bias="tailwind",
                context_regime="context_plus_catalyst",
                horizon_return_5d=5.0,
                max_favorable_excursion=7.0,
                max_adverse_excursion=-1.5,
            )
        )
        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=continuation_plan.id or 0,
                ticker="MSFT",
                action="long",
                outcome="loss",
                status="resolved",
                horizon=StrategyHorizon.ONE_WEEK.value,
                setup_family="continuation",
                transmission_bias="headwind",
                context_regime="industry_dominant",
                horizon_return_5d=-2.0,
                max_favorable_excursion=1.5,
                max_adverse_excursion=-4.0,
            )
        )
        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=mean_reversion_plan.id or 0,
                ticker="TSLA",
                action="short",
                outcome="open",
                status="open",
                horizon=StrategyHorizon.ONE_DAY.value,
                setup_family="mean_reversion",
                transmission_bias="mixed",
                context_regime="mixed_context",
                horizon_return_5d=1.0,
            )
        )

        summary = RecommendationSetupFamilyReviewService(outcomes).summarize(limit=20)

        self.assertEqual(summary.total_outcomes_reviewed, 3)
        family_map = {item.family: item for item in summary.families}
        self.assertEqual(family_map["breakout"].resolved_outcomes, 1)
        self.assertEqual(family_map["breakout"].overall_win_rate_percent, 100.0)
        self.assertEqual(family_map["breakout"].by_horizon[0].key, "1w")
        self.assertEqual(family_map["breakout"].by_transmission_bias[0].key, "tailwind")
        self.assertEqual(family_map["breakout"].by_context_regime[0].key, "context_plus_catalyst")
        self.assertEqual(family_map["continuation"].loss_outcomes, 1)
        self.assertEqual(family_map["mean_reversion"].open_outcomes, 1)
        self.assertEqual(family_map["mean_reversion"].resolved_outcomes, 0)
        self.assertEqual(family_map["breakdown"].total_outcomes, 0)

        filtered = RecommendationSetupFamilyReviewService(outcomes).summarize(setup_family="breakout", limit=20)
        self.assertEqual(len(filtered.families), 1)
        self.assertEqual(filtered.families[0].family, "breakout")
        self.assertEqual(filtered.families[0].total_outcomes, 1)

        session.close()


if __name__ == "__main__":
    unittest.main()
