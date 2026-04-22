"""
Comprehensive test suite for TickerDeepAnalysisService.

Design principles:
  - Verify exact arithmetic for price levels (entry, stop, take profit).
  - Verify confidence score weighting and quality capping.
  - Verify setup classification logic (momentum and RSI triggers).
  - Verify feature vector normalization.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

import pandas as pd

from trade_proposer_app.domain.enums import RecommendationDirection
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService


class TickerDeepAnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from trade_proposer_app.services.proposals import ProposalService
        self.proposal_service = Mock(spec=ProposalService)
        self.taxonomy_service = Mock()
        self.taxonomy_service.get_ticker_profile.return_value = {"sector": "Technology"}
        self.taxonomy_service.get_ticker_relationships.return_value = []
        self.taxonomy_service.get_transmission_window_definition.return_value = None
        self.taxonomy_service.get_analysis_slice_label.side_effect = lambda value: str(value)
        self.taxonomy_service.get_transmission_tag_definition.return_value = None
        self.taxonomy_service.get_transmission_driver_definition.return_value = None
        self.taxonomy_service.get_transmission_channel_definition.return_value = None
        self.taxonomy_service.get_transmission_conflict_definition.return_value = None
        self.taxonomy_service.get_context_regime_definition.return_value = None
        self.taxonomy_service.get_transmission_bias_definition.return_value = None
        # Ensure context passthrough for enrichment
        self.proposal_service._apply_news_context.side_effect = lambda ctx, t, as_of=None: ctx
        self.service = TickerDeepAnalysisService(self.proposal_service, taxonomy_service=self.taxonomy_service)

    # ─── Price Level Arithmetic ───────────────────────────────────────────────

    def test_suggest_price_levels_long_with_clamped_stop(self) -> None:
        """
        Verify LONG price levels.
        Inputs: price=100, atr=1.0, risk_stop_offset=0.2 (low volatility)
        
        Calculation:
          base_stop = atr = 1.0
          adjusted_stop = 1.0 + 0.2 = 1.2
          min_stop = max(100*0.005, 1.0*0.5, 0.01) = max(0.5, 0.5, 0.01) = 0.5
          max_stop = 100*0.03 = 3.0
          stop_distance = 1.2 (within bounds 0.5 - 3.0)
          
          raw_tp = 1.2 * 1.5 + (0.0 * 0.5) = 1.8  (assuming risk_tp_offset=0)
          min_tp = max(1.2 * 1.1, 100*0.0075, 0.01) = max(1.32, 0.75, 0.01) = 1.32
          tp_distance = 1.8 (within bounds)
          
          entry = 100.0 (assuming adjustment=0)
          stop = 100.0 - 1.2 = 98.8
          take = 100.0 + 1.8 = 101.8
        """
        aggregations = {
            "risk_stop_offset": 0.2,
            "risk_take_profit_offset": 0.0,
            "entry_adjustment": 100.0
        }
        entry, stop, take = self.service._suggest_price_levels(
            RecommendationDirection.LONG, price=100.0, atr=1.0, aggregations=aggregations
        )
        self.assertEqual(entry, 100.0)
        self.assertEqual(stop, 98.8)
        self.assertEqual(take, 101.8)

    def test_suggest_price_levels_short_with_min_RR_clamp(self) -> None:
        """
        Verify SHORT price levels and minimum R:R clamp.
        Calculation:
          price=100, atr=2.0, risk_stop_offset=5.0 (extreme risk)
          base_stop = 2.0
          adjusted_stop = 2.0 + 5.0 = 7.0
          max_stop = 100 * 0.03 = 3.0
          stop_distance = 3.0 (clamped to max)
          
          raw_tp = 3.0 * 1.5 = 4.5
          take = 100 - 4.5 = 95.5
        """
        aggregations = {
            "risk_stop_offset": 5.0,
            "risk_take_profit_offset": 0.0,
            "entry_adjustment": 100.0
        }
        entry, stop, take = self.service._suggest_price_levels(
            RecommendationDirection.SHORT, price=100.0, atr=2.0, aggregations=aggregations
        )
        self.assertEqual(stop, 103.0) # 100 + 3.0
        self.assertEqual(take, 95.5)  # 100 - 4.5

    # ─── Confidence & Quality ─────────────────────────────────────────────────

    def test_compose_confidence_applies_data_quality_cap(self) -> None:
        """
        Verify weighted confidence and quality cap.
        Weighted components sum to 80.
        Data quality cap of 0.5 (50%).
        Result = 80 * 0.5 = 40.
        """
        components = {
            "context_confidence": 80.0,
            "directional_confidence": 80.0,
            "catalyst_confidence": 80.0,
            "technical_clarity": 80.0,
            "execution_clarity": 80.0,
            "data_quality_cap": 50.0 # 50% multiplier
        }
        # 80 * (0.18+0.3+0.14+0.2+0.18) = 80 * 1.0 = 80.0
        # 80 * 0.5 = 40.0
        result = self.service._compose_confidence(components)
        self.assertEqual(result, 40.0)

    def test_compose_confidence_clamps_to_95(self) -> None:
        """System never reports 100% confidence."""
        components = {k: 100.0 for k in ["context_confidence", "directional_confidence", "catalyst_confidence", "technical_clarity", "execution_clarity", "data_quality_cap"]}
        result = self.service._compose_confidence(components)
        self.assertEqual(result, 95.0)

    def test_build_confidence_components_penalizes_problems(self) -> None:
        """Problems in context should reduce the data_quality_cap."""
        context = {"problems": ["p1", "p2"], "news_feed_errors": ["e1"]}
        # cap = 1.0 - min(0.7, (2 * 0.12) + (1 * 0.1)) = 1.0 - (0.24 + 0.1) = 0.66
        # 0.66 * 100 = 66.0
        comps = self.service._build_confidence_components(context, RecommendationDirection.LONG)
        self.assertEqual(comps["data_quality_cap"], 66.0)

    def test_build_confidence_components_reward_relative_strength_and_volume_confirmation(self) -> None:
        base = self.service._build_confidence_components(
            {"momentum_medium": 0.06, "momentum_short": 0.03, "rsi": 56, "price_above_sma50": 1, "price_above_sma200": 1},
            RecommendationDirection.LONG,
        )
        boosted = self.service._build_confidence_components(
            {
                "momentum_medium": 0.06,
                "momentum_short": 0.03,
                "rsi": 56,
                "price_above_sma50": 1,
                "price_above_sma200": 1,
                "rel_return_5d_vs_spy": 0.03,
                "rel_return_20d_vs_spy": 0.04,
                "rel_return_5d_vs_sector": 0.02,
                "rel_return_20d_vs_sector": 0.03,
                "volume_ratio_20": 1.4,
                "dollar_volume_ratio_20": 1.5,
            },
            RecommendationDirection.LONG,
        )
        self.assertGreater(boosted["directional_confidence"], base["directional_confidence"])
        self.assertGreater(boosted["technical_clarity"], base["technical_clarity"])
        self.assertGreater(boosted["execution_clarity"], base["execution_clarity"])

    # ─── Setup Classification ─────────────────────────────────────────────────

    def test_classify_setup_breakout(self) -> None:
        """Breakout: Long + momentum_short > 0.04 + RSI >= 60."""
        context = {
            "momentum_short": 0.05,
            "rsi": 65,
            "momentum_medium": 0,
            "news_item_count": 0
        }
        setup = self.service._classify_setup(context, {}, RecommendationDirection.LONG)
        self.assertEqual(setup, "breakout")

    def test_classify_setup_mean_reversion(self) -> None:
        """Mean Reversion: Long + RSI < 40."""
        context = {
            "momentum_short": 0,
            "rsi": 35,
            "momentum_medium": 0,
            "news_item_count": 0
        }
        setup = self.service._classify_setup(context, {}, RecommendationDirection.LONG)
        self.assertEqual(setup, "mean_reversion")

    def test_classify_setup_continuation_with_relative_strength_confirmation(self) -> None:
        context = {
            "momentum_medium": 0.06,
            "momentum_short": 0.02,
            "rsi": 58,
            "news_item_count": 0,
            "rel_return_5d_vs_spy": 0.02,
            "rel_return_20d_vs_spy": 0.03,
            "rel_return_5d_vs_sector": 0.015,
            "rel_return_20d_vs_sector": 0.02,
            "volume_ratio_20": 1.2,
            "dollar_volume_ratio_20": 1.25,
        }
        setup = self.service._classify_setup(context, {"direction_score": 0.54}, RecommendationDirection.LONG)
        self.assertEqual(setup, "continuation")

    def test_classify_setup_breakout_with_relative_strength_confirmation(self) -> None:
        context = {
            "momentum_short": 0.035,
            "momentum_medium": 0.03,
            "rsi": 56,
            "news_item_count": 0,
            "rel_return_5d_vs_spy": 0.02,
            "rel_return_20d_vs_spy": 0.025,
            "rel_return_5d_vs_sector": 0.02,
            "rel_return_20d_vs_sector": 0.02,
            "volume_ratio_20": 1.3,
            "dollar_volume_ratio_20": 1.35,
        }
        setup = self.service._classify_setup(context, {}, RecommendationDirection.LONG)
        self.assertEqual(setup, "breakout")

    def test_classify_setup_catalyst(self) -> None:
        """Catalyst: news >= 4 + sentiment >= 0.2."""
        context = {
            "news_item_count": 4,
            "ticker_sentiment_score": 0.25,
            "rsi": 50
        }
        setup = self.service._classify_setup(context, {}, RecommendationDirection.LONG)
        self.assertEqual(setup, "catalyst_follow_through")

    # ─── Normalization ────────────────────────────────────────────────────────

    def test_normalize_value_clamps_to_unit_interval(self) -> None:
        self.assertEqual(self.service._normalize_value(150, (100, 200)), 0.5)
        self.assertEqual(self.service._normalize_value(250, (100, 200)), 1.0)
        self.assertEqual(self.service._normalize_value(50, (100, 200)), 0.0)

    def test_normalize_value_handles_zero_range(self) -> None:
        # If min == max, return 0.5 (neutral)
        self.assertEqual(self.service._normalize_value(100, (100, 100)), 0.5)

    def test_build_reference_features_computes_relative_strength_and_volume_confirmation(self) -> None:
        dates = pd.date_range("2026-01-01", periods=25, freq="D")
        ticker_history = pd.DataFrame({
            "Close": [100.0 + i for i in range(25)],
            "Volume": [1000.0] * 24 + [2000.0],
        }, index=dates)
        spy_history = pd.DataFrame({
            "Close": [100.0 + (i * 0.2) for i in range(25)],
            "Volume": [1000.0] * 25,
        }, index=dates)
        sector_history = pd.DataFrame({
            "Close": [100.0 + (i * 0.4) for i in range(25)],
            "Volume": [1000.0] * 25,
        }, index=dates)

        def fetch_history(symbol: str, as_of=None):
            return {"SPY": spy_history, "XLK": sector_history}[symbol]

        self.proposal_service._fetch_price_history.side_effect = fetch_history
        features = self.service._build_reference_features("AAPL", ticker_history, {"sector": "Technology"})

        self.assertGreater(features["rel_return_5d_vs_spy"], 0.0)
        self.assertGreater(features["rel_return_20d_vs_spy"], 0.0)
        self.assertGreater(features["rel_return_5d_vs_sector"], 0.0)
        self.assertGreater(features["rel_return_20d_vs_sector"], 0.0)
        expected_volume_ratio = float(ticker_history["Volume"].iloc[-1]) / float(ticker_history["Volume"].tail(20).mean())
        expected_dollar_volume_ratio = float((ticker_history["Close"] * ticker_history["Volume"]).iloc[-1]) / float((ticker_history["Close"] * ticker_history["Volume"]).tail(20).mean())
        self.assertAlmostEqual(features["volume_ratio_20"], expected_volume_ratio, places=5)
        self.assertAlmostEqual(features["dollar_volume_ratio_20"], expected_dollar_volume_ratio, places=5)
        self.assertEqual(features["reference_features"]["sector_etf_symbol"], "XLK")
        self.assertTrue(features["reference_features"]["benchmark_available"])
        self.assertTrue(features["reference_features"]["sector_available"])

    def test_build_reference_features_falls_back_cleanly_when_sector_mapping_missing(self) -> None:
        dates = pd.date_range("2026-01-01", periods=25, freq="D")
        ticker_history = pd.DataFrame({
            "Close": [100.0 + i for i in range(25)],
            "Volume": [1000.0] * 25,
        }, index=dates)
        spy_history = pd.DataFrame({
            "Close": [100.0 + (i * 0.2) for i in range(25)],
            "Volume": [1000.0] * 25,
        }, index=dates)

        self.proposal_service._fetch_price_history.side_effect = lambda symbol, as_of=None: spy_history if symbol == "SPY" else None
        features = self.service._build_reference_features("AAPL", ticker_history, {"sector": "Unknown Sector"})

        self.assertEqual(features["rel_return_5d_vs_sector"], 0.0)
        self.assertEqual(features["rel_return_20d_vs_sector"], 0.0)
        self.assertIsNone(features["reference_features"]["sector_etf_symbol"])
        self.assertFalse(features["reference_features"]["sector_available"])
        self.assertIn("sector ETF mapping unavailable", " ".join(features["reference_features"]["notes"]))

    def test_reference_history_is_cached_per_symbol_and_as_of(self) -> None:
        dates = pd.date_range("2026-01-01", periods=25, freq="D")
        ticker_history = pd.DataFrame({
            "Close": [100.0 + i for i in range(25)],
            "Volume": [1000.0] * 25,
        }, index=dates)
        reference_history = pd.DataFrame({
            "Close": [100.0 + (i * 0.2) for i in range(25)],
            "Volume": [1000.0] * 25,
        }, index=dates)

        self.proposal_service._fetch_price_history.side_effect = lambda symbol, as_of=None: reference_history

        first = self.service._safe_fetch_reference_history("SPY", as_of=None, notes=[])
        second = self.service._safe_fetch_reference_history("SPY", as_of=None, notes=[])

        self.assertIs(first, second)
        self.assertEqual(self.proposal_service._fetch_price_history.call_count, 1)

    # ─── End-to-End Integration (Mocked) ──────────────────────────────────────

    def test_analyze_produces_valid_run_output(self) -> None:
        # Mock history with enough rows for indicators
        dates = pd.date_range("2026-01-01", periods=250, freq="D")
        history = pd.DataFrame({
            "Open": [100.0] * 250,
            "High": [105.0] * 250,
            "Low": [95.0] * 250,
            "Close": [102.0] * 250,
            "Volume": [1000] * 250
        }, index=dates)
        benchmark = pd.DataFrame({
            "Open": [100.0] * 250,
            "High": [101.0] * 250,
            "Low": [99.0] * 250,
            "Close": [100.0 + (i * 0.1) for i in range(250)],
            "Volume": [900] * 250,
        }, index=dates)
        sector = pd.DataFrame({
            "Open": [100.0] * 250,
            "High": [101.5] * 250,
            "Low": [99.0] * 250,
            "Close": [100.0 + (i * 0.15) for i in range(250)],
            "Volume": [950] * 250,
        }, index=dates)

        def fetch_history(symbol: str, as_of=None):
            return {"AAPL": history, "SPY": benchmark, "XLK": sector}[symbol]

        self.proposal_service._fetch_price_history.side_effect = fetch_history
        self.proposal_service._last_price_history_fetch_diagnostics = {"source": "remote", "remote_attempt_count": 1, "selected_bar_count": 250}

        output = self.service.analyze("AAPL")

        self.assertEqual(output.recommendation.ticker, "AAPL")
        self.assertIn("AAPL", output.diagnostics.analysis_json)

        # Verify JSON diagnostics
        analysis = json.loads(output.diagnostics.analysis_json)
        self.assertIn("technical", analysis)
        self.assertIn("feature_vector", analysis)
        self.assertEqual(analysis["ticker_deep_analysis"]["price_history"]["source"], "remote")
        self.assertIn("rel_return_5d_vs_spy", analysis["technical"])
        self.assertIn("volume_ratio_20", analysis["technical"])
        self.assertEqual(analysis["technical"]["reference_features"]["sector_etf_symbol"], "XLK")

if __name__ == "__main__":
    unittest.main()
