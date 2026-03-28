import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_plan_evaluations import RecommendationPlanEvaluationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class RecommendationPlanEvaluationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = create_session()
        self.plan_repository = RecommendationPlanRepository(self.session)
        self.outcomes = RecommendationOutcomeRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()

    def test_run_evaluation_persists_trade_outcome_metrics_for_long_plan(self) -> None:
        plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=100.0,
                entry_price_high=101.0,
                stop_loss=96.0,
                take_profit=106.0,
                signal_breakdown={"setup_family": "continuation"},
                computed_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
            )
        )
        price_history = pd.DataFrame(
            {
                "High": [102.0, 107.0, 108.0],
                "Low": [99.5, 101.0, 104.0],
                "Close": [101.5, 106.5, 107.0],
            },
            index=pd.to_datetime(["2024-01-02T17:00:00Z", "2024-01-03T17:00:00Z", "2024-01-04T17:00:00Z"], utc=True),
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.win_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="AAPL", limit=10)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].outcome, "win")
        self.assertEqual(stored[0].setup_family, "continuation")
        self.assertEqual(stored[0].horizon, "1w")
        self.assertEqual(stored[0].transmission_bias, "unknown")
        self.assertEqual(stored[0].transmission_bias_label, "unknown")
        self.assertEqual(stored[0].context_regime, "mixed_context")
        self.assertEqual(stored[0].context_regime_label, "mixed context")
        self.assertTrue((stored[0].horizon_return_1d or 0) > 0)
        self.assertTrue((stored[0].max_favorable_excursion or 0) > 0)

    def test_run_evaluation_marks_no_action_plan_without_price_lookup_dependency(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="no_action",
                confidence_percent=44.0,
                computed_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
            )
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=pd.DataFrame()):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.no_action_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="MSFT", limit=10)
        self.assertEqual(stored[0].outcome, "no_action")
        self.assertEqual(stored[0].status, "resolved")


if __name__ == "__main__":
    unittest.main()
