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
from trade_proposer_app.domain.models import RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import PARAMETER_BY_KEY, normalize_plan_generation_tuning_config, parameter_definitions
from trade_proposer_app.services.plan_reliability_features import PlanReliabilityFeatureBuilder


class PlanGenerationTuningServiceTests(unittest.TestCase):
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
        self.outcome_repository = RecommendationOutcomeRepository(self.session)
        self.settings_repository = SettingsRepository(self.session)
        self.tuning_repository = PlanGenerationTuningRepository(self.session)
        self.service = PlanGenerationTuningService(self.session)
        self.settings_repository.set_plan_generation_tuning_settings(
            auto_enabled=False,
            auto_promote_enabled=False,
            min_actionable_resolved=4,
            min_validation_resolved=2,
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _seed_record(
        self,
        *,
        created_at: datetime,
        mfe: float,
        mae: float,
        outcome: str,
        setup_family: str = "breakout",
        action: str = "long",
        intended_action: str | None = None,
        stop_loss_hit: bool | None = None,
        take_profit_hit: bool | None = None,
        horizon_return_5d: float | None = None,
    ) -> None:
        signal_breakdown = {
            "setup_family": setup_family,
            "transmission_summary": {"context_bias": "tailwind"},
        }
        if intended_action is not None:
            signal_breakdown["intended_action"] = intended_action
        plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action=action,
                confidence_percent=72.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                signal_breakdown=signal_breakdown,
                computed_at=created_at,
            )
        )
        self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                outcome=outcome,
                status="resolved",
                evaluated_at=created_at,
                stop_loss_hit=stop_loss_hit,
                take_profit_hit=take_profit_hit,
                horizon_return_5d=horizon_return_5d,
                max_favorable_excursion=mfe,
                max_adverse_excursion=mae,
                confidence_bucket="65_to_79",
                setup_family=setup_family,
            )
        )

    def test_broker_resolved_records_without_excursions_are_still_eligible_for_tuning(self) -> None:
        plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                signal_breakdown={
                    "setup_family": "breakout",
                    "transmission_summary": {"context_bias": "tailwind"},
                },
                computed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
        )
        features = PlanReliabilityFeatureBuilder().build(
            self.plan_repository.get_plan(plan.id or 0),
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                outcome="win",
                status="resolved",
                evaluated_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
                outcome_source="broker",
                realized_return_pct=12.5,
                realized_pnl=125.0,
                setup_family="breakout",
            ),
        )
        self.assertIsNotNone(features)
        self.assertEqual(features.setup_family if features is not None else None, "breakout")

    def test_describe_seeds_baseline_config_and_exposes_parameter_schema(self) -> None:
        payload = self.service.describe()

        self.assertEqual(payload["objective_name"], "plan_generation_precision_tuning_v1")
        self.assertEqual(payload["parameter_schema_version"], "v1")
        self.assertGreaterEqual(len(payload["parameters"]), 5)
        self.assertIsNotNone(payload["state"].active_config_version_id)
        self.assertEqual(payload["state"].active_config["setup_family.breakout.take_profit_distance_multiplier"], 1.12)

    def test_parameter_schema_exposes_the_first_campaign_exploration_envelope(self) -> None:
        parameters = {item["key"]: item for item in parameter_definitions()}
        self.assertEqual(parameters["global.entry_band_risk_fraction"]["exploration_min"], 0.0)
        self.assertEqual(parameters["global.entry_band_risk_fraction"]["exploration_max"], 0.15)
        self.assertEqual(parameters["setup_family.breakout.take_profit_distance_multiplier"]["exploration_min"], 1.05)
        self.assertEqual(parameters["setup_family.breakout.take_profit_distance_multiplier"]["exploration_max"], 1.25)

    def test_run_ranks_candidates_lexicographically_and_persists_candidate_history(self) -> None:
        # Search slice
        self._seed_record(created_at=datetime(2026, 3, 1, tzinfo=timezone.utc), mfe=15.0, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 2, tzinfo=timezone.utc), mfe=12.5, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 3, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)
        self._seed_record(created_at=datetime(2026, 3, 4, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        # Validation slice
        self._seed_record(created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)

        run = self.service.run(limit=50)

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.eligible_record_count, 6)
        self.assertEqual(run.validation_record_count, 2)
        self.assertGreaterEqual(run.candidate_count, 3)
        self.assertIsNotNone(run.winning_candidate_id)
        self.assertIsNone(run.promoted_config_version_id)
        self.assertEqual(len(run.candidates), run.candidate_count)

        winner = run.candidates[0]
        baseline = next(candidate for candidate in run.candidates if candidate.is_baseline)
        self.assertGreater(
            winner.metric_breakdown["validation_win_rate_percent"],
            baseline.metric_breakdown["validation_win_rate_percent"],
        )
        self.assertIn("setup_family.breakout.take_profit_distance_multiplier", winner.changed_keys)
        self.assertEqual(winner.metric_breakdown["validation_win_count"], 1)
        self.assertEqual(winner.metric_breakdown["validation_actionable_count"], 2)

        stored = self.tuning_repository.get_run(run.id or 0)
        self.assertEqual(stored.winning_candidate_id, winner.id)
        self.assertEqual(len(stored.candidates), len(run.candidates))

    def test_explore_mode_uses_broader_candidate_search_and_persists_seed(self) -> None:
        for index in range(1, 9):
            self._seed_record(
                created_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                mfe=12.0 if index % 2 else 3.0,
                mae=3.0 if index % 2 else 11.0,
                outcome="win" if index % 2 else "loss",
                stop_loss_hit=index % 2 == 0,
                take_profit_hit=index % 2 == 1,
            )

        manual_run = self.service.run(mode="manual", limit=50)
        explore_run = self.service.run(mode="explore", limit=None)

        self.assertGreater(explore_run.candidate_count, manual_run.candidate_count)
        self.assertTrue(bool(explore_run.summary.get("exploration_mode")))
        self.assertIsInstance(explore_run.summary.get("exploration_seed"), int)
        self.assertGreaterEqual(explore_run.summary.get("history_span_days", 0), 30)
        for candidate in explore_run.candidates:
            for key, value in candidate.config.items():
                definition = PARAMETER_BY_KEY[key]
                self.assertGreaterEqual(value, definition.exploration_min)
                self.assertLessEqual(value, definition.exploration_max)

    def test_apply_promotes_only_guardrail_eligible_winner_and_updates_active_config(self) -> None:
        self._seed_record(created_at=datetime(2026, 3, 1, tzinfo=timezone.utc), mfe=15.0, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 2, tzinfo=timezone.utc), mfe=12.5, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 3, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)
        self._seed_record(created_at=datetime(2026, 3, 4, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)

        run = self.service.run(limit=50, apply=True)

        self.assertIsNotNone(run.promoted_config_version_id)
        active_config_version_id = self.settings_repository.get_plan_generation_active_config_version_id()
        self.assertEqual(active_config_version_id, run.promoted_config_version_id)
        promoted = self.tuning_repository.get_config_version(run.promoted_config_version_id or 0)
        self.assertEqual(promoted.source_run_id, run.id)
        self.assertEqual(promoted.status, "active")

    def test_live_trade_level_logic_uses_active_plan_generation_config_defaults_and_overrides(self) -> None:
        baseline = normalize_plan_generation_tuning_config(None)
        baseline_levels = family_adjusted_trade_levels(
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            setup_family="breakout",
            action="long",
            transmission_context_bias="tailwind",
            tuning_config=baseline,
        )
        aggressive = dict(baseline)
        aggressive["setup_family.breakout.take_profit_distance_multiplier"] = 1.17
        aggressive["setup_family.breakout.stop_distance_multiplier"] = 0.8
        aggressive["global.entry_band_risk_fraction"] = 0.1
        overridden_levels = family_adjusted_trade_levels(
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            setup_family="breakout",
            action="long",
            transmission_context_bias="tailwind",
            tuning_config=aggressive,
        )

        self.assertEqual(baseline_levels, (100.0, 100.0, 95.75, 111.2))
        self.assertEqual(overridden_levels, (99.5, 100.5, 96.0, 111.7))

    def test_eligible_records_include_scoreable_phantom_wins_and_losses_only_for_no_action_or_watchlist(self) -> None:
        self._seed_record(
            created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            mfe=15.0,
            mae=4.0,
            outcome="win",
            action="long",
            stop_loss_hit=False,
            take_profit_hit=True,
        )
        self._seed_record(
            created_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
            mfe=14.0,
            mae=4.0,
            outcome="phantom_win",
            action="no_action",
            intended_action="long",
            stop_loss_hit=False,
            take_profit_hit=True,
        )
        self._seed_record(
            created_at=datetime(2026, 3, 3, tzinfo=timezone.utc),
            mfe=2.0,
            mae=11.0,
            outcome="phantom_loss",
            action="watchlist",
            intended_action="short",
            stop_loss_hit=True,
            take_profit_hit=False,
        )
        self._seed_record(
            created_at=datetime(2026, 3, 4, tzinfo=timezone.utc),
            mfe=0.0,
            mae=0.0,
            outcome="phantom_no_entry",
            action="no_action",
            intended_action="long",
            horizon_return_5d=-0.25,
        )

        eligible = self.service._eligible_records(ticker="EOG", setup_family=None, limit=50)

        self.assertEqual(len(eligible), 3)
        self.assertEqual([record.plan.action for record in eligible], ["long", "no_action", "watchlist"])
        scored = self.service._score_records(eligible, normalize_plan_generation_tuning_config(None))
        self.assertEqual(scored[0], 3)
        self.assertEqual(scored[1], 2)


class PlanGenerationTuningRouteTests(unittest.IsolatedAsyncioTestCase):
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

        session = Session(bind=self.engine)
        try:
            settings_repository = SettingsRepository(session)
            settings_repository.set_plan_generation_tuning_settings(
                auto_enabled=False,
                auto_promote_enabled=False,
                min_actionable_resolved=4,
                min_validation_resolved=2,
            )
            plan_repository = RecommendationPlanRepository(session)
            outcome_repository = RecommendationOutcomeRepository(session)
            payloads = [
                (datetime(2026, 3, 1, tzinfo=timezone.utc), 15.0, 4.0, "win", False, True),
                (datetime(2026, 3, 2, tzinfo=timezone.utc), 12.5, 4.0, "win", False, True),
                (datetime(2026, 3, 3, tzinfo=timezone.utc), 2.0, 11.0, "loss", True, False),
                (datetime(2026, 3, 4, tzinfo=timezone.utc), 10.9, 3.0, "win", False, True),
                (datetime(2026, 3, 5, tzinfo=timezone.utc), 10.9, 3.0, "win", False, True),
                (datetime(2026, 3, 6, tzinfo=timezone.utc), 2.0, 11.0, "loss", True, False),
            ]
            for created_at, mfe, mae, outcome, stop_loss_hit, take_profit_hit in payloads:
                plan = plan_repository.create_plan(
                    RecommendationPlan(
                        ticker="EOG",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=72.0,
                        entry_price_low=100.0,
                        entry_price_high=100.0,
                        stop_loss=95.0,
                        take_profit=110.0,
                        signal_breakdown={
                            "setup_family": "breakout",
                            "transmission_summary": {"context_bias": "tailwind"},
                        },
                        computed_at=created_at,
                    )
                )
                outcome_repository.upsert_outcome(
                    RecommendationPlanOutcome(
                        recommendation_plan_id=plan.id or 0,
                        outcome=outcome,
                        status="resolved",
                        evaluated_at=created_at,
                        stop_loss_hit=stop_loss_hit,
                        take_profit_hit=take_profit_hit,
                        max_favorable_excursion=mfe,
                        max_adverse_excursion=mae,
                        confidence_bucket="65_to_79",
                        setup_family="breakout",
                    )
                )
        finally:
            session.close()

    async def asyncTearDown(self) -> None:
        settings.single_user_auth_enabled = self._previous_single_user_auth_enabled
        app.dependency_overrides.clear()
        self.engine.dispose()

    async def test_routes_expose_state_runs_and_configs(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            state = await client.get("/api/plan-generation-tuning")
            self.assertEqual(state.status_code, 200)
            state_payload = state.json()
            self.assertIn("parameters", state_payload)
            self.assertIn("state", state_payload)
            self.assertIsNotNone(state_payload["state"]["active_config_version_id"])

            run_response = await client.post("/api/plan-generation-tuning/run?apply=true")
            self.assertEqual(run_response.status_code, 200)
            run_payload = run_response.json()
            self.assertIsNotNone(run_payload["winning_candidate_id"])
            self.assertIsNotNone(run_payload["promoted_config_version_id"])
            self.assertEqual(run_payload["candidates"][0]["id"], run_payload["winning_candidate_id"])

            runs = await client.get("/api/plan-generation-tuning/runs?limit=10")
            self.assertEqual(runs.status_code, 200)
            runs_payload = runs.json()
            self.assertGreaterEqual(runs_payload["total"], 1)
            self.assertGreaterEqual(len(runs_payload["items"]), 1)

            configs = await client.get("/api/plan-generation-tuning/configs?limit=10")
            self.assertEqual(configs.status_code, 200)
            configs_payload = configs.json()
            self.assertGreaterEqual(configs_payload["total"], 2)
            promoted_config_id = run_payload["promoted_config_version_id"]
            promoted_detail = await client.get(f"/api/plan-generation-tuning/configs/{promoted_config_id}")
            self.assertEqual(promoted_detail.status_code, 200)
            detail_payload = promoted_detail.json()
            self.assertEqual(detail_payload["config"]["id"], promoted_config_id)
            self.assertTrue(any(event["event_type"] in {"config_promoted", "config_promoted_manual"} for event in detail_payload["events"]))


class PlanGenerationTuningValidationFallbackTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_validation_returns_fallback_summary_when_no_records_exist(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/plan-generation-tuning/validation")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["summary"]["qualified_slices"], 0)
            self.assertFalse(payload["summary"]["promotion_recommended"])
            self.assertIn("no eligible records", payload["summary"]["promotion_rationale"].lower())
