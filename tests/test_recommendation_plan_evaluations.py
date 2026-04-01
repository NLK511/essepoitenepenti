import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar, RecommendationPlan, RecommendationPlanOutcome
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
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
        self.assertEqual(stored[0].transmission_bias_detail["label"], "unknown")
        self.assertEqual(stored[0].context_regime, "mixed_context")
        self.assertEqual(stored[0].context_regime_label, "mixed context")
        self.assertEqual(stored[0].context_regime_detail["label"], "mixed context")
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

    def test_run_evaluation_includes_same_day_daily_bar_after_plan_time(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=100.0,
                entry_price_high=101.0,
                stop_loss=96.0,
                take_profit=106.0,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
            )
        )
        price_history = pd.DataFrame(
            {
                "High": [102.0, 99.0, 99.5],
                "Low": [95.0, 98.0, 98.5],
                "Close": [96.5, 98.5, 99.0],
                "available_at": pd.to_datetime(
                    [
                        "2024-01-01T23:59:59Z",
                        "2024-01-02T23:59:59Z",
                        "2024-01-03T23:59:59Z",
                    ],
                    utc=True,
                ),
            },
            index=pd.to_datetime(
                [
                    "2024-01-01T00:00:00Z",
                    "2024-01-02T00:00:00Z",
                    "2024-01-03T00:00:00Z",
                ],
                utc=True,
            ),
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_recomputes_existing_eog_outcome_with_new_data(self) -> None:
        plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, 18, 888095, tzinfo=timezone.utc),
            )
        )
        self.outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=plan.id or 0,
                ticker="EOG",
                action="long",
                outcome="loss",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="catalyst_follow_through",
                notes="seeded historical result",
            )
        )
        recomputed_price_history = pd.DataFrame(
            {
                "Open": [151.03, 149.0],
                "High": [151.869995, 151.279999],
                "Low": [149.389999, 141.75],
                "Close": [149.889999, 143.369995],
                "available_at": pd.to_datetime(
                    ["2026-03-30T23:59:59Z", "2026-03-31T23:59:59Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z", "2026-03-31T00:00:00Z"], utc=True),
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=recomputed_price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(recommendation_plan_ids=[plan.id or 0])

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "no_entry")
        self.assertEqual(stored[0].status, "open")
        self.assertEqual(stored[0].notes, "Entry zone has not been touched yet.")

    def test_run_evaluation_skips_resolved_plans_during_batch_evaluation(self) -> None:
        open_plan = self.plan_repository.create_plan(
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
        resolved_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="MSFT",
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
        self.outcomes.upsert_outcome(
            RecommendationPlanOutcome(
                recommendation_plan_id=resolved_plan.id or 0,
                ticker="MSFT",
                action="long",
                outcome="loss",
                status="resolved",
                confidence_bucket="65_to_79",
                setup_family="continuation",
                notes="already resolved",
            )
        )
        price_history = pd.DataFrame(
            {
                "High": [107.0],
                "Low": [99.5],
                "Close": [106.5],
                "available_at": pd.to_datetime(["2024-01-02T23:59:59Z"], utc=True),
            },
            index=pd.to_datetime(["2024-01-02T17:00:00Z"], utc=True),
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        stored_aapl = self.outcomes.list_outcomes(ticker="AAPL", limit=10)
        self.assertEqual(stored_aapl[0].outcome, "win")
        stored_msft = self.outcomes.list_outcomes(ticker="MSFT", limit=10)
        self.assertEqual(stored_msft[0].outcome, "loss")
        self.assertEqual(stored_msft[0].status, "resolved")

    def test_run_evaluation_prefers_persisted_intraday_bars_when_available(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=100.0,
                entry_price_high=101.0,
                stop_loss=96.0,
                take_profit=106.0,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc),
            )
        )
        market_data = HistoricalMarketDataRepository(self.session)
        market_data.upsert_bar(
            HistoricalMarketBar(
                ticker="EOG",
                timeframe="1h",
                bar_time=datetime(2024, 1, 1, 15, 30, tzinfo=timezone.utc),
                available_at=datetime(2024, 1, 1, 15, 30, tzinfo=timezone.utc),
                open_price=100.2,
                high_price=101.5,
                low_price=99.8,
                close_price=101.0,
                volume=1000,
                source="fixture",
            )
        )
        market_data.upsert_bar(
            HistoricalMarketBar(
                ticker="EOG",
                timeframe="1h",
                bar_time=datetime(2024, 1, 1, 16, 30, tzinfo=timezone.utc),
                available_at=datetime(2024, 1, 1, 16, 30, tzinfo=timezone.utc),
                open_price=101.0,
                high_price=102.0,
                low_price=95.5,
                close_price=96.0,
                volume=1000,
                source="fixture",
            )
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", side_effect=AssertionError("fallback should not be used")):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertEqual(stored[0].setup_family, "breakout")
        self.assertEqual(stored[0].horizon, "1w")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_counts_gap_through_entry_before_stop_as_loss(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        price_history = pd.DataFrame(
            {
                "Open": [151.03, 149.0],
                "High": [152.18, 151.28],
                "Low": [149.39, 141.75],
                "Close": [149.89, 142.98],
                "available_at": pd.to_datetime(
                    ["2026-03-30T23:59:59Z", "2026-03-31T23:59:59Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z", "2026-03-31T00:00:00Z"], utc=True),
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_flattens_yfinance_multiindex_columns_before_evaluating(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=datetime(2026, 3, 30, 21, 0, tzinfo=timezone.utc),
            )
        )
        price_history = pd.DataFrame(
            {
                ("Adj Close", "EOG"): [149.889999, 143.369995],
                ("Close", "EOG"): [149.889999, 143.369995],
                ("High", "EOG"): [152.0, 151.279999],
                ("Low", "EOG"): [149.389999, 141.75],
                ("Open", "EOG"): [151.029999, 149.0],
                ("Volume", "EOG"): [1234567, 2345678],
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z", "2026-03-31T00:00:00Z"], utc=True),
        )
        price_history.columns = pd.MultiIndex.from_tuples(price_history.columns, names=["Price", "Ticker"])

        with patch("trade_proposer_app.services.recommendation_plan_evaluations.yf.download", return_value=price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation()

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_uses_intraday_history_during_us_market_hours(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=66.11,
                entry_price_low=151.1839,
                entry_price_high=151.1839,
                stop_loss=148.4832,
                take_profit=155.3656,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc),
            )
        )

        def fake_download(ticker: str, start_date: datetime, end_date: datetime, *, intraday_only: bool = False) -> pd.DataFrame:
            self.assertTrue(intraday_only)
            self.assertEqual(ticker, "EOG")
            return pd.DataFrame(
                {
                    "Open": [150.54, 150.63, 150.51],
                    "High": [150.78, 150.73, 150.57],
                    "Low": [150.52, 150.32, 150.01],
                    "Close": [150.57, 150.52, 150.12],
                    "available_at": pd.to_datetime(
                        ["2026-03-31T15:05:00Z", "2026-03-31T15:10:00Z", "2026-03-31T15:15:00Z"],
                        utc=True,
                    ),
                },
                index=pd.to_datetime(
                    ["2026-03-31T15:00:00Z", "2026-03-31T15:05:00Z", "2026-03-31T15:10:00Z"],
                    utc=True,
                ),
            )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", side_effect=fake_download):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(
                as_of=datetime(2026, 3, 31, 15, 30, tzinfo=timezone.utc)
            )

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.pending_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "no_entry")
        self.assertFalse(stored[0].entry_touched)
        self.assertIsNone(stored[0].stop_loss_hit)
        self.assertIsNone(stored[0].take_profit_hit)

    def test_run_evaluation_uses_daily_history_for_prior_sessions_and_intraday_for_current_session(self) -> None:
        previous_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=72.0,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "breakout"},
                computed_at=datetime(2026, 3, 30, 23, 0, tzinfo=timezone.utc),
            )
        )
        current_plan = self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=66.11,
                entry_price_low=151.1839,
                entry_price_high=151.1839,
                stop_loss=148.4832,
                take_profit=155.3656,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc),
            )
        )
        daily_history = pd.DataFrame(
            {
                "Open": [151.03, 149.0],
                "High": [152.18, 151.28],
                "Low": [148.75, 141.75],
                "Close": [150.98, 142.98],
                "available_at": pd.to_datetime(
                    ["2026-03-30T23:59:59Z", "2026-03-31T23:59:59Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z", "2026-03-31T00:00:00Z"], utc=True),
        )
        intraday_history = pd.DataFrame(
            {
                "Open": [150.54, 150.63, 150.51],
                "High": [151.20, 156.10, 156.25],
                "Low": [150.52, 150.32, 150.01],
                "Close": [150.57, 155.70, 155.90],
                "available_at": pd.to_datetime(
                    ["2026-03-31T15:05:00Z", "2026-03-31T15:10:00Z", "2026-03-31T15:15:00Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(
                ["2026-03-31T15:00:00Z", "2026-03-31T15:05:00Z", "2026-03-31T15:10:00Z"],
                utc=True,
            ),
        )

        def fake_download(ticker: str, start_date: datetime, end_date: datetime, *, intraday_only: bool = False) -> pd.DataFrame:
            self.assertEqual(ticker, "EOG")
            return intraday_history if intraday_only else daily_history

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", side_effect=fake_download):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(
                as_of=datetime(2026, 3, 31, 15, 30, tzinfo=timezone.utc)
            )

        self.assertEqual(result.evaluated_recommendation_plans, 2)
        self.assertEqual(result.win_recommendation_plan_outcomes, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        outcome_by_plan_id = {item.recommendation_plan_id: item.outcome for item in stored}
        self.assertEqual(outcome_by_plan_id[previous_plan.id or 0], "loss")
        self.assertEqual(outcome_by_plan_id[current_plan.id or 0], "win")

    def test_run_evaluation_uses_daily_history_after_market_close_for_same_day_plans(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        daily_history = pd.DataFrame(
            {
                "Open": [151.03, 149.0],
                "High": [152.18, 151.279999],
                "Low": [148.75, 141.75],
                "Close": [150.98, 143.369995],
                "available_at": pd.to_datetime(
                    ["2026-03-30T23:59:59Z", "2026-03-31T23:59:59Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z", "2026-03-31T00:00:00Z"], utc=True),
        )
        intraday_history = pd.DataFrame(
            {
                "Open": [150.54, 150.63, 150.51],
                "High": [150.78, 150.73, 150.57],
                "Low": [150.52, 150.32, 150.01],
                "Close": [150.57, 150.52, 150.12],
                "available_at": pd.to_datetime(
                    ["2026-03-30T15:05:00Z", "2026-03-30T15:10:00Z", "2026-03-30T15:15:00Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(
                ["2026-03-30T15:00:00Z", "2026-03-30T15:05:00Z", "2026-03-30T15:10:00Z"],
                utc=True,
            ),
        )

        def fake_download(ticker: str, start_date: datetime, end_date: datetime, *, intraday_only: bool = False) -> pd.DataFrame:
            self.assertEqual(ticker, "EOG")
            return intraday_history if intraday_only else daily_history

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", side_effect=fake_download):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(
                as_of=datetime(2026, 3, 30, 21, 30, tzinfo=timezone.utc)
            )

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_allows_same_day_daily_bar_fallback_after_close_even_when_available_at_is_midnight(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        daily_history = pd.DataFrame(
            {
                "Open": [151.03],
                "High": [152.18],
                "Low": [148.75],
                "Close": [150.98],
                "available_at": pd.to_datetime(["2026-03-30T00:00:00Z"], utc=True),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z"], utc=True),
        )

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=daily_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(
                as_of=datetime(2026, 3, 30, 21, 30, tzinfo=timezone.utc)
            )

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_does_not_fall_back_to_daily_history_when_intraday_history_is_missing(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc),
            )
        )
        daily_history = pd.DataFrame(
            {
                "Open": [151.03, 149.0],
                "High": [152.18, 151.279999],
                "Low": [148.75, 141.75],
                "Close": [150.98, 143.369995],
                "available_at": pd.to_datetime(
                    ["2026-03-30T23:59:59Z", "2026-03-31T23:59:59Z"],
                    utc=True,
                ),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z", "2026-03-31T00:00:00Z"], utc=True),
        )
        empty_intraday = pd.DataFrame(columns=["Open", "High", "Low", "Close", "available_at"])

        def fake_download(ticker: str, start_date: datetime, end_date: datetime, *, intraday_only: bool = False) -> pd.DataFrame:
            self.assertEqual(ticker, "EOG")
            return empty_intraday if intraday_only else daily_history

        with patch.object(RecommendationPlanEvaluationService, "_download_price_history", side_effect=fake_download):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(
                as_of=datetime(2026, 3, 31, 15, 30, tzinfo=timezone.utc)
            )

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.pending_recommendation_plan_outcomes, 1)
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "pending")
        self.assertEqual(stored[0].status, "open")
        self.assertEqual(stored[0].notes, "No price history available for evaluation.")

    def test_run_evaluation_falls_back_to_yfinance_when_persisted_daily_history_is_incomplete(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        persisted_history = pd.DataFrame(
            {
                "Open": [151.03],
                "High": [152.18],
                "Low": [148.75],
                "Close": [150.98],
                "available_at": pd.to_datetime(["2026-03-30T23:59:59Z"], utc=True),
            },
            index=pd.to_datetime(["2026-03-30T00:00:00Z"], utc=True),
        )
        downloaded_history = pd.DataFrame(
            {
                "Open": [151.03],
                "High": [152.18],
                "Low": [148.75],
                "Close": [150.98],
                "available_at": pd.to_datetime(["2026-03-31T23:59:59Z"], utc=True),
            },
            index=pd.to_datetime(["2026-03-31T00:00:00Z"], utc=True),
        )
        with patch.object(RecommendationPlanEvaluationService, "_load_persisted_price_history", return_value=persisted_history) as persisted_mock:
            with patch.object(RecommendationPlanEvaluationService, "_download_price_history", return_value=downloaded_history) as download_mock:
                result = RecommendationPlanEvaluationService(self.session).run_evaluation(as_of=datetime(2026, 3, 31, 21, 18, 53, 29509, tzinfo=timezone.utc))

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        persisted_mock.assert_called_once()
        download_mock.assert_called_once()
        stored = self.outcomes.list_outcomes(ticker="EOG", limit=10)
        self.assertEqual(stored[0].outcome, "loss")
        self.assertTrue(stored[0].entry_touched)
        self.assertTrue(stored[0].stop_loss_hit)
        self.assertFalse(stored[0].take_profit_hit)

    def test_run_evaluation_uses_as_of_as_the_price_history_upper_bound(self) -> None:
        self.plan_repository.create_plan(
            RecommendationPlan(
                ticker="EOG",
                horizon=StrategyHorizon.ONE_WEEK,
                action="long",
                confidence_percent=67.95,
                entry_price_low=151.8925,
                entry_price_high=151.8925,
                stop_loss=149.0889,
                take_profit=156.2066,
                signal_breakdown={"setup_family": "catalyst_follow_through"},
                computed_at=datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc),
            )
        )
        captured: list[tuple[datetime, datetime, bool]] = []

        def fake_load_price_history(
            ticker: str,
            start_date: datetime,
            end_date: datetime,
            *,
            intraday_only: bool = False,
            require_full_coverage: bool = False,
            plan_ids: list[int] | None = None,
        ) -> pd.DataFrame:
            self.assertEqual(ticker, "EOG")
            captured.append((start_date, end_date, intraday_only))
            return pd.DataFrame(
                {
                    "Open": [151.03],
                    "High": [152.18],
                    "Low": [148.75],
                    "Close": [150.98],
                    "available_at": pd.to_datetime(["2026-03-30T23:59:59Z"], utc=True),
                },
                index=pd.to_datetime(["2026-03-30T00:00:00Z"], utc=True),
            )

        as_of = datetime(2026, 3, 30, 21, 30, tzinfo=timezone.utc)
        with patch.object(RecommendationPlanEvaluationService, "_load_price_history", side_effect=fake_load_price_history):
            result = RecommendationPlanEvaluationService(self.session).run_evaluation(as_of=as_of)

        self.assertEqual(result.evaluated_recommendation_plans, 1)
        self.assertEqual(result.loss_recommendation_plan_outcomes, 1)
        self.assertEqual(len(captured), 1)
        _, end_date, intraday_only = captured[0]
        self.assertFalse(intraday_only)
        self.assertEqual(end_date, as_of)

    def test_evaluate_plan_matrix_covers_core_entry_stop_take_combinations(self) -> None:
        service = RecommendationPlanEvaluationService(self.session)
        computed_at = datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc)

        def frame(rows: list[tuple[str, float, float, float, float, str]]) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "Open": [row[1] for row in rows],
                    "High": [row[2] for row in rows],
                    "Low": [row[3] for row in rows],
                    "Close": [row[4] for row in rows],
                    "available_at": pd.to_datetime([row[5] for row in rows], utc=True),
                },
                index=pd.to_datetime([row[0] for row in rows], utc=True),
            )

        cases = [
            {
                "name": "long no entry",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 96.0,
                "take_profit": 106.0,
                "rows": [("2026-03-31T00:00:00Z", 102.0, 103.0, 101.5, 102.5, "2026-03-31T23:59:59Z")],
                "expected_outcome": "no_entry",
                "expected_status": "open",
                "entry_touched": False,
                "stop_loss_hit": None,
                "take_profit_hit": None,
            },
            {
                "name": "long entry only open",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 96.0,
                "take_profit": 106.0,
                "rows": [("2026-03-31T00:00:00Z", 100.2, 101.2, 100.1, 100.9, "2026-03-31T23:59:59Z")],
                "expected_outcome": "open",
                "expected_status": "open",
                "entry_touched": True,
                "stop_loss_hit": False,
                "take_profit_hit": False,
            },
            {
                "name": "long stop before take",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 96.0,
                "take_profit": 106.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 101.0, 95.5, 96.5, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": False,
            },
            {
                "name": "long take before stop",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 96.0,
                "take_profit": 106.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 106.5, 100.1, 106.0, "2026-03-31T23:59:59Z")],
                "expected_outcome": "win",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": False,
                "take_profit_hit": True,
            },
            {
                "name": "long both same bar",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 96.0,
                "take_profit": 106.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 107.0, 95.0, 100.0, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": True,
            },
            {
                "name": "long gap through entry then stop",
                "action": "long",
                "entry_low": 151.8925,
                "entry_high": 151.8925,
                "stop_loss": 149.0889,
                "take_profit": 156.2066,
                "rows": [("2026-03-31T00:00:00Z", 149.0, 152.18, 148.75, 150.98, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": False,
            },
            {
                "name": "long no stop only take",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": None,
                "take_profit": 106.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 106.5, 100.2, 106.0, "2026-03-31T23:59:59Z")],
                "expected_outcome": "win",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": None,
                "take_profit_hit": True,
            },
            {
                "name": "long no take only stop",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 96.0,
                "take_profit": None,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 101.0, 95.8, 96.2, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": None,
            },
            {
                "name": "long no stop no take",
                "action": "long",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": None,
                "take_profit": None,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 101.0, 100.1, 100.6, "2026-03-31T23:59:59Z")],
                "expected_outcome": "open",
                "expected_status": "open",
                "entry_touched": True,
                "stop_loss_hit": None,
                "take_profit_hit": None,
            },
            {
                "name": "short no entry",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 98.0, 99.0, 97.5, 98.5, "2026-03-31T23:59:59Z")],
                "expected_outcome": "no_entry",
                "expected_status": "open",
                "entry_touched": False,
                "stop_loss_hit": None,
                "take_profit_hit": None,
            },
            {
                "name": "short entry only open",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 100.8, 101.0, 100.1, 100.4, "2026-03-31T23:59:59Z")],
                "expected_outcome": "open",
                "expected_status": "open",
                "entry_touched": True,
                "stop_loss_hit": False,
                "take_profit_hit": False,
            },
            {
                "name": "short stop before take",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 104.5, 99.8, 103.8, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": False,
            },
            {
                "name": "short take before stop",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 101.5, 95.5, 96.2, "2026-03-31T23:59:59Z")],
                "expected_outcome": "win",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": False,
                "take_profit_hit": True,
            },
            {
                "name": "short both same bar",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 104.5, 95.0, 100.0, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": True,
            },
            {
                "name": "short gap through entry then stop",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 104.5, 105.0, 95.5, 101.0, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": True,
            },
            {
                "name": "short no stop only take",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": None,
                "take_profit": 96.0,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 101.0, 95.5, 96.0, "2026-03-31T23:59:59Z")],
                "expected_outcome": "win",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": None,
                "take_profit_hit": True,
            },
            {
                "name": "short no take only stop",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": 104.0,
                "take_profit": None,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 104.5, 99.8, 103.8, "2026-03-31T23:59:59Z")],
                "expected_outcome": "loss",
                "expected_status": "resolved",
                "entry_touched": True,
                "stop_loss_hit": True,
                "take_profit_hit": None,
            },
            {
                "name": "short no stop no take",
                "action": "short",
                "entry_low": 100.0,
                "entry_high": 101.0,
                "stop_loss": None,
                "take_profit": None,
                "rows": [("2026-03-31T00:00:00Z", 100.5, 101.0, 100.2, 100.4, "2026-03-31T23:59:59Z")],
                "expected_outcome": "open",
                "expected_status": "open",
                "entry_touched": True,
                "stop_loss_hit": None,
                "take_profit_hit": None,
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                plan = RecommendationPlan(
                    ticker="EOG",
                    horizon=StrategyHorizon.ONE_WEEK,
                    action=case["action"],
                    confidence_percent=72.0,
                    entry_price_low=case["entry_low"],
                    entry_price_high=case["entry_high"],
                    stop_loss=case["stop_loss"],
                    take_profit=case["take_profit"],
                    signal_breakdown={"setup_family": "matrix"},
                    computed_at=computed_at,
                )
                outcome = service._evaluate_plan(plan, frame(case["rows"]), run_id=None)

                self.assertEqual(outcome.outcome, case["expected_outcome"])
                self.assertEqual(outcome.status, case["expected_status"])
                self.assertEqual(outcome.entry_touched, case["entry_touched"])
                self.assertEqual(bool(outcome.stop_loss_hit), bool(case["stop_loss_hit"]))
                self.assertEqual(bool(outcome.take_profit_hit), bool(case["take_profit_hit"]))


if __name__ == "__main__":
    unittest.main()
