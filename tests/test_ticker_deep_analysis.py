import json
import unittest

import pandas as pd

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService


class StubProposalService:
    def __init__(self) -> None:
        self.weights = {"confidence": {}, "aggregators": {}}

    def _fetch_price_history(self, ticker: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Open": [98.0, 99.0, 100.0],
                "High": [101.0, 103.0, 105.0],
                "Low": [97.0, 98.5, 99.5],
                "Close": [100.0, 102.0, 104.0],
                "Volume": [1000, 1200, 1400],
            },
            index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True),
        )

    def _enrich_history(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["SMA_20"] = [99.0, 100.0, 101.0]
        enriched["SMA_50"] = [98.0, 99.0, 100.0]
        enriched["SMA_200"] = [97.0, 98.0, 99.0]
        enriched["RSI_14"] = [55.0, 59.0, 63.0]
        enriched["ATR_14"] = [2.0, 2.1, 2.2]
        enriched["atr_pct"] = [2.0, 2.05, 2.12]
        enriched["momentum_short"] = [0.03, 0.04, 0.05]
        enriched["momentum_medium"] = [0.07, 0.09, 0.11]
        enriched["momentum_long"] = [0.1, 0.11, 0.12]
        enriched["price_change_1d"] = [0.01, 0.02, 0.02]
        enriched["price_change_10d"] = [0.05, 0.06, 0.07]
        enriched["price_change_63d"] = [0.09, 0.1, 0.11]
        enriched["price_change_126d"] = [0.12, 0.13, 0.14]
        enriched["entry_delta_2w"] = [0.05, 0.06, 0.07]
        enriched["entry_delta_3m"] = [0.09, 0.1, 0.11]
        enriched["entry_delta_12m"] = [0.18, 0.19, 0.2]
        enriched["price_vs_sma20_ratio"] = [0.01, 0.015, 0.02]
        enriched["price_vs_sma50_ratio"] = [0.015, 0.02, 0.025]
        enriched["price_vs_sma200_ratio"] = [0.02, 0.025, 0.03]
        enriched["price_vs_sma20_slope"] = [0.01, 0.015, 0.02]
        enriched["price_vs_sma50_slope"] = [0.015, 0.02, 0.025]
        enriched["price_vs_sma200_slope"] = [0.02, 0.025, 0.03]
        enriched["volatility_band_upper"] = [101.0, 102.0, 103.0]
        enriched["volatility_band_lower"] = [97.0, 98.0, 99.0]
        enriched["volatility_band_width"] = [4.0, 4.0, 4.0]
        return enriched

    def _build_context(self, df: pd.DataFrame) -> dict[str, object]:
        return {
            "price": 104.0,
            "atr": 2.2,
            "atr_pct": 2.12,
            "rsi": 63.0,
            "direction": "LONG",
            "price_above_sma50": 1,
            "price_above_sma200": 1,
            "momentum_short": 0.05,
            "momentum_medium": 0.11,
            "momentum_long": 0.12,
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
            "price_change_1d": 0.02,
            "price_change_10d": 0.07,
            "price_change_63d": 0.11,
            "price_change_126d": 0.14,
            "entry_delta_2w": 0.07,
            "entry_delta_3m": 0.11,
            "entry_delta_12m": 0.2,
            "price_vs_sma20_ratio": 0.02,
            "price_vs_sma50_ratio": 0.025,
            "price_vs_sma200_ratio": 0.03,
            "price_vs_sma20_slope": 0.02,
            "price_vs_sma50_slope": 0.025,
            "price_vs_sma200_slope": 0.03,
            "volatility_band_upper": 103.0,
            "volatility_band_lower": 99.0,
            "volatility_band_width": 4.0,
            "short_bullish": 3.0,
            "short_bearish": 0.0,
            "medium_bullish": 3.0,
            "medium_bearish": 0.0,
        }

    def _apply_news_context(self, context: dict[str, object], ticker: str) -> dict[str, object]:
        return context

    def _build_feature_vector(self, context: dict[str, object]) -> dict[str, float]:
        return {
            "price_close": 104.0,
            "sma20": 101.0,
            "sma50": 100.0,
            "sma200": 99.0,
            "rsi": 63.0,
            "atr": 2.2,
            "atr_pct": 2.12,
            "volatility_band_upper": 103.0,
            "volatility_band_lower": 99.0,
            "volatility_band_width": 4.0,
            "momentum_short": 0.05,
            "momentum_medium": 0.11,
            "momentum_long": 0.12,
            "price_change_1d": 0.02,
            "price_change_10d": 0.07,
            "price_change_63d": 0.11,
            "price_change_126d": 0.14,
            "entry_delta_2w": 0.07,
            "entry_delta_3m": 0.11,
            "entry_delta_12m": 0.2,
            "price_vs_sma20_ratio": 0.02,
            "price_vs_sma50_ratio": 0.025,
            "price_vs_sma200_ratio": 0.03,
            "price_vs_sma20_slope": 0.02,
            "price_vs_sma50_slope": 0.025,
            "price_vs_sma200_slope": 0.03,
            "short_bullish": 3.0,
            "short_bearish": 0.0,
            "medium_bullish": 3.0,
            "medium_bearish": 0.0,
            "sentiment_score": 0.22,
            "enhanced_sentiment_score": 0.22,
            "news_sentiment_score": 0.22,
            "social_sentiment_score": 0.0,
            "macro_sentiment_score": 0.22,
            "industry_sentiment_score": 0.3,
            "ticker_sentiment_score": 0.31,
            "social_item_count": 0.0,
            "macro_item_count": 1.0,
            "industry_item_count": 1.0,
            "ticker_item_count": 4.0,
            "source_count": 1.0,
            "context_count": 2.0,
            "news_point_count": 4.0,
            "polarity_trend": 0.12,
            "sentiment_volatility": 0.08,
            "context_tag_earnings": 0.0,
            "context_tag_geopolitical": 0.0,
            "context_tag_industry": 1.0,
            "context_tag_general": 0.0,
        }

    def _compute_column_ranges(self, df: pd.DataFrame):
        return {column: (float(df[column].min()), float(df[column].max())) for column in df.columns if column in df}

    def _normalize_feature_vector(self, feature_vector, column_ranges):
        return {key: 0.6 for key in feature_vector}

    def _compute_aggregations(self, normalized, atr, price):
        return {
            "direction_score": 0.63,
            "risk_offset_pct": 0.1,
            "risk_stop_offset": 0.2,
            "risk_take_profit_offset": 0.4,
            "entry_adjustment": price,
            "entry_drift_signal": 0.12,
        }

    def _suggest_price_levels(self, direction, price, atr, aggregations):
        return (104.0, 101.6, 108.4)

    def _build_analysis_payload(self, **kwargs):
        return {"summary": {"text": "native deep analysis"}, "sentiment": {"ticker": {"score": 0.31}}}

    def _build_diagnostics(self, analysis_json, feature_vector, normalized_vector, aggregations, context):
        from trade_proposer_app.domain.models import RunDiagnostics

        return RunDiagnostics(
            analysis_json=analysis_json,
            raw_output=analysis_json,
            summary_method=str(context.get("summary_method", "digest")),
        )


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
        self.assertEqual(output.recommendation.direction, RecommendationDirection.LONG)
        self.assertGreater(output.recommendation.confidence, 0.0)
        self.assertEqual(output.diagnostics.analysis_json, output.diagnostics.raw_output)


if __name__ == "__main__":
    unittest.main()
