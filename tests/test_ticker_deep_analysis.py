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

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService




def _neutral_market_intelligence_service() -> Mock:
    service = Mock()
    service.analyze.return_value = json.loads(
        """
        {
          "ticker": "AAPL",
          "as_of": "2026-05-03T00:00:00+00:00",
          "source_set": [],
          "coverage_status": "ok",
          "freshness_status": "fresh",
          "event_intelligence": {"available": false, "warnings": [], "conflict_flags": []},
          "options_intelligence": {"available": false, "warnings": [], "conflict_flags": []},
          "analyst_intelligence": {"available": false, "warnings": [], "conflict_flags": []},
          "confidence_contribution": {"event": 0.0, "options": 0.0, "analyst": 0.0, "combined": 0.0},
          "conflict_flags": [],
          "warnings": [],
          "provider_diagnostics": {"source_name": "mock", "provider_keys": [], "info_available": false, "errors": []},
          "raw_payload_refs": {},
          "summary": "Market intelligence unavailable."
        }
        """
    )
    service.summarize.return_value = "Market intelligence unavailable."
    return service

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
        self.market_intelligence_service = _neutral_market_intelligence_service()
        self.service = TickerDeepAnalysisService(
            self.proposal_service,
            taxonomy_service=self.taxonomy_service,
            market_intelligence_service=self.market_intelligence_service,
        )

    def test_analysis_payload_service_matches_compatibility_wrapper(self) -> None:
        context = {
            "summary_text": "sample summary",
            "summary_method": "stub",
            "summary_backend": "local",
            "summary_model": "test-model",
            "summary_runtime_seconds": 0.1,
            "summary_metadata": {"k": "v"},
            "news_digest": "digest",
            "news_item_count": 2,
            "context_count": 1,
            "news_point_count": 3,
            "news_feeds_used": ["feed-a"],
            "news_feed_errors": ["feed-b failed"],
            "news_items": [{"title": "item"}],
            "sentiment_score": 0.25,
            "sentiment_label": "mixed",
            "ticker_sentiment_score": 0.4,
            "ticker_sentiment_label": "constructive",
            "macro_context_score": 0.7,
            "macro_context_label": "supportive",
            "industry_context_score": 0.6,
            "industry_context_label": "neutral",
            "macro_coverage_insights": ["macro ok"],
            "industry_coverage_insights": ["industry ok"],
            "macro_context_quality_score": 0.9,
            "macro_context_quality_status": "ok",
            "macro_context_quality_flags": {"fresh": True},
            "macro_context_quality_notes": ["fresh macro"],
            "industry_context_quality_score": 0.8,
            "industry_context_quality_status": "degraded",
            "industry_context_quality_flags": {"stale": True},
            "industry_context_quality_notes": ["stale industry"],
            "price": 123.45,
            "sma20": 120.0,
            "sma50": 118.0,
            "sma200": 110.0,
            "rsi": 55.0,
            "atr": 2.5,
            "atr_pct": 2.0,
            "price_above_sma50": 1,
            "price_above_sma200": 1,
            "momentum_short": 0.02,
            "momentum_medium": 0.04,
            "momentum_long": 0.08,
            "rel_return_5d_vs_spy": 0.01,
            "rel_return_20d_vs_spy": 0.02,
            "rel_return_5d_vs_sector": -0.01,
            "rel_return_20d_vs_sector": 0.03,
            "volume_ratio_20": 1.2,
            "dollar_volume_ratio_20": 1.4,
            "reference_features": {"spy": "available"},
            "price_history_diagnostics": {"source": "remote"},
        }
        feature_vector = {"momentum_short": 0.02, "rsi": 55.0}
        normalized_vector = {"momentum_short": 0.6, "rsi": 0.55}
        aggregations = {"direction_score": 0.7, "entry_adjustment": 123.5}
        confidence_components = {"technical_clarity": 70.0}
        transmission_analysis = {"expected_transmission_window": "2d_5d"}

        wrapper_payload = self.service._build_analysis_payload(
            ticker="AAPL",
            direction="LONG",
            technical_direction="LONG",
            direction_score=0.72,
            confidence=68.0,
            entry_price=123.5,
            stop_loss=120.0,
            take_profit=130.0,
            context=context,
            feature_vector=feature_vector,
            normalized_vector=normalized_vector,
            aggregations=aggregations,
            setup_family="momentum_breakout",
            confidence_components=confidence_components,
            transmission_analysis=transmission_analysis,
            horizon=StrategyHorizon.ONE_WEEK,
        )
        direct_payload = self.service.analysis_payloads.build_analysis_payload(
            ticker="AAPL",
            direction="LONG",
            technical_direction="LONG",
            direction_score=0.72,
            confidence=68.0,
            entry_price=123.5,
            stop_loss=120.0,
            take_profit=130.0,
            context=context,
            feature_vector=feature_vector,
            normalized_vector=normalized_vector,
            aggregations=aggregations,
            setup_family="momentum_breakout",
            confidence_components=confidence_components,
            transmission_analysis=transmission_analysis,
            horizon=StrategyHorizon.ONE_WEEK,
            model_name=self.service.model_name,
        )

        self.assertEqual(wrapper_payload, direct_payload)
        self.assertEqual(wrapper_payload["ticker_deep_analysis"]["price_history"], {"source": "remote"})
        self.assertEqual(wrapper_payload["technical"]["reference_features"], {"spy": "available"})

    def test_diagnostics_payload_service_matches_compatibility_wrapper(self) -> None:
        self.proposal_service.weights = {"confidence": {"technical_clarity": 0.2}}
        context = {
            "problems": ["missing benchmark", "missing benchmark", "stale industry"],
            "news_feed_errors": ["feed failed"],
            "summary_error": "summary failed",
            "llm_error": "llm unavailable",
            "summary_method": "fallback",
        }
        feature_vector = {"momentum_short": 0.02}
        normalized_vector = {"momentum_short": 0.6}
        aggregations = {"direction_score": 0.7}
        analysis_json = '{"summary": {"text": "x"}}'

        wrapper = self.service._build_diagnostics(analysis_json, feature_vector, normalized_vector, aggregations, context)
        direct = self.service.analysis_payloads.build_diagnostics(
            analysis_json,
            feature_vector,
            normalized_vector,
            aggregations,
            context,
            weights=self.proposal_service.weights,
        )

        self.assertEqual(wrapper.model_dump(), direct.model_dump())
        self.assertEqual(wrapper.warnings, ["missing benchmark", "stale industry"])
        self.assertEqual(json.loads(wrapper.confidence_weights_json), {"technical_clarity": 0.2})

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
            "market_intelligence_confidence": 80.0,
            "technical_clarity": 80.0,
            "execution_clarity": 80.0,
            "data_quality_cap": 50.0 # 50% multiplier
        }
        # 80 * (0.16+0.27+0.11+0.12+0.18+0.16) = 80 * 1.0 = 80.0
        # 80 * 0.5 = 40.0
        result = self.service._compose_confidence(components)
        self.assertEqual(result, 40.0)

    def test_compose_confidence_clamps_to_95(self) -> None:
        """System never reports 100% confidence."""
        components = {k: 100.0 for k in ["context_confidence", "directional_confidence", "catalyst_confidence", "market_intelligence_confidence", "technical_clarity", "execution_clarity", "data_quality_cap"]}
        result = self.service._compose_confidence(components)
        self.assertEqual(result, 95.0)

    def test_build_confidence_components_penalizes_problems(self) -> None:
        """Problems in context should reduce the data_quality_cap."""
        context = {"problems": ["p1", "p2"], "news_feed_errors": ["e1"]}
        # cap = 1.0 - min(0.7, (2 * 0.12) + (1 * 0.1)) = 1.0 - (0.24 + 0.1) = 0.66
        # 0.66 * 100 = 66.0
        comps = self.service._build_confidence_components(context, RecommendationDirection.LONG)
        self.assertEqual(comps["data_quality_cap"], 66.0)

    def test_build_confidence_components_penalizes_context_quality_status(self) -> None:
        context = {
            "macro_context_quality_status": "blocked",
            "industry_context_quality_status": "degraded",
            "problems": [],
            "news_feed_errors": [],
        }
        comps = self.service._build_confidence_components(context, RecommendationDirection.LONG)
        self.assertLess(comps["data_quality_cap"], 100.0)
        self.assertEqual(self.service._context_quality_status(context), "blocked")

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
        self.assertIn("context_quality", analysis["ticker_deep_analysis"])
        self.assertEqual(analysis["ticker_deep_analysis"]["context_quality"]["status"], "unknown")

    def test_analyze_includes_market_intelligence_in_payload_and_confidence_components(self) -> None:
        dates = pd.date_range("2026-01-01", periods=250, freq="B")
        history = pd.DataFrame(
            {
                "Open": [100.0 + (i * 0.05) for i in range(250)],
                "High": [101.0 + (i * 0.05) for i in range(250)],
                "Low": [99.0 + (i * 0.05) for i in range(250)],
                "Close": [100.0 + (i * 0.05) for i in range(250)],
                "Volume": [900] * 250,
            }, index=dates)

        def fetch_history(symbol: str, as_of=None):
            return history

        self.proposal_service._fetch_price_history.side_effect = fetch_history
        self.proposal_service._last_price_history_fetch_diagnostics = {"source": "remote", "remote_attempt_count": 1, "selected_bar_count": 250}
        self.market_intelligence_service.analyze.return_value = {
            "ticker": "AAPL",
            "as_of": "2026-05-03T00:00:00+00:00",
            "source_set": ["mock"],
            "coverage_status": "ok",
            "freshness_status": "fresh",
            "event_intelligence": {"available": True, "event_label": "earnings", "window_label": "2d_5d", "bias": "bullish", "score": 82.0, "warnings": [], "conflict_flags": []},
            "options_intelligence": {"available": True, "pressure_bias": "bullish", "score": 61.0, "warnings": [], "conflict_flags": []},
            "analyst_intelligence": {"available": True, "bias": "bullish", "score": 75.0, "warnings": [], "conflict_flags": []},
            "confidence_contribution": {"event": 82.0, "options": 61.0, "analyst": 75.0, "combined": 76.0},
            "conflict_flags": [],
            "warnings": [],
            "provider_diagnostics": {"source_name": "mock", "provider_keys": [], "info_available": True, "errors": []},
            "raw_payload_refs": {},
            "summary": "earnings 2d_5d · options bullish · analyst bullish",
        }
        self.market_intelligence_service.summarize.return_value = "earnings 2d_5d · options bullish · analyst bullish"

        output = self.service.analyze("AAPL")
        analysis = json.loads(output.diagnostics.analysis_json)

        self.assertEqual(analysis["market_intelligence"]["summary"], "earnings 2d_5d · options bullish · analyst bullish")
        self.assertEqual(analysis["ticker_deep_analysis"]["market_intelligence_summary"], "earnings 2d_5d · options bullish · analyst bullish")
        self.assertGreater(analysis["ticker_deep_analysis"]["confidence_components"]["market_intelligence_confidence"], 0)
        self.assertEqual(analysis["ticker_deep_analysis"]["transmission_analysis"]["market_intelligence_summary"], "earnings 2d_5d · options bullish · analyst bullish")

    def test_analyze_resolves_direction_from_aggregated_score(self) -> None:
        dates = pd.date_range("2026-01-01", periods=250, freq="B")
        downtrend = pd.DataFrame(
            {
                "Open": [120.0 - (i * 0.1) for i in range(250)],
                "High": [121.0 - (i * 0.1) for i in range(250)],
                "Low": [119.0 - (i * 0.1) for i in range(250)],
                "Close": [120.0 - (i * 0.1) for i in range(250)],
                "Volume": [1000] * 250,
            },
            index=dates,
        )

        self.proposal_service._fetch_price_history.side_effect = lambda symbol, as_of=None: downtrend
        self.proposal_service._last_price_history_fetch_diagnostics = {"source": "remote", "remote_attempt_count": 1, "selected_bar_count": 250}

        original_compute = self.service._compute_aggregations
        self.service._compute_aggregations = lambda normalized, atr, price: {
            "direction_score": 0.82,
            "risk_offset_pct": 0.0,
            "risk_stop_offset": 0.0,
            "risk_take_profit_offset": 0.0,
            "entry_adjustment": price,
            "entry_drift_signal": 0.0,
        }
        try:
            output = self.service.analyze("AAPL")
        finally:
            self.service._compute_aggregations = original_compute

        analysis = json.loads(output.diagnostics.analysis_json)
        self.assertEqual(output.recommendation.direction, RecommendationDirection.LONG)
        self.assertEqual(analysis["proposal"]["direction"], "LONG")
        self.assertEqual(analysis["proposal"]["technical_direction"], "SHORT")
        self.assertEqual(analysis["proposal"]["direction_score"], 0.82)

if __name__ == "__main__":
    unittest.main()
