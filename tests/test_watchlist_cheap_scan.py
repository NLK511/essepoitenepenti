import unittest

import pandas as pd

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanError, CheapScanSignalService


class CheapScanSignalServiceTests(unittest.TestCase):
    def test_score_uses_dedicated_component_model(self) -> None:
        def fetcher(ticker: str, period: str, as_of=None) -> pd.DataFrame:
            self.assertEqual(ticker, "AAPL")
            self.assertEqual(period, "6mo")
            self.assertIsNone(as_of)
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
        def fetcher(ticker: str, period: str, as_of=None) -> pd.DataFrame:
            return pd.DataFrame({"Close": [100 + i for i in range(10)], "Volume": [1_000_000 for _ in range(10)]})

        with self.assertRaises(CheapScanError):
            CheapScanSignalService(history_fetcher=fetcher).score("MSFT", StrategyHorizon.ONE_DAY)

    def test_score_warns_only_when_history_is_shorter_than_full_sma_window(self) -> None:
        def fetcher(ticker: str, period: str, as_of=None) -> pd.DataFrame:
            closes = [100 + i for i in range(40)]
            volumes = [1_000_000 for _ in range(40)]
            return pd.DataFrame({"Close": closes, "Volume": volumes})

        signal = CheapScanSignalService(history_fetcher=fetcher).score("NVDA", StrategyHorizon.ONE_WEEK)

        self.assertIn("cheap scan used limited lookback history", signal.warnings)
        self.assertEqual(signal.diagnostics["history_bar_count"], 40)
        self.assertEqual(signal.diagnostics["effective_sma50_window"], 40)

    def test_score_does_not_warn_when_full_sma_window_is_available(self) -> None:
        def fetcher(ticker: str, period: str, as_of=None) -> pd.DataFrame:
            closes = [100 + i for i in range(55)]
            volumes = [1_000_000 for _ in range(55)]
            return pd.DataFrame({"Close": closes, "Volume": volumes})

        signal = CheapScanSignalService(history_fetcher=fetcher).score("META", StrategyHorizon.ONE_WEEK)

        self.assertNotIn("cheap scan used limited lookback history", signal.warnings)
        self.assertEqual(signal.diagnostics["history_bar_count"], 55)
        self.assertEqual(signal.diagnostics["effective_sma50_window"], 50)

    def test_score_uses_traded_value_warning_label_and_diagnostic(self) -> None:
        def fetcher(ticker: str, period: str, as_of=None) -> pd.DataFrame:
            closes = [10.0 for _ in range(55)]
            volumes = [100_000 for _ in range(55)]
            return pd.DataFrame({"Close": closes, "Volume": volumes})

        signal = CheapScanSignalService(history_fetcher=fetcher).score("PROX.BR", StrategyHorizon.ONE_WEEK)

        self.assertIn("low average traded value on cheap scan", signal.warnings)
        self.assertNotIn("low average dollar volume on cheap scan", signal.warnings)
        self.assertEqual(signal.diagnostics["avg_traded_value_20"], 1_000_000.0)
        self.assertEqual(signal.diagnostics["liquidity_metric_currency"], "raw_quote_currency_not_normalized")
