import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, StrategyHorizon, RecommendationDirection
from trade_proposer_app.domain.models import HistoricalMarketBar, Watchlist, RunOutput, Recommendation, RunDiagnostics, TickerSignalSnapshot
from trade_proposer_app.persistence.models import Base, HistoricalMarketBarRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.bars_refresh import BarsRefreshService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignalService, CheapScanSignal


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class BarsRefreshAndSimulationTests(unittest.TestCase):
    def test_bars_refresh_service_incremental_logic(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            service = BarsRefreshService(repository)
            
            base_time = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=3)
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=base_time,
                    open_price=150.0, high_price=151.0, low_price=149.0, close_price=150.5,
                    volume=1000, source="test"
                )
            )
            
            new_time = base_time + timedelta(minutes=2)
            mock_df = pd.DataFrame([{
                "Open": 151.0, "High": 152.0, "Low": 150.0, "Close": 151.5, "Volume": 2000
            }], index=[new_time])
            mock_df.index.name = "Datetime"
            if mock_df.index.tz is None:
                mock_df.index = mock_df.index.tz_localize(timezone.utc)
            
            with patch("yfinance.download", return_value=mock_df):
                result = service.refresh_bars(["AAPL"], lookback_days=7)
                
            self.assertEqual(result["total_ingested"], 1)
            
        finally:
            session.close()

    def test_cheap_scan_signal_service_database_source(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            service = CheapScanSignalService(repository=repository)
            
            now = datetime.now(timezone.utc)
            start_date = now - timedelta(days=70)
            for i in range(65):
                bar_time = start_date + timedelta(days=i)
                repository.upsert_bar(
                    HistoricalMarketBar(
                        ticker="AAPL",
                        timeframe="1d",
                        bar_time=bar_time,
                        available_at=datetime.combine(bar_time.date(), datetime.max.time(), tzinfo=timezone.utc),
                        open_price=100.0 + i, high_price=101.0 + i, low_price=99.0 + i, close_price=100.5 + i,
                        volume=1000000, source="seed"
                    )
                )
            
            as_of = start_date + timedelta(days=64, hours=23)
            signal = service.score("AAPL", StrategyHorizon.ONE_WEEK, as_of=as_of)
            
            self.assertEqual(signal.ticker, "AAPL")
            self.assertEqual(signal.diagnostics["data_source"], "database")
            
        finally:
            session.close()

    def test_watchlist_orchestration_passes_as_of_to_cheap_scan_and_deep_analysis_in_replay_mode(self) -> None:
        mock_cheap_scan = MagicMock()
        mock_deep_analysis = MagicMock()
        mock_context_repo = MagicMock()
        mock_plan_repo = MagicMock()

        from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService

        service = WatchlistOrchestrationService(
            context_snapshots=mock_context_repo,
            recommendation_plans=mock_plan_repo,
            cheap_scan_service=mock_cheap_scan,
            deep_analysis_service=mock_deep_analysis
        )

        watchlist = Watchlist(id=1, name="Test", tickers=["AAPL"], default_horizon=StrategyHorizon.ONE_WEEK)
        as_of = datetime.now(timezone.utc)

        mock_signal_obj = CheapScanSignal(
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            directional_bias="long",
            confidence_percent=80.0,
            attention_score=70.0,
            trend_score=80.0,
            breakout_score=70.0,
            momentum_score=60.0,
            directional_score=0.5,
            diagnostics={"model": "test-model"}
        )
        mock_cheap_scan.score.return_value = mock_signal_obj

        mock_deep_analysis.analyze.return_value = None
        mock_context_repo.create_ticker_signal_snapshot.side_effect = lambda signal: signal.model_copy(update={"id": 1})
        mock_plan_repo.create_plan.side_effect = lambda plan: plan.model_copy(update={"id": 1})

        service.execute(watchlist, ["AAPL"], as_of=as_of)

        mock_cheap_scan.score.assert_called_once()
        _, cheap_scan_kwargs = mock_cheap_scan.score.call_args
        self.assertEqual(cheap_scan_kwargs["as_of"], as_of)

        mock_deep_analysis.analyze.assert_called_once()
        _, deep_analysis_kwargs = mock_deep_analysis.analyze.call_args
        self.assertEqual(deep_analysis_kwargs["as_of"], as_of)
        self.assertEqual(deep_analysis_kwargs["horizon"], StrategyHorizon.ONE_WEEK)

    def test_watchlist_orchestration_passes_none_as_of_in_normal_mode(self) -> None:
        mock_cheap_scan = MagicMock()
        mock_deep_analysis = MagicMock()
        mock_context_repo = MagicMock()
        mock_plan_repo = MagicMock()

        from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService

        service = WatchlistOrchestrationService(
            context_snapshots=mock_context_repo,
            recommendation_plans=mock_plan_repo,
            cheap_scan_service=mock_cheap_scan,
            deep_analysis_service=mock_deep_analysis
        )

        watchlist = Watchlist(id=1, name="Test", tickers=["AAPL"], default_horizon=StrategyHorizon.ONE_WEEK)

        mock_signal_obj = CheapScanSignal(
            ticker="AAPL",
            horizon=StrategyHorizon.ONE_WEEK,
            directional_bias="long",
            confidence_percent=80.0,
            attention_score=70.0,
            trend_score=80.0,
            breakout_score=70.0,
            momentum_score=60.0,
            directional_score=0.5,
            diagnostics={"model": "test-model"}
        )
        mock_cheap_scan.score.return_value = mock_signal_obj

        mock_deep_analysis.analyze.return_value = None
        mock_context_repo.create_ticker_signal_snapshot.side_effect = lambda signal: signal.model_copy(update={"id": 1})
        mock_plan_repo.create_plan.side_effect = lambda plan: plan.model_copy(update={"id": 1})

        service.execute(watchlist, ["AAPL"])

        mock_cheap_scan.score.assert_called_once()
        _, cheap_scan_kwargs = mock_cheap_scan.score.call_args
        self.assertIn("as_of", cheap_scan_kwargs)
        self.assertIsNone(cheap_scan_kwargs["as_of"])

    def test_cheap_scan_signal_service_lazy_hydration(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            service = CheapScanSignalService(repository=repository)
            
            # 1. Setup: No bars in DB for this ticker
            ticker = "LAZY"
            as_of = datetime(2026, 4, 1, tzinfo=timezone.utc)
            
            # 2. Mock yfinance to return some data
            mock_df = pd.DataFrame([
                {"Open": 100.0 + i, "High": 101.0 + i, "Low": 99.0 + i, "Close": 100.5 + i, "Volume": 1000}
                for i in range(40)
            ], index=[as_of - timedelta(days=40-i) for i in range(40)])
            mock_df.index.name = "Date"
            
            with patch("yfinance.download", return_value=mock_df):
                signal = service.score(ticker, StrategyHorizon.ONE_WEEK, as_of=as_of)
                
            # 3. Verify: Remote fallback happened and signal was produced
            self.assertEqual(signal.ticker, ticker)
            self.assertEqual(signal.diagnostics["data_source"], "yahoo")
            
            # 4. Verify: Data was persisted to DB
            stored_bars = repository.list_bars(ticker=ticker, timeframe="1d")
            self.assertGreaterEqual(len(stored_bars), 40)
            self.assertEqual(stored_bars[0].source, "yahoo_fallback")
            
        finally:
            session.close()
