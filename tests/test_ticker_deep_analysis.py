import json
import unittest

import pandas as pd

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService


class StubProposalService:
    def __init__(self) -> None:
        self.weights = {"confidence": {}, "aggregators": {}}

    def _fetch_price_history(self, ticker: str) -> pd.DataFrame:
        close = [100.0 + (index * 0.2) for index in range(260)]
        return pd.DataFrame(
            {
                "Open": [value - 0.8 for value in close],
                "High": [value + 1.0 for value in close],
                "Low": [value - 1.0 for value in close],
                "Close": close,
                "Volume": [1000 + (index * 10) for index in range(260)],
            },
            index=pd.date_range("2024-01-02", periods=260, freq="D", tz="UTC"),
        )

    def _apply_news_context(self, context: dict[str, object], ticker: str) -> dict[str, object]:
        return {
            **context,
            "sentiment_score": 0.22,
            "sentiment_label": "POSITIVE",
            "macro_sentiment_score": 0.22,
            "industry_sentiment_score": 0.3,
            "ticker_sentiment_score": 0.31,
            "ticker_sentiment_label": "POSITIVE",
            "news_item_count": 4,
            "context_count": 2,
            "news_feed_errors": [],
            "problems": [],
            "summary_text": "AI demand and momentum remain supportive.",
            "summary_method": "digest",
            "news_items": [{"title": "AI demand supports the group while suppliers keep the supply chain tight"}],
            "news_feeds_used": ["stub_news"],
            "source_count": 1,
            "news_point_count": 4,
            "polarity_trend": 0.12,
            "sentiment_volatility": 0.08,
            "macro_item_count": 1.0,
            "industry_item_count": 1.0,
            "ticker_item_count": 4.0,
            "social_item_count": 0.0,
            "context_tag_industry": 1.0,
            "ticker_profile": {
                "ticker": ticker,
                "industry": "Semiconductors",
                "sector": "Technology",
                "themes": ["ai", "semiconductor"],
                "macro_sensitivity": ["rates", "growth"],
                "industry_keywords": ["semiconductor", "chip"],
            },
            "macro_context_events": [
                {
                    "key": "bond_yields",
                    "label": "Bond yields",
                    "saliency_weight": 0.7,
                    "event_score": 1.9,
                    "persistence_state": "escalating",
                    "recency_bucket": "fresh",
                    "window_hint": "2d_5d",
                    "transmission_channels": ["rates", "valuation_duration"],
                    "regime_tags": ["rates", "yield_pressure"],
                    "contradiction_flag": False,
                }
            ],
            "industry_context_events": [
                {
                    "key": "ai_theme",
                    "label": "AI theme",
                    "saliency_weight": 0.8,
                    "event_score": 2.1,
                    "persistence_state": "escalating",
                    "recency_bucket": "fresh",
                    "window_hint": "2d_5d",
                    "transmission_channels": ["theme_attention", "compute_demand", "supply_chain"],
                    "regime_tags": ["industry_dominant"],
                    "contradiction_flag": False,
                }
            ],
            "macro_context_regime_tags": ["risk_off"],
            "industry_context_regime_tags": ["industry_dominant"],
            "macro_context_contradictory_event_labels": [],
            "industry_context_contradictory_event_labels": [],
        }


class TickerDeepAnalysisServiceTests(unittest.TestCase):
    def test_analyze_annotates_output_with_native_model_horizon_and_components(self) -> None:
        service = TickerDeepAnalysisService(StubProposalService())

        output = service.analyze("AAPL", horizon=StrategyHorizon.ONE_WEEK)
        payload = json.loads(output.diagnostics.analysis_json or "{}")

        self.assertEqual(payload["ticker_deep_analysis"]["model"], "ticker_deep_analysis_v2")
        self.assertEqual(payload["ticker_deep_analysis"]["execution_path"], "native")
        self.assertEqual(payload["ticker_deep_analysis"]["horizon"], "1w")
        self.assertIn("setup_family", payload["ticker_deep_analysis"])
        self.assertIn("confidence_components", payload["ticker_deep_analysis"])
        self.assertIn("transmission_analysis", payload["ticker_deep_analysis"])
        self.assertEqual(payload["ticker_deep_analysis"]["transmission_analysis"]["context_bias"], "tailwind")
        self.assertIn("primary_drivers", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertIn("expected_transmission_window", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertIn("conflict_flags", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertIn("context_strength_percent", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertIn("context_event_relevance_percent", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertIn("ticker_relationship_edges", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertIn("matched_ticker_relationships", payload["ticker_deep_analysis"]["transmission_analysis"])
        self.assertTrue(payload["ticker_deep_analysis"]["transmission_analysis"]["ticker_relationship_edges"])
        self.assertTrue(payload["ticker_deep_analysis"]["transmission_analysis"]["matched_ticker_relationships"])
        self.assertEqual(payload["ticker_deep_analysis"]["transmission_analysis"]["matched_ticker_relationships"][0]["type"], "supplier_to")
        self.assertEqual(payload["ticker_deep_analysis"]["transmission_analysis"]["expected_transmission_window"], "2d_5d")
        self.assertEqual(payload["ticker_deep_analysis"]["transmission_analysis"]["decay_state"], "fresh")
        self.assertEqual(payload["summary"]["method"], "digest")
        self.assertEqual(payload["news"]["feeds_used"], ["stub_news"])
        self.assertEqual(output.recommendation.direction, RecommendationDirection.LONG)
        self.assertGreater(output.recommendation.confidence, 0.0)
        self.assertEqual(output.diagnostics.analysis_json, output.diagnostics.raw_output)
        self.assertEqual(output.diagnostics.summary_method, "digest")
        self.assertIsNotNone(output.diagnostics.feature_vector_json)
        self.assertIsNotNone(output.diagnostics.aggregations_json)


if __name__ == "__main__":
    unittest.main()
