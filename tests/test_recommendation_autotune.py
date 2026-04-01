from __future__ import annotations

import unittest
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationDecisionSample, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.recommendation_autotune import RecommendationAutotuneService


class RecommendationAutotuneServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = Session(bind=self.engine)
        self.plan_repository = RecommendationPlanRepository(self.session)
        self.sample_repository = RecommendationDecisionSampleRepository(self.session)
        self.outcome_repository = RecommendationOutcomeRepository(self.session)
        self.settings_repository = SettingsRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _create_resolved_sample(self, *, confidence: float, outcome: str, created_at: datetime) -> None:
        plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=confidence,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=created_at,
            )
        )
        self.sample_repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=plan.id or 0,
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK.value,
                action="long",
                decision_type="actionable",
                confidence_percent=confidence,
                calibrated_confidence_percent=confidence,
                setup_family="breakout",
                reviewed_at=created_at,
            )
        )
        self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                outcome=outcome,
                status="resolved",
                evaluated_at=created_at,
                confidence_bucket="high",
                setup_family="breakout",
            )
        )

    def test_run_persists_best_threshold_and_candidate_results(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self._create_resolved_sample(confidence=67.0, outcome="win", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=65.0, outcome="win", created_at=datetime(2026, 3, 2, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=61.0, outcome="loss", created_at=datetime(2026, 3, 3, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=55.0, outcome="loss", created_at=datetime(2026, 3, 4, tzinfo=timezone.utc))

        run = RecommendationAutotuneService(self.session).run()

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.objective_name, "confidence_threshold_raw_grid")
        self.assertEqual(run.sample_count, 4)
        self.assertEqual(run.resolved_sample_count, 4)
        self.assertGreaterEqual(run.candidate_count, 5)
        self.assertEqual(run.baseline_threshold, 60.0)
        self.assertEqual(run.best_threshold, 64.0)
        self.assertGreater(run.best_score or 0.0, run.baseline_score or 0.0)
        self.assertEqual(run.winning_config["confidence_threshold"], 64.0)
        self.assertEqual(len(run.candidate_results), run.candidate_count)
        self.assertTrue(any(candidate["threshold"] == 64.0 for candidate in run.candidate_results))

        stored_latest = RecommendationAutotuneService(self.session).describe()["latest_run"]
        self.assertIsNotNone(stored_latest)
        self.assertEqual(stored_latest.best_threshold, 64.0)

    def test_run_with_apply_updates_confidence_threshold_setting(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self._create_resolved_sample(confidence=67.0, outcome="win", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=65.0, outcome="win", created_at=datetime(2026, 3, 2, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=61.0, outcome="loss", created_at=datetime(2026, 3, 3, tzinfo=timezone.utc))

        run = RecommendationAutotuneService(self.session).run(apply=True)

        self.assertTrue(run.applied)
        self.assertEqual(self.settings_repository.get_confidence_threshold(), 64.0)
        self.assertEqual(run.summary["applied_threshold"], 64.0)
        self.assertIn("shortlist_aggressiveness", run.winning_config)
        self.assertIn("near_miss_gap_cutoff", run.winning_config)

    def test_run_scores_multi_parameter_grid_and_prefers_shortlist_promotion(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self.settings_repository.set_autotune_config(
            confidence_adjustment=-4.0,
            near_miss_gap_cutoff=0.0,
            shortlist_aggressiveness=0.0,
            degraded_penalty=3.0,
        )

        payloads = [
            (59.0, "win", "near_miss", True, 59.0, datetime(2026, 3, 1, tzinfo=timezone.utc)),
            (59.0, "loss", "no_action", False, 59.0, datetime(2026, 3, 2, tzinfo=timezone.utc)),
            (63.0, "win", "actionable", False, 63.0, datetime(2026, 3, 3, tzinfo=timezone.utc)),
            (52.0, "loss", "degraded", True, 52.0, datetime(2026, 3, 4, tzinfo=timezone.utc)),
        ]
        for confidence, outcome, decision_type, shortlisted, calibrated_confidence, created_at in payloads:
            plan = self.plan_repository.create_plan(
                RecommendationPlan(
                    ticker="EOG",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action="long",
                    confidence_percent=confidence,
                    entry_price_low=100.0,
                    entry_price_high=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    signal_breakdown={"setup_family": "breakout"},
                    computed_at=created_at,
                )
            )
            self.sample_repository.upsert_sample(
                RecommendationDecisionSample(
                    recommendation_plan_id=plan.id or 0,
                    ticker="EOG",
                    horizon=StrategyHorizon.ONE_WEEK.value,
                    action="long",
                    decision_type=decision_type,
                    shortlisted=shortlisted,
                    confidence_percent=confidence,
                    calibrated_confidence_percent=calibrated_confidence,
                    setup_family="breakout",
                    reviewed_at=created_at,
                )
            )
            self.outcome_repository.upsert_outcome(
                RecommendationPlanOutcome(
                    recommendation_plan_id=plan.id or 0,
                    outcome=outcome,
                    status="resolved",
                    evaluated_at=created_at,
                    confidence_bucket="high",
                    setup_family="breakout",
                )
            )

        run = RecommendationAutotuneService(self.session).run()

        self.assertGreaterEqual(run.candidate_count, 100)
        self.assertGreater(run.best_score or 0.0, run.baseline_score or 0.0)
        self.assertGreater(run.winning_config["shortlist_aggressiveness"], 0)
        self.assertIn("near_miss_gap_cutoff", run.winning_config)
        self.assertTrue(any(candidate["shortlisted_selected_count"] > 0 for candidate in run.candidate_results))
        self.assertTrue(any(candidate["near_miss_selected_count"] > 0 for candidate in run.candidate_results))
        self.assertTrue(any(candidate["degraded_selected_count"] > 0 for candidate in run.candidate_results))


class RecommendationAutotuneRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._previous_single_user_auth_enabled = settings.single_user_auth_enabled
        settings.single_user_auth_enabled = False
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=self.engine)

        def override_db_session():
            session = Session(bind=self.engine)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db_session] = override_db_session

    async def asyncTearDown(self) -> None:
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        app.dependency_overrides.clear()
        self.engine.dispose()

    async def test_run_endpoint_returns_autotune_run(self) -> None:
        session = Session(bind=self.engine)
        try:
            plan_repository = RecommendationPlanRepository(session)
            sample_repository = RecommendationDecisionSampleRepository(session)
            outcome_repository = RecommendationOutcomeRepository(session)
            settings_repository = SettingsRepository(session)
            settings_repository.set_confidence_threshold(60.0)

            for index, (confidence, outcome) in enumerate([(67.0, "win"), (65.0, "win"), (61.0, "loss")], start=1):
                plan = plan_repository.create_plan(
                    RecommendationPlan(
                        ticker="EOG",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=confidence,
                        entry_price_low=100.0,
                        entry_price_high=100.0,
                        stop_loss=95.0,
                        take_profit=110.0,
                        signal_breakdown={"setup_family": "breakout"},
                        computed_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                    )
                )
                sample_repository.upsert_sample(
                    RecommendationDecisionSample(
                        recommendation_plan_id=plan.id or 0,
                        ticker="EOG",
                        horizon=StrategyHorizon.ONE_WEEK.value,
                        action="long",
                        decision_type="actionable",
                        confidence_percent=confidence,
                        calibrated_confidence_percent=confidence,
                        setup_family="breakout",
                        reviewed_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                    )
                )
                outcome_repository.upsert_outcome(
                    RecommendationPlanOutcome(
                        recommendation_plan_id=plan.id or 0,
                        outcome=outcome,
                        status="resolved",
                        evaluated_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                        confidence_bucket="high",
                        setup_family="breakout",
                    )
                )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/recommendation-autotune/run?apply=true")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["applied"])
            self.assertEqual(payload["best_threshold"], 64.0)
            self.assertEqual(payload["summary"]["applied_threshold"], 64.0)

            state_response = await client.get("/api/recommendation-autotune")
            self.assertEqual(state_response.status_code, 200)
            state_payload = state_response.json()
            self.assertEqual(state_payload["current_confidence_threshold"], 64.0)
            self.assertEqual(state_payload["latest_run"]["best_threshold"], 64.0)
            self.assertIn("active_tuning", state_payload)
            self.assertIn("shortlist_aggressiveness", state_payload["active_tuning"])
