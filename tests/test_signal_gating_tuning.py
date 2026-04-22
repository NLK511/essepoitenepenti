from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from trade_proposer_app.app import app
from trade_proposer_app.config import settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar, RecommendationDecisionSample, RecommendationPlan, RecommendationPlanOutcome, RecommendationSignalGatingTuningRun, TickerSignalSnapshot
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.signal_gating_tuning_runs import RecommendationSignalGatingTuningRunRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.signal_gating_tuning import RecommendationSignalGatingTuningError, RecommendationSignalGatingTuningService


class RecommendationSignalGatingTuningServiceTests(unittest.TestCase):
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

    def _create_benchmark_sample(self, *, ticker: str, direction: str, created_at: datetime, confidence: float = 59.0) -> int:
        snapshot = ContextSnapshotRepository(self.session).create_ticker_signal_snapshot(
            TickerSignalSnapshot(
                ticker=ticker,
                horizon=StrategyHorizon.ONE_WEEK,
                computed_at=created_at,
                direction=direction,
                confidence_percent=confidence,
                attention_score=confidence,
                macro_exposure_score=0.0,
                industry_alignment_score=0.0,
                ticker_sentiment_score=0.0,
                technical_setup_score=0.0,
                catalyst_score=0.0,
                expected_move_score=0.0,
                execution_quality_score=0.0,
            )
        )
        sample = self.sample_repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker=ticker,
                horizon=StrategyHorizon.ONE_WEEK.value,
                action="no_action",
                decision_type="rejected",
                shortlisted=False,
                confidence_percent=confidence,
                calibrated_confidence_percent=confidence,
                setup_family="breakout",
                reviewed_at=created_at,
                ticker_signal_snapshot_id=snapshot.id or 0,
                signal_breakdown={"benchmark_direction": direction},
            )
        )
        bars = [
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=created_at - timedelta(days=1),
                open_price=100.0,
                high_price=100.0,
                low_price=100.0,
                close_price=100.0,
                volume=1000.0,
            ),
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=created_at + timedelta(days=1),
                open_price=100.0,
                high_price=103.5,
                low_price=99.0,
                close_price=102.5,
                volume=1000.0,
            ),
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=created_at + timedelta(days=2),
                open_price=102.5,
                high_price=104.0,
                low_price=101.5,
                close_price=103.0,
                volume=1000.0,
            ),
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=created_at + timedelta(days=3),
                open_price=103.0,
                high_price=105.5,
                low_price=102.0,
                close_price=104.5,
                volume=1000.0,
            ),
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=created_at + timedelta(days=4),
                open_price=104.5,
                high_price=107.0,
                low_price=103.5,
                close_price=106.0,
                volume=1000.0,
            ),
        ]
        HistoricalMarketDataRepository(self.session).upsert_bars(bars)
        return sample.id or 0

    def test_run_persists_best_threshold_and_candidate_results(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self._create_resolved_sample(confidence=67.0, outcome="win", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=65.0, outcome="win", created_at=datetime(2026, 3, 2, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=61.0, outcome="loss", created_at=datetime(2026, 3, 3, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=55.0, outcome="loss", created_at=datetime(2026, 3, 4, tzinfo=timezone.utc))

        run = RecommendationSignalGatingTuningService(self.session).run()

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.objective_name, "signal_gating_tuning_raw_grid")
        self.assertEqual(run.sample_count, 4)
        self.assertEqual(run.resolved_sample_count, 4)
        self.assertGreaterEqual(run.candidate_count, 5)
        self.assertEqual(run.baseline_threshold, 60.0)
        self.assertEqual(run.best_threshold, 64.0)
        self.assertGreater(run.best_score or 0.0, run.baseline_score or 0.0)
        self.assertEqual(run.winning_config["confidence_threshold"], 64.0)
        self.assertEqual(len(run.candidate_results), run.candidate_count)
        self.assertTrue(any(candidate["threshold"] == 64.0 for candidate in run.candidate_results))

        stored_latest = RecommendationSignalGatingTuningService(self.session).describe()["latest_run"]
        self.assertIsNotNone(stored_latest)
        self.assertEqual(stored_latest.best_threshold, 64.0)

    def test_run_with_apply_updates_confidence_threshold_setting(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self._create_resolved_sample(confidence=67.0, outcome="win", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=65.0, outcome="win", created_at=datetime(2026, 3, 2, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=61.0, outcome="loss", created_at=datetime(2026, 3, 3, tzinfo=timezone.utc))

        run = RecommendationSignalGatingTuningService(self.session).run(apply=True)

        self.assertTrue(run.applied)
        self.assertEqual(self.settings_repository.get_confidence_threshold(), 64.0)
        self.assertEqual(run.summary["applied_threshold"], 64.0)
        self.assertIn("shortlist_aggressiveness", run.winning_config)
        self.assertIn("near_miss_gap_cutoff", run.winning_config)

    def test_run_defaults_to_samples_since_latest_applied_tuning(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self._create_resolved_sample(confidence=67.0, outcome="win", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))

        applied_run = RecommendationSignalGatingTuningService(self.session).run(apply=True)
        applied_boundary = (applied_run.completed_at or applied_run.created_at) + timedelta(seconds=1)

        later_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=58.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=applied_boundary,
            )
        )
        self.sample_repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=later_plan.id or 0,
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK.value,
                action="long",
                decision_type="actionable",
                confidence_percent=58.0,
                calibrated_confidence_percent=58.0,
                setup_family="breakout",
                reviewed_at=applied_boundary,
            )
        )
        self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=later_plan.id or 0,
                outcome="expired",
                status="resolved",
                evaluated_at=applied_boundary,
                confidence_bucket="high",
                setup_family="breakout",
            )
        )

        with self.assertRaisesRegex(RecommendationSignalGatingTuningError, "no scoreable win/loss outcomes or benchmark follow-through found for signal gating tuning since"):
            RecommendationSignalGatingTuningService(self.session).run()

        latest_applied = RecommendationSignalGatingTuningService(self.session).describe()["latest_run"]
        self.assertIsNotNone(latest_applied)
        self.assertEqual(applied_run.id, latest_applied.id)

    def test_run_without_applied_history_uses_all_matching_samples(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self._create_resolved_sample(confidence=67.0, outcome="win", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        self._create_resolved_sample(confidence=61.0, outcome="loss", created_at=datetime(2026, 3, 2, tzinfo=timezone.utc))

        run = RecommendationSignalGatingTuningService(self.session).run()

        self.assertEqual(run.sample_count, 2)
        self.assertEqual(run.resolved_sample_count, 2)
        self.assertEqual(run.benchmark_sample_count, 0)
        self.assertEqual(run.scoreable_sample_count, 2)
        self.assertEqual(run.summary["filters"]["sample_window_mode"], "all_history")
        self.assertIsNone(run.summary["filters"]["limit"])

    def test_run_scores_multi_parameter_grid_and_prefers_shortlist_promotion(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        self.settings_repository.set_signal_gating_tuning_config(
            threshold_offset=0.0,
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

        run = RecommendationSignalGatingTuningService(self.session).run()

        self.assertGreaterEqual(run.candidate_count, 100)
        self.assertEqual(run.benchmark_sample_count, 0)
        self.assertEqual(run.scoreable_sample_count, 4)
        self.assertGreater(run.best_score or 0.0, run.baseline_score or 0.0)
        self.assertGreater(run.winning_config["shortlist_aggressiveness"], 0)
        self.assertIn("near_miss_gap_cutoff", run.winning_config)
        self.assertTrue(any(candidate["shortlisted_selected_count"] > 0 for candidate in run.candidate_results))
        self.assertTrue(any(candidate["near_miss_selected_count"] > 0 for candidate in run.candidate_results))
        self.assertTrue(any(candidate["degraded_selected_count"] > 0 for candidate in run.candidate_results))
    def test_run_detects_benchmark_follow_through_for_discarded_signals(self) -> None:
        self.settings_repository.set_confidence_threshold(60.0)
        signal_time = datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc)
        self._create_benchmark_sample(ticker="AAPL", direction="long", created_at=signal_time, confidence=59.0)

        run = RecommendationSignalGatingTuningService(self.session).run()

        self.assertEqual(run.sample_count, 1)
        self.assertEqual(run.resolved_sample_count, 0)
        self.assertEqual(run.benchmark_sample_count, 1)
        self.assertEqual(run.scoreable_sample_count, 1)
        self.assertEqual(run.summary["benchmark_sample_count"], 1)
        self.assertEqual(run.summary["missed_opportunity_count"], 1)
        self.assertEqual(run.summary["good_reject_count"], 0)
        self.assertGreater(run.best_score or 0.0, run.baseline_score or 0.0)
        self.assertTrue(any(candidate["benchmark_selected_count"] > 0 for candidate in run.candidate_results))
        self.assertTrue(any(candidate["benchmark_hit_count"] > 0 for candidate in run.candidate_results))

    def test_repository_filters_samples_by_shortlist_and_context_fields(self) -> None:
        base_time = datetime(2026, 3, 5, tzinfo=timezone.utc)
        long_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=68.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=base_time,
            )
        )
        short_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="short",
                confidence_percent=62.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=105.0,
                take_profit=90.0,
                signal_breakdown={"setup_family": "continuation"},
                computed_at=base_time,
            )
        )
        self.sample_repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=long_plan.id or 0,
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK.value,
                action="long",
                decision_type="actionable",
                shortlisted=True,
                setup_family="breakout",
                transmission_bias="tailwind",
                context_regime="catalyst_active",
                confidence_percent=68.0,
                reviewed_at=base_time,
            )
        )
        self.sample_repository.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=short_plan.id or 0,
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK.value,
                action="short",
                decision_type="rejected",
                shortlisted=False,
                setup_family="continuation",
                transmission_bias="headwind",
                context_regime="headwind_without_dominant_tag",
                confidence_percent=62.0,
                reviewed_at=base_time,
            )
        )

        shortlisted_items = self.sample_repository.list_samples(shortlisted=True)
        self.assertEqual(len(shortlisted_items), 1)
        self.assertEqual(shortlisted_items[0].ticker, "AAPL")
        tailwind_items = self.sample_repository.list_samples(transmission_bias="tailwind")
        self.assertEqual(len(tailwind_items), 1)
        self.assertEqual(tailwind_items[0].ticker, "AAPL")
        headwind_items = self.sample_repository.list_samples(context_regime="headwind_without_dominant_tag")
        self.assertEqual(len(headwind_items), 1)
        self.assertEqual(headwind_items[0].ticker, "MSFT")

    def test_recommendation_calibration_summary_includes_action_buckets(self) -> None:
        base_time = datetime(2026, 3, 6, tzinfo=timezone.utc)
        long_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="AAPL",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=68.0,
                entry_price_low=100.0,
                entry_price_high=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=base_time,
            )
        )
        no_action_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="MSFT",
                horizon=StrategyHorizon.ONE_WEEK,
                action="no_action",
                confidence_percent=42.0,
                computed_at=base_time,
            )
        )
        watchlist_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="NVDA",
                horizon=StrategyHorizon.ONE_WEEK,
                action="watchlist",
                confidence_percent=48.0,
                computed_at=base_time,
            )
        )
        self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=long_plan.id or 0,
                ticker="AAPL",
                action="long",
                outcome="win",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="breakout",
                horizon="1w",
                context_regime="catalyst_active",
                transmission_bias="tailwind",
            )
        )
        self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=no_action_plan.id or 0,
                ticker="MSFT",
                action="no_action",
                outcome="no_action",
                status="resolved",
                confidence_bucket="below_50",
                setup_family="continuation",
                horizon="1w",
                context_regime="headwind_without_dominant_tag",
                transmission_bias="headwind",
            )
        )
        self.outcome_repository.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=watchlist_plan.id or 0,
                ticker="NVDA",
                action="watchlist",
                outcome="watchlist",
                status="resolved",
                confidence_bucket="50_to_64",
                setup_family="continuation",
                horizon="1w",
                context_regime="mixed_context",
                transmission_bias="unknown",
            )
        )

        summary = RecommendationPlanCalibrationService(self.outcome_repository).summarize(limit=20)
        self.assertEqual(summary.total_outcomes, 3)
        self.assertEqual(summary.by_action[0].key, "long")
        self.assertEqual(summary.by_action[0].win_rate_percent, 100.0)
        action_keys = {bucket.key for bucket in summary.by_action}
        self.assertIn("no_action", action_keys)
        self.assertIn("watchlist", action_keys)
        self.assertIsNotNone(summary.calibration_report)
        self.assertEqual(summary.calibration_report.version_label, "confidence-reliability-v1")
        self.assertGreater(summary.calibration_report.sample_count, 0)
        self.assertGreaterEqual(len(summary.calibration_report.bins), 1)


class RecommendationSignalGatingTuningRouteTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_run_endpoint_returns_signal_gating_tuning_run(self) -> None:
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
            response = await client.post("/api/signal-gating-tuning/run?apply=true")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["applied"])
            self.assertEqual(payload["best_threshold"], 64.0)
            self.assertEqual(payload["summary"]["applied_threshold"], 64.0)

            state_response = await client.get("/api/signal-gating-tuning")
            self.assertEqual(state_response.status_code, 200)
            state_payload = state_response.json()
            self.assertEqual(state_payload["current_confidence_threshold"], 64.0)
            self.assertEqual(state_payload["latest_run"]["best_threshold"], 64.0)
            self.assertIn("active_tuning", state_payload)
            self.assertIn("shortlist_aggressiveness", state_payload["active_tuning"])
            self.assertGreaterEqual(state_payload["latest_run"]["benchmark_sample_count"], 0)

            runs_response = await client.get("/api/signal-gating-tuning/runs?limit=5")
            self.assertEqual(runs_response.status_code, 200)
            runs_payload = runs_response.json()
            self.assertGreaterEqual(len(runs_payload["runs"]), 1)
            self.assertEqual(runs_payload["runs"][0]["best_threshold"], 64.0)

    async def test_calibration_report_endpoint_returns_report(self) -> None:
        session = Session(bind=self.engine)
        try:
            plan_repository = RecommendationPlanRepository(session)
            outcome_repository = RecommendationOutcomeRepository(session)
            for index, outcome in enumerate(["win", "loss"], start=1):
                plan = plan_repository.create_plan(
                    RecommendationPlan(
                        ticker="AAPL",
                        horizon=StrategyHorizon.ONE_WEEK,
                        action="long",
                        confidence_percent=65.0 + index,
                        entry_price_low=100.0,
                        entry_price_high=100.0,
                        stop_loss=95.0,
                        take_profit=110.0,
                        signal_breakdown={"setup_family": "breakout"},
                        computed_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                    )
                )
                outcome_repository.upsert_outcome(
                    RecommendationPlanOutcome(
                        recommendation_plan_id=plan.id or 0,
                        ticker="AAPL",
                        action="long",
                        outcome=outcome,
                        status="resolved",
                        evaluated_at=datetime(2026, 3, index, tzinfo=timezone.utc),
                        confidence_bucket="65_to_79",
                        setup_family="breakout",
                        horizon="1w",
                        transmission_bias="tailwind",
                        context_regime="catalyst_active",
                    )
                )
        finally:
            session.close()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/recommendation-outcomes/calibration-report?limit=20")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("calibration_summary", payload)
            self.assertIn("calibration_report", payload)
            self.assertIsNotNone(payload["calibration_report"])
            self.assertGreater(payload["calibration_report"]["sample_count"], 0)

    def test_signal_gating_tuning_run_repository_handles_legacy_schema_without_benchmark_columns(self) -> None:
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_reset_on_return=None,
        )
        Base.metadata.create_all(bind=engine)
        session = Session(bind=engine)
        try:
            session.execute(text("DROP TABLE signal_gating_tuning_runs"))
            session.execute(
                text(
                    """
                    CREATE TABLE signal_gating_tuning_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        objective_name VARCHAR(120) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        applied BOOLEAN NOT NULL,
                        filters_json TEXT NOT NULL,
                        sample_count INTEGER NOT NULL,
                        resolved_sample_count INTEGER NOT NULL,
                        candidate_count INTEGER NOT NULL,
                        baseline_threshold FLOAT,
                        baseline_score FLOAT,
                        best_threshold FLOAT,
                        best_score FLOAT,
                        winning_config_json TEXT NOT NULL,
                        candidate_results_json TEXT NOT NULL,
                        summary_json TEXT NOT NULL,
                        artifact_json TEXT NOT NULL,
                        error_message TEXT NOT NULL,
                        started_at DATETIME,
                        completed_at DATETIME,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
            session.commit()

            repository = RecommendationSignalGatingTuningRunRepository(session)
            created = repository.create_run(
                RecommendationSignalGatingTuningRun(
                    objective_name="signal_gating_tuning_raw_grid",
                    status="completed",
                    applied=False,
                    sample_count=3,
                    resolved_sample_count=2,
                    benchmark_sample_count=7,
                    scoreable_sample_count=9,
                    candidate_count=4,
                    baseline_threshold=60.0,
                    baseline_score=1.25,
                    best_threshold=64.0,
                    best_score=2.5,
                    winning_config={"threshold_offset": 4.0},
                    candidate_results=[{"threshold": 64.0, "score": 2.5}],
                    summary={"sample_count": 3},
                    artifact={"benchmark_summary": {"benchmark_sample_count": 7}},
                    started_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 4, 20, 1, tzinfo=timezone.utc),
                )
            )
            listed = repository.list_runs(limit=10)

            self.assertIsNotNone(created.id)
            self.assertEqual(created.benchmark_sample_count, 0)
            self.assertEqual(created.scoreable_sample_count, 0)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].best_threshold, 64.0)
            self.assertEqual(listed[0].benchmark_sample_count, 0)
            self.assertEqual(listed[0].scoreable_sample_count, 0)
        finally:
            session.close()
            engine.dispose()
