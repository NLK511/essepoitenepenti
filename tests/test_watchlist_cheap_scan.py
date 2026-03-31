import unittest

import pandas as pd

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanError, CheapScanSignalService


class CheapScanSignalServiceTests(unittest.TestCase):
    def test_score_uses_dedicated_component_model(self) -> None:
        def fetcher(ticker: str, period: str) -> pd.DataFrame:
            self.assertEqual(ticker, "AAPL")
            self.assertEqual(period, "6mo")
            closes = [100 + i for i in range(80)]
            volumes = [1_500_000 + (i * 10_000) for i in range(80)]
            return pd.DataFrame({"Close": closes, "Volume": volumes})

        signal = CheapScanSignalService(history_fetcher=fetcher).score("aapl", StrategyHorizon.ONE_WEEK)

        self.assertEqual(signal.ticker, "AAPL")
        self.assertEqual(signal.horizon, StrategyHorizon.ONE_WEEK)
        self.assertEqual(signal.directional_bias, "long")
        self.assertGreater(signal.directional_score, 0)
        self.assertGreater(signal.attention_score, 0)
        self.assertGreater(signal.trend_score, 50)
        self.assertGreater(signal.momentum_score, 50)
        self.assertEqual(signal.diagnostics["model"], "cheap_scan_v1")
        self.assertIn("trend", signal.indicator_summary)

    def test_score_raises_for_insufficient_history(self) -> None:
        def fetcher(ticker: str, period: str) -> pd.DataFrame:
            return pd.DataFrame({"Close": [100 + i for i in range(10)], "Volume": [1_000_000 for _ in range(10)]})

        with self.assertRaises(CheapScanError):
            CheapScanSignalService(history_fetcher=fetcher).score("MSFT", StrategyHorizon.ONE_DAY)
