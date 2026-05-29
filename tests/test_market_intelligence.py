from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.services.market_intelligence import MarketIntelligenceService, MarketIntelligenceServiceConfig


class MarketIntelligenceServiceTests(unittest.TestCase):
    def test_disabled_snapshot_is_not_decision_grade_evidence(self) -> None:
        service = MarketIntelligenceService()
        with patch("trade_proposer_app.services.market_intelligence.yf.Ticker", side_effect=AssertionError("disabled market intelligence should not fetch")):
            snapshot = service.analyze("AAPL", horizon=StrategyHorizon.ONE_WEEK)

        self.assertEqual(snapshot["coverage_status"], "disabled")
        self.assertEqual(snapshot["freshness_status"], "disabled")
        self.assertEqual(snapshot["confidence_contribution"]["combined"], 0.0)
        self.assertEqual(snapshot["conflict_flags"], [])

    def test_live_snapshot_combines_event_options_and_analyst_signals(self) -> None:
        service = MarketIntelligenceService(config=MarketIntelligenceServiceConfig(enabled=True))
        ticker_obj = Mock()
        ticker_obj.info = {
            "earningsTimestamp": int(datetime(2026, 5, 6, tzinfo=timezone.utc).timestamp()),
            "recommendationKey": "buy",
            "recommendationMean": 1.8,
            "targetMeanPrice": 220.0,
            "currentPrice": 200.0,
            "regularMarketPrice": 200.0,
        }
        ticker_obj.calendar = pd.DataFrame({"Earnings Date": [pd.Timestamp("2026-05-06", tz="UTC")]}, index=["Earnings Date"])
        ticker_obj.options = ["2026-05-10"]
        ticker_obj.option_chain.return_value = SimpleNamespace(
            calls=pd.DataFrame({"openInterest": [100, 120], "volume": [40, 35], "impliedVolatility": [0.25, 0.28]}),
            puts=pd.DataFrame({"openInterest": [20, 15], "volume": [8, 7], "impliedVolatility": [0.23, 0.24]}),
        )
        ticker_obj.recommendations = pd.DataFrame([
            {"action": "main", "fromGrade": "Hold", "toGrade": "Buy"},
        ])

        with patch("trade_proposer_app.services.market_intelligence.yf.Ticker", return_value=ticker_obj):
            snapshot = service.analyze("AAPL", horizon=StrategyHorizon.ONE_WEEK)

        self.assertTrue(snapshot["event_intelligence"]["available"])
        self.assertTrue(snapshot["options_intelligence"]["available"])
        self.assertTrue(snapshot["analyst_intelligence"]["available"])
        self.assertGreater(snapshot["confidence_contribution"]["combined"], 0)
        self.assertIn("earnings", snapshot["summary"])
        self.assertIn("options", snapshot["summary"])
        self.assertIn("analyst", snapshot["summary"])

    def test_replay_snapshots_do_not_fetch_live_market_intelligence(self) -> None:
        service = MarketIntelligenceService(config=MarketIntelligenceServiceConfig(enabled=True))
        with patch("trade_proposer_app.services.market_intelligence.yf.Ticker", side_effect=AssertionError("should not fetch live market intelligence during replay")):
            snapshot = service.analyze("AAPL", as_of=datetime.now(timezone.utc) - timedelta(days=3))

        self.assertEqual(snapshot["coverage_status"], "replay_unavailable")
        self.assertTrue(any("replay unavailable" in warning for warning in snapshot["warnings"]))
