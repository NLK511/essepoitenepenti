import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_evidence_concentration import RecommendationEvidenceConcentrationService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class RecommendationEvidenceConcentrationTests(unittest.TestCase):
    def test_summarize_highlights_strong_and_weak_cohorts(self) -> None:
        session = create_session()
        plans = RecommendationPlanRepository(session)
        outcomes = RecommendationOutcomeRepository(session)
        try:
            for index in range(12):
                plan = plans.create_plan(
                    RecommendationPlan(
                        ticker=f"CN{index}",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=74.0,
                        computed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        signal_breakdown={"setup_family": "continuation"},
                    )
                )
                outcomes.upsert_outcome(
                    RecommendationPlanOutcome(
                        recommendation_plan_id=plan.id or 0,
                        ticker=f"CN{index}",
                        action="long",
                        outcome="win" if index < 9 else "loss",
                        status="resolved",
                        confidence_bucket="65_to_79",
                        setup_family="continuation",
                        horizon="1w",
                        transmission_bias="tailwind",
                        context_regime="macro_dominant",
                        horizon_return_5d=1.8 if index < 9 else -0.7,
                    )
                )
            for index in range(12):
                plan = plans.create_plan(
                    RecommendationPlan(
                        ticker=f"BR{index}",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=72.0,
                        computed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        signal_breakdown={"setup_family": "breakout"},
                    )
                )
                outcomes.upsert_outcome(
                    RecommendationPlanOutcome(
                        recommendation_plan_id=plan.id or 0,
                        ticker=f"BR{index}",
                        action="long",
                        outcome="loss" if index < 9 else "win",
                        status="resolved",
                        confidence_bucket="65_to_79",
                        setup_family="breakout",
                        horizon="1w",
                        transmission_bias="headwind",
                        context_regime="industry_dominant",
                        horizon_return_5d=-1.9 if index < 9 else 0.6,
                    )
                )

            summary = RecommendationEvidenceConcentrationService(outcomes).summarize(limit=100)

            self.assertEqual(summary.resolved_outcomes_reviewed, 24)
            self.assertFalse(summary.ready_for_expansion)
            self.assertTrue(summary.strongest_positive_cohorts)
            self.assertTrue(summary.weakest_cohorts)
            self.assertEqual(summary.strongest_positive_cohorts[0].key, "continuation")
            self.assertEqual(summary.strongest_positive_cohorts[0].slice_label, "setup family")
            self.assertEqual(summary.weakest_cohorts[0].key, "breakout")
            self.assertIn("strongest usable cohorts", summary.focus_message.lower())
            self.assertIn("cohort", summary.strongest_positive_cohorts[0].interpretation.lower())
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
