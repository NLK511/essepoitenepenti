import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_plan_baselines import RecommendationPlanBaselineService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class RecommendationPlanBaselineServiceTests(unittest.TestCase):
    def test_summarize_compares_actionable_cohorts_against_simple_baselines(self) -> None:
        session = create_session()
        plans = RecommendationPlanRepository(session)
        outcomes = RecommendationOutcomeRepository(session)

        aapl = plans.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=78.0,
                computed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "continuation", "attention_score": 82.0},
            )
        )
        msft = plans.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="short",
                confidence_percent=68.0,
                computed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "breakdown", "attention_score": 74.0},
            )
        )
        tsla = plans.create_plan(
            RecommendationPlan(
                ticker="TSLA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=61.0,
                computed_at=datetime(2024, 1, 3, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "catalyst_follow_through", "attention_score": 71.0},
            )
        )
        plans.create_plan(
            RecommendationPlan(
                ticker="NVDA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="no_action",
                confidence_percent=44.0,
                computed_at=datetime(2024, 1, 4, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "no_action", "attention_score": 40.0},
            )
        )

        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=aapl.id or 0,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                horizon_return_5d=4.0,
                confidence_bucket="65_to_79",
                setup_family="continuation",
            )
        )
        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=msft.id or 0,
                ticker="MSFT",
                action="short",
                outcome="loss",
                status="resolved",
                horizon_return_5d=-2.0,
                confidence_bucket="65_to_79",
                setup_family="breakdown",
            )
        )
        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=tsla.id or 0,
                ticker="TSLA",
                action="long",
                outcome="open",
                status="open",
                horizon_return_5d=1.0,
                confidence_bucket="50_to_64",
                setup_family="catalyst_follow_through",
            )
        )

        summary = RecommendationPlanBaselineService(plans).summarize(limit=20)

        self.assertEqual(summary.total_plans_reviewed, 4)
        self.assertEqual(summary.total_trade_plans_reviewed, 3)
        comparison_map = {item.key: item for item in summary.comparisons}
        self.assertEqual(comparison_map["actual_actionable"].trade_plan_count, 3)
        self.assertEqual(comparison_map["actual_actionable"].resolved_trade_count, 2)
        self.assertEqual(comparison_map["actual_actionable"].win_rate_percent, 50.0)
        self.assertEqual(comparison_map["high_confidence_only"].trade_plan_count, 1)
        self.assertEqual(comparison_map["cheap_scan_attention_leaders"].trade_plan_count, 3)
        self.assertEqual(comparison_map["momentum_setup_lane"].resolved_trade_count, 2)
        self.assertEqual(comparison_map["event_setup_lane"].trade_plan_count, 1)
        self.assertEqual(comparison_map["event_setup_lane"].open_trade_count, 1)
        family_map = {item.key: item for item in summary.family_cohorts}
        self.assertEqual(family_map["family__continuation"].resolved_trade_count, 1)
        self.assertEqual(family_map["family__continuation"].win_rate_percent, 100.0)
        self.assertEqual(family_map["family__breakdown"].resolved_trade_count, 1)
        self.assertEqual(family_map["family__breakdown"].win_rate_percent, 0.0)
        self.assertEqual(family_map["family__mean_reversion"].trade_plan_count, 0)
        self.assertEqual(family_map["family__catalyst_follow_through"].open_trade_count, 1)

        session.close()

    def test_expired_trade_plans_are_not_counted_as_open(self) -> None:
        session = create_session()
        plans = RecommendationPlanRepository(session)
        outcomes = RecommendationOutcomeRepository(session)

        plan = plans.create_plan(
            RecommendationPlan(
                ticker="NVDA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                computed_at=datetime(2024, 1, 5, tzinfo=timezone.utc),
                signal_breakdown={"setup_family": "breakout", "attention_score": 76.0},
            )
        )

        outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="NVDA",
                action="long",
                outcome="expired",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="breakout",
            )
        )

        summary = RecommendationPlanBaselineService(plans).summarize(limit=20)
        comparison_map = {item.key: item for item in summary.comparisons}

        self.assertEqual(comparison_map["actual_actionable"].trade_plan_count, 1)
        self.assertEqual(comparison_map["actual_actionable"].resolved_trade_count, 0)
        self.assertEqual(comparison_map["actual_actionable"].open_trade_count, 0)

        session.close()


if __name__ == "__main__":
    unittest.main()
