from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from functools import cmp_to_key
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import PlanGenerationWalkForwardSummary, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base, RunRecord, WorkerHeartbeatRecord
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.plan_generation_tuning import CandidateEvaluation, PlanGenerationTuningError, PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import PARAMETER_BY_KEY, exploration_campaigns, normalize_plan_generation_tuning_config, parameter_definitions
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
        self.assertGreaterEqual(len(payload["parameters"]), 8)
        self.assertIsNotNone(payload["state"].active_config_version_id)
        self.assertEqual(payload["state"].active_config["setup_family.breakout.take_profit_distance_multiplier"], 1.12)
        self.assertEqual(payload["state"].active_config["setup_family.entry_band_multiplier"], 1.0)
        self.assertEqual(payload["state"].active_config["global.actionable_confidence_floor_percent"], 60.0)
        self.assertEqual(payload["state"].active_config["global.volatility_stop_multiplier"], 0.12)

    def test_parameter_schema_exposes_the_first_campaign_exploration_envelope(self) -> None:
        parameters = {item["key"]: item for item in parameter_definitions()}
        self.assertEqual(parameters["global.entry_band_risk_fraction"]["exploration_min"], 0.0)
        self.assertEqual(parameters["global.entry_band_risk_fraction"]["exploration_max"], 0.25)
        self.assertEqual(parameters["setup_family.entry_band_multiplier"]["exploration_min"], 0.9)
        self.assertEqual(parameters["setup_family.entry_band_multiplier"]["exploration_max"], 1.12)
        self.assertEqual(parameters["global.headwind_stop_multiplier"]["exploration_min"], 0.84)
        self.assertEqual(parameters["global.headwind_stop_multiplier"]["exploration_max"], 1.02)
        self.assertEqual(parameters["global.actionable_confidence_floor_percent"]["exploration_min"], 40.0)
        self.assertEqual(parameters["global.actionable_confidence_floor_percent"]["exploration_max"], 70.0)
        self.assertEqual(parameters["global.volatility_stop_multiplier"]["exploration_min"], 0.0)
        self.assertEqual(parameters["global.volatility_stop_multiplier"]["exploration_max"], 0.25)
        self.assertEqual(parameters["setup_family.breakout.take_profit_distance_multiplier"]["exploration_min"], 0.95)
        self.assertEqual(parameters["setup_family.breakout.take_profit_distance_multiplier"]["exploration_max"], 1.45)

    def test_exploration_campaign_plan_is_ranked_and_bounded(self) -> None:
        campaigns = exploration_campaigns()
        self.assertEqual([item["name"] for item in campaigns[:4]], ["entry_calibration", "selectivity", "risk_protection", "reward_expansion"])
        self.assertEqual(campaigns[0]["candidate_budget"], 4)
        self.assertEqual(campaigns[1]["candidate_budget"], 1)
        self.assertEqual(campaigns[2]["candidate_budget"], 4)
        self.assertEqual(campaigns[3]["candidate_budget"], 4)
        self.assertEqual(sum(item["candidate_budget"] for item in campaigns), 13)

    def test_describe_includes_the_ranked_exploration_campaign_plan(self) -> None:
        payload = self.service.describe()
        self.assertIn("exploration_campaigns", payload)
        self.assertEqual([item["name"] for item in payload["exploration_campaigns"][:4]], ["entry_calibration", "selectivity", "risk_protection", "reward_expansion"])

    def test_candidate_ranking_applies_documented_tie_tolerances(self) -> None:
        baseline = CandidateEvaluation(
            config={"a": 1.0},
            changed_keys=["a"],
            search_actionable_count=100,
            search_win_count=60,
            search_expected_value=1.0,
            search_ambiguous_count=0,
            validation_actionable_count=1000,
            validation_win_count=600,
            validation_expected_value=1.00,
            validation_ambiguous_count=0,
        )
        higher_ev_inside_ties = CandidateEvaluation(
            config={"a": 1.0, "b": 1.0},
            changed_keys=["a", "b"],
            search_actionable_count=100,
            search_win_count=60,
            search_expected_value=1.0,
            search_ambiguous_count=0,
            validation_actionable_count=1000,
            validation_win_count=601,
            validation_expected_value=1.03,
            validation_ambiguous_count=0,
        )
        lower_win_rate_outside_tolerance = CandidateEvaluation(
            config={"c": 1.0},
            changed_keys=["c"],
            search_actionable_count=100,
            search_win_count=60,
            search_expected_value=1.0,
            search_ambiguous_count=0,
            validation_actionable_count=1000,
            validation_win_count=597,
            validation_expected_value=9.00,
            validation_ambiguous_count=0,
        )

        candidates = [lower_win_rate_outside_tolerance, baseline, higher_ev_inside_ties]
        candidates.sort(key=cmp_to_key(PlanGenerationTuningService._candidate_compare))

        self.assertIs(candidates[0], higher_ev_inside_ties)
        self.assertIs(candidates[1], baseline)
        self.assertIs(candidates[2], lower_win_rate_outside_tolerance)

    def test_promotion_eligibility_applies_documented_tie_tolerances(self) -> None:
        baseline = CandidateEvaluation(
            config={}, changed_keys=[], search_actionable_count=100, search_win_count=60, search_expected_value=1.0, search_ambiguous_count=0,
            validation_actionable_count=1000, validation_win_count=600, validation_expected_value=1.0, validation_ambiguous_count=0,
        )
        within_tie = CandidateEvaluation(
            config={}, changed_keys=["x"], search_actionable_count=100, search_win_count=60, search_expected_value=1.0, search_ambiguous_count=0,
            validation_actionable_count=1000, validation_win_count=599, validation_expected_value=0.99, validation_ambiguous_count=0,
        )
        outside_win_rate = CandidateEvaluation(
            config={}, changed_keys=["x"], search_actionable_count=100, search_win_count=60, search_expected_value=1.0, search_ambiguous_count=0,
            validation_actionable_count=1000, validation_win_count=597, validation_expected_value=9.0, validation_ambiguous_count=0,
        )

        self.assertTrue(PlanGenerationTuningService._promotion_eligible(within_tie, baseline, min_validation_resolved=10))
        self.assertFalse(PlanGenerationTuningService._promotion_eligible(outside_win_rate, baseline, min_validation_resolved=10))
        self.assertIn("validation_win_rate_below_baseline", PlanGenerationTuningService._rejection_reasons(outside_win_rate, baseline, min_validation_resolved=10))

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

    def test_run_emits_worker_progress_logs(self) -> None:
        for index in range(1, 7):
            self._seed_record(
                created_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                mfe=15.0 if index % 2 else 3.0,
                mae=3.0 if index % 2 else 11.0,
                outcome="win" if index % 2 else "loss",
                stop_loss_hit=index % 2 == 0,
                take_profit_hit=index % 2 == 1,
            )

        with patch("trade_proposer_app.services.plan_generation_tuning.logger") as mock_logger:
            run = self.service.run(mode="wide", limit=None)

        self.assertEqual(run.status, "completed")
        logged_messages = " ".join(str(call.args[0]) for call in mock_logger.info.call_args_list if call.args)
        self.assertIn("plan generation tuning started", logged_messages)
        self.assertIn("plan generation tuning candidate search prepared", logged_messages)
        self.assertIn("plan generation tuning evaluating batch", logged_messages)
        self.assertIn("plan generation tuning finished", logged_messages)

    def test_eligible_records_stream_all_batches_without_truncation(self) -> None:
        for index in range(1, 7):
            self._seed_record(
                created_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                mfe=15.0 if index % 2 else 3.0,
                mae=3.0 if index % 2 else 11.0,
                outcome="win" if index % 2 else "loss",
                stop_loss_hit=index % 2 == 0,
                take_profit_hit=index % 2 == 1,
            )

        with patch.object(PlanGenerationTuningService, "ELIGIBLE_RECORD_BATCH_SIZE", 2):
            with patch.object(self.service.plans, "list_plans", wraps=self.service.plans.list_plans) as mock_list_plans:
                eligible = self.service._eligible_records(ticker=None, setup_family=None, limit=None)

        self.assertEqual(len(eligible), 6)
        self.assertGreaterEqual(mock_list_plans.call_count, 3)

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
        wide_run = self.service.run(mode="wide", limit=None)

        self.assertEqual(manual_run.candidate_count, 25)
        self.assertEqual(explore_run.candidate_count, 45)
        self.assertEqual(wide_run.candidate_count, 66)
        self.assertEqual(manual_run.summary.get("refinement_candidate_count"), 3)
        self.assertEqual(explore_run.summary.get("refinement_candidate_count"), 2)
        self.assertEqual(wide_run.summary.get("refinement_candidate_count"), 5)
        self.assertTrue(bool(explore_run.summary.get("exploration_mode")))
        self.assertTrue(bool(wide_run.summary.get("wide_research_mode")))
        self.assertIsInstance(explore_run.summary.get("exploration_seed"), int)
        self.assertIsInstance(wide_run.summary.get("exploration_seed"), int)
        self.assertGreaterEqual(explore_run.summary.get("history_span_days", 0), 30)
        self.assertEqual([item["name"] for item in explore_run.summary.get("exploration_campaign_plan")], ["entry_calibration", "selectivity", "risk_protection", "reward_expansion"])
        self.assertEqual(wide_run.summary.get("validation_mode"), "rolling_walk_forward")
        self.assertGreaterEqual(wide_run.summary.get("validation_slice_count", 0), explore_run.summary.get("validation_slice_count", 0))
        self.assertGreaterEqual(explore_run.summary.get("evaluation_batch_count", 0), 1)
        self.assertGreater(wide_run.summary.get("evaluation_batch_count", 0), 1)
        self.assertEqual(explore_run.summary.get("candidate_batch_size"), 12)
        self.assertEqual(wide_run.summary.get("candidate_batch_size"), 16)
        self.assertEqual(explore_run.summary.get("exploration_campaign_plan")[1]["name"], "selectivity")
        for candidate in explore_run.candidates[1:]:
            self.assertIn("campaign", candidate.metric_breakdown)
            self.assertLessEqual(len(candidate.changed_keys), 1)
            for key, value in candidate.config.items():
                definition = PARAMETER_BY_KEY[key]
                self.assertGreaterEqual(value, definition.exploration_min)
                self.assertLessEqual(value, definition.exploration_max)
        for candidate in wide_run.candidates[1:]:
            self.assertIn("campaign", candidate.metric_breakdown)
            self.assertLessEqual(len(candidate.changed_keys), 1)
            for key, value in candidate.config.items():
                definition = PARAMETER_BY_KEY[key]
                self.assertGreaterEqual(value, definition.exploration_min)
                self.assertLessEqual(value, definition.exploration_max)

    def test_run_aborts_when_memory_guard_trips(self) -> None:
        for index in range(1, 9):
            self._seed_record(
                created_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                mfe=12.0 if index % 2 else 3.0,
                mae=3.0 if index % 2 else 11.0,
                outcome="win" if index % 2 else "loss",
                stop_loss_hit=index % 2 == 0,
                take_profit_hit=index % 2 == 1,
            )

        with patch.object(PlanGenerationTuningService, "_current_rss_bytes", return_value=2_000_000_000), patch.object(
            PlanGenerationTuningService, "_memory_limit_bytes", return_value=1_000_000_000
        ):
            with self.assertRaises(PlanGenerationTuningError):
                self.service.run(mode="wide", limit=None)

    def test_explore_mode_ranks_candidates_with_rolling_walk_forward_validation(self) -> None:
        for index in range(1, 9):
            self._seed_record(
                created_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                mfe=12.0 if index % 2 else 3.0,
                mae=3.0 if index % 2 else 11.0,
                outcome="win" if index % 2 else "loss",
                stop_loss_hit=index % 2 == 0,
                take_profit_hit=index % 2 == 1,
            )

        active_config = normalize_plan_generation_tuning_config(None)
        improved_config = dict(active_config)
        improved_config["setup_family.breakout.take_profit_distance_multiplier"] = 1.45

        walk_forward_baseline = PlanGenerationWalkForwardSummary(
            total_slices=4,
            lookback_days=30,
            validation_days=90,
            step_days=30,
            min_validation_resolved=2,
            candidate_label="candidate",
            baseline_label="baseline",
            qualified_slices=3,
            candidate_wins=1,
            baseline_wins=1,
            ties=1,
            average_win_rate_delta=0.0,
            average_expected_value_delta=0.0,
            promotion_recommended=False,
            promotion_rationale="baseline",
            slices=[],
        )
        walk_forward_improved = PlanGenerationWalkForwardSummary(
            total_slices=4,
            lookback_days=30,
            validation_days=90,
            step_days=30,
            min_validation_resolved=2,
            candidate_label="candidate",
            baseline_label="baseline",
            qualified_slices=3,
            candidate_wins=3,
            baseline_wins=0,
            ties=0,
            average_win_rate_delta=8.0,
            average_expected_value_delta=0.35,
            promotion_recommended=True,
            promotion_rationale="improved",
            slices=[],
        )

        def summarize_records_side_effect(self, *, records, candidate_config, baseline_config, candidate_label, baseline_label, lookback_days, validation_days, step_days, min_validation_resolved):
            if candidate_config == baseline_config:
                return walk_forward_baseline
            return walk_forward_improved

        with patch.object(PlanGenerationTuningService, "_candidate_configs", return_value=[active_config, improved_config]), patch("trade_proposer_app.services.plan_generation_walk_forward.PlanGenerationWalkForwardService.summarize_records", autospec=True, side_effect=summarize_records_side_effect):
            explore_run = self.service.run(mode="explore", limit=None)

        self.assertEqual(explore_run.summary.get("validation_mode"), "rolling_walk_forward")
        self.assertEqual(explore_run.summary.get("validation_slice_count"), 4)
        self.assertEqual(explore_run.candidates[0].changed_keys, ["setup_family.breakout.take_profit_distance_multiplier"])
        self.assertGreaterEqual(explore_run.candidates[0].metric_breakdown["validation_win_rate_percent"], explore_run.candidates[1].metric_breakdown["validation_win_rate_percent"])

    def test_apply_promotes_only_guardrail_eligible_winner_and_updates_active_config(self) -> None:
        self._seed_record(created_at=datetime(2026, 3, 1, tzinfo=timezone.utc), mfe=15.0, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 2, tzinfo=timezone.utc), mfe=12.5, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 3, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)
        self._seed_record(created_at=datetime(2026, 3, 4, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)

        with patch.object(PlanGenerationTuningService, "_edge_validation_gate_report", return_value={"label": "eligible_for_cautious_expansion", "reasons": []}):
            run = self.service.run(limit=50, apply=True)

        self.assertIsNotNone(run.promoted_config_version_id)
        self.assertTrue(run.summary["promotion_applied"])
        self.assertFalse(run.summary["promotion_rejection_reasons"])
        active_config_version_id = self.settings_repository.get_plan_generation_active_config_version_id()
        self.assertEqual(active_config_version_id, run.promoted_config_version_id)
        promoted = self.tuning_repository.get_config_version(run.promoted_config_version_id or 0)
        self.assertEqual(promoted.source_run_id, run.id)
        self.assertEqual(promoted.status, "active")

    def test_apply_blocks_promotion_when_edge_validation_gate_fails(self) -> None:
        self._seed_record(created_at=datetime(2026, 3, 1, tzinfo=timezone.utc), mfe=15.0, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 2, tzinfo=timezone.utc), mfe=12.5, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 3, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)
        self._seed_record(created_at=datetime(2026, 3, 4, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)

        with patch.object(PlanGenerationTuningService, "_edge_validation_gate_report", return_value={"label": "research_only", "reasons": ["thin_broker_sample"]}):
            run = self.service.run(limit=50, apply=True)

        self.assertIsNone(run.promoted_config_version_id)
        self.assertFalse(run.summary["promotion_applied"])
        self.assertIn("edge_validation_gate_research_only", run.summary["promotion_rejection_reasons"])
        self.assertEqual(run.summary["edge_validation_gate"]["label"], "research_only")

    def test_apply_completes_without_promotion_when_winner_is_not_eligible(self) -> None:
        self._seed_record(created_at=datetime(2026, 3, 1, tzinfo=timezone.utc), mfe=15.0, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 2, tzinfo=timezone.utc), mfe=12.5, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 3, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)
        self._seed_record(created_at=datetime(2026, 3, 4, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)

        with patch.object(PlanGenerationTuningService, "_promotion_eligible", return_value=False):
            run = self.service.run(limit=50, apply=True)

        self.assertIsNone(run.promoted_config_version_id)
        self.assertFalse(run.summary["promotion_applied"])
        self.assertTrue(run.summary["promotion_rejection_reasons"])
        self.assertEqual(self.settings_repository.get_plan_generation_active_config_version_id(), run.baseline_config_version_id)
        events = self.tuning_repository.list_events(run_id=run.id or 0, limit=20)
        self.assertTrue(any(event.event_type == "config_promotion_skipped" for event in events))

    def test_manual_promote_allows_a_ranked_eligible_non_winner_candidate(self) -> None:
        self._seed_record(created_at=datetime(2026, 3, 1, tzinfo=timezone.utc), mfe=15.0, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 2, tzinfo=timezone.utc), mfe=12.5, mae=4.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 3, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)
        self._seed_record(created_at=datetime(2026, 3, 4, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), mfe=10.9, mae=3.0, outcome="win", take_profit_hit=True, stop_loss_hit=False)
        self._seed_record(created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), mfe=2.0, mae=11.0, outcome="loss", take_profit_hit=False, stop_loss_hit=True)

        active_config = normalize_plan_generation_tuning_config(None)
        winner_config = dict(active_config)
        winner_config["global.actionable_confidence_floor_percent"] = 65.0
        eligible_runner_up_config = dict(active_config)
        eligible_runner_up_config["setup_family.breakout.take_profit_distance_multiplier"] = 1.17

        winner_eval = CandidateEvaluation(
            config=winner_config,
            changed_keys=["global.actionable_confidence_floor_percent"],
            search_actionable_count=10,
            search_win_count=6,
            search_expected_value=1.0,
            search_ambiguous_count=0,
            validation_actionable_count=1,
            validation_win_count=1,
            validation_expected_value=1.0,
            validation_ambiguous_count=0,
        )
        runner_up_eval = CandidateEvaluation(
            config=eligible_runner_up_config,
            changed_keys=["setup_family.breakout.take_profit_distance_multiplier"],
            search_actionable_count=10,
            search_win_count=5,
            search_expected_value=0.8,
            search_ambiguous_count=0,
            validation_actionable_count=10,
            validation_win_count=5,
            validation_expected_value=0.8,
            validation_ambiguous_count=0,
        )
        baseline_eval = CandidateEvaluation(
            config=active_config,
            changed_keys=[],
            search_actionable_count=10,
            search_win_count=4,
            search_expected_value=0.5,
            search_ambiguous_count=0,
            validation_actionable_count=10,
            validation_win_count=4,
            validation_expected_value=0.5,
            validation_ambiguous_count=0,
        )

        def evaluate_side_effect(config, baseline_config, search_records, validation_records):
            if config == active_config:
                return baseline_eval
            if config == winner_config:
                return winner_eval
            if config == eligible_runner_up_config:
                return runner_up_eval
            raise AssertionError("unexpected config")

        with patch.object(PlanGenerationTuningService, "_candidate_configs", return_value=[active_config, winner_config, eligible_runner_up_config]), patch.object(
            PlanGenerationTuningService, "_refinement_configs", return_value=[]
        ), patch.object(PlanGenerationTuningService, "_evaluate_candidate", side_effect=evaluate_side_effect):
            run = self.service.run(limit=50)

        candidate_rank_2 = next(candidate for candidate in run.candidates if candidate.rank == 2)
        self.assertTrue(candidate_rank_2.promotion_eligible)
        with patch.object(PlanGenerationTuningService, "_edge_validation_gate_report", return_value={"label": "demote_or_halt", "reasons": ["negative_realized_pnl"]}):
            promoted = self.service.promote_candidate(run.id or 0, candidate_rank_2.id or 0)

        self.assertIsNotNone(promoted.id)
        self.assertEqual(promoted.source, "promoted_candidate")
        self.assertEqual(promoted.source_candidate_id, candidate_rank_2.id)
        self.assertEqual(self.settings_repository.get_plan_generation_active_config_version_id(), promoted.id)
        events = self.tuning_repository.list_events(config_version_id=promoted.id or 0, limit=10)
        self.assertTrue(any(event.event_type == "config_promoted_manual_candidate" for event in events))

    def test_live_trade_level_logic_uses_active_plan_generation_config_defaults_and_overrides(self) -> None:
        baseline = normalize_plan_generation_tuning_config(None)
        baseline_levels = family_adjusted_trade_levels(
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            setup_family="breakout",
            action="long",
            transmission_context_bias="tailwind",
            volatility_score=50.0,
            tuning_config=baseline,
        )
        aggressive = dict(baseline)
        aggressive["setup_family.breakout.take_profit_distance_multiplier"] = 1.17
        aggressive["setup_family.breakout.stop_distance_multiplier"] = 0.8
        aggressive["setup_family.entry_band_multiplier"] = 1.1
        aggressive["global.entry_band_risk_fraction"] = 0.1
        aggressive["global.volatility_stop_multiplier"] = 0.2
        overridden_levels = family_adjusted_trade_levels(
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            setup_family="breakout",
            action="long",
            transmission_context_bias="tailwind",
            volatility_score=80.0,
            tuning_config=aggressive,
        )

        self.assertEqual(baseline_levels, (100.0, 100.0, 95.75, 111.2))
        self.assertEqual(overridden_levels, (99.45, 100.55, 95.76, 111.7))

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
            self.assertIn("exploration_campaigns", state_payload)
            self.assertIn("state", state_payload)
            self.assertIsNotNone(state_payload["state"]["active_config_version_id"])
            self.assertEqual(state_payload["exploration_campaigns"][0]["name"], "entry_calibration")

            run_response = await client.post("/api/plan-generation-tuning/run?apply=true")
            self.assertEqual(run_response.status_code, 200)
            run_payload = run_response.json()
            self.assertEqual(run_payload["status"], "queued")
            self.assertEqual(run_payload["job_type"], "plan_generation_tuning")
            self.assertEqual(json.loads(run_payload["artifact_json"])["plan_generation_tuning_request"]["apply"], True)

            runs = await client.get("/api/runs?job_type=plan_generation_tuning&limit=10")
            self.assertEqual(runs.status_code, 200)
            runs_payload = runs.json()
            self.assertGreaterEqual(len(runs_payload), 1)
            self.assertEqual(runs_payload[0]["job_type"], "plan_generation_tuning")

            configs = await client.get("/api/plan-generation-tuning/configs?limit=10")
            self.assertEqual(configs.status_code, 200)
            configs_payload = configs.json()
            self.assertGreaterEqual(configs_payload["total"], 1)

    async def test_route_promotes_a_ranked_eligible_non_winner_candidate(self) -> None:
        active_config = normalize_plan_generation_tuning_config(None)
        winner_config = dict(active_config)
        winner_config["global.actionable_confidence_floor_percent"] = 65.0
        eligible_runner_up_config = dict(active_config)
        eligible_runner_up_config["setup_family.breakout.take_profit_distance_multiplier"] = 1.17

        winner_eval = CandidateEvaluation(
            config=winner_config,
            changed_keys=["global.actionable_confidence_floor_percent"],
            search_actionable_count=10,
            search_win_count=6,
            search_expected_value=1.0,
            search_ambiguous_count=0,
            validation_actionable_count=1,
            validation_win_count=1,
            validation_expected_value=1.0,
            validation_ambiguous_count=0,
        )
        runner_up_eval = CandidateEvaluation(
            config=eligible_runner_up_config,
            changed_keys=["setup_family.breakout.take_profit_distance_multiplier"],
            search_actionable_count=10,
            search_win_count=5,
            search_expected_value=0.8,
            search_ambiguous_count=0,
            validation_actionable_count=10,
            validation_win_count=5,
            validation_expected_value=0.8,
            validation_ambiguous_count=0,
        )
        baseline_eval = CandidateEvaluation(
            config=active_config,
            changed_keys=[],
            search_actionable_count=10,
            search_win_count=4,
            search_expected_value=0.5,
            search_ambiguous_count=0,
            validation_actionable_count=10,
            validation_win_count=4,
            validation_expected_value=0.5,
            validation_ambiguous_count=0,
        )

        def evaluate_side_effect(config, baseline_config, search_records, validation_records):
            if config == active_config:
                return baseline_eval
            if config == winner_config:
                return winner_eval
            if config == eligible_runner_up_config:
                return runner_up_eval
            raise AssertionError("unexpected config")

        session = Session(bind=self.engine)
        try:
            service = PlanGenerationTuningService(session)
            with patch.object(PlanGenerationTuningService, "_candidate_configs", return_value=[active_config, winner_config, eligible_runner_up_config]), patch.object(
                PlanGenerationTuningService, "_refinement_configs", return_value=[]
            ), patch.object(PlanGenerationTuningService, "_evaluate_candidate", side_effect=evaluate_side_effect):
                run = service.run(limit=50)
        finally:
            session.close()

        candidate_rank_2 = next(candidate for candidate in run.candidates if candidate.rank == 2)
        self.assertTrue(candidate_rank_2.promotion_eligible)

        transport = httpx.ASGITransport(app=app)
        with patch.object(PlanGenerationTuningService, "_edge_validation_gate_report", return_value={"label": "demote_or_halt", "reasons": ["negative_realized_pnl"]}):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(f"/api/plan-generation-tuning/runs/{run.id}/candidates/{candidate_rank_2.id}/promote")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["promoted"])
        self.assertEqual(payload["config"]["source"], "promoted_candidate")
        self.assertEqual(payload["config"]["source_candidate_id"], candidate_rank_2.id)

    async def test_route_recoveres_stale_running_tuning_run_with_dead_worker_heartbeat(self) -> None:
        reference_now = datetime(2026, 5, 16, 6, 40, tzinfo=timezone.utc)
        session = Session(bind=self.engine)
        try:
            jobs = JobRepository(session)
            runs = RunRepository(session)
            job = jobs.get_or_create_system_job("plan-generation-tuning", JobType.PLAN_GENERATION_TUNING)
            stale_run = runs.enqueue(job.id or 0, job_type=JobType.PLAN_GENERATION_TUNING)
            worker_id = "worker-stale-test"
            session.add(
                WorkerHeartbeatRecord(
                    worker_id=worker_id,
                    hostname="test-host",
                    pid=12345,
                    status="running",
                    last_heartbeat_at=reference_now - timedelta(minutes=5),
                    started_at=reference_now - timedelta(minutes=5),
                    active_run_id=stale_run.id,
                )
            )
            session.execute(
                update(RunRecord)
                .where(RunRecord.id == stale_run.id)
                .values(
                    status="running",
                    started_at=reference_now - timedelta(minutes=4),
                    lease_expires_at=reference_now + timedelta(minutes=20),
                    worker_id=worker_id,
                )
            )
            session.commit()
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/plan-generation-tuning/run?mode=wide&apply=false")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "queued")
            self.assertNotEqual(payload["id"], stale_run.id)

        session = Session(bind=self.engine)
        try:
            refreshed = RunRepository(session).get_run(stale_run.id or 0)
            self.assertEqual(refreshed.status, "failed")
            self.assertIn("worker_heartbeat_stale", refreshed.timing_json or "")
        finally:
            session.close()


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
