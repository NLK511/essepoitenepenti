import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.enums import JobType, RunStatus
from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService, YahooHistoricalBarProvider
from trade_proposer_app.services.historical_replay import HistoricalReplayService
from trade_proposer_app.services.job_execution import JobExecutionService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class StubHistoricalBarProvider:
    provider_name = "stub"
    source_tier = "research"

    def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        return [
            HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=datetime(2024, 2, 5, tzinfo=timezone.utc),
                available_at=datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc),
                open_price=100.0,
                high_price=102.0,
                low_price=99.0,
                close_price=101.0,
                volume=1000,
                adjusted_close=101.0,
                source="stub",
                source_tier="research",
                metadata_json="{}",
            )
        ]


class HistoricalReplayTests(unittest.TestCase):
    def test_yahoo_provider_parses_daily_bar_payload(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1704067200],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0],
                                    "high": [101.0],
                                    "low": [99.5],
                                    "close": [100.5],
                                    "volume": [12345],
                                }
                            ],
                            "adjclose": [{"adjclose": [100.25]}],
                        },
                    }
                ]
            }
        }
        with patch("trade_proposer_app.services.historical_market_data.httpx.get", return_value=response):
            provider = YahooHistoricalBarProvider(base_url="https://query1.finance.yahoo.com")
            bars = provider.fetch_daily_bars(
                "AAPL",
                start_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(1, len(bars))
        self.assertEqual("AAPL", bars[0].ticker)
        self.assertEqual(100.5, bars[0].close_price)
        self.assertEqual(100.25, bars[0].adjusted_close)
        self.assertEqual(datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc), bars[0].available_at)

    def test_historical_market_bar_upsert_and_window_query(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    available_at=datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc),
                    open_price=100.0,
                    high_price=101.0,
                    low_price=99.0,
                    close_price=100.5,
                    volume=1000,
                    source="fixture",
                )
            )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    available_at=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
                    open_price=101.0,
                    high_price=102.0,
                    low_price=100.0,
                    close_price=101.5,
                    volume=1100,
                    source="fixture",
                )
            )
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1d",
                    bar_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                    available_at=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
                    open_price=101.0,
                    high_price=103.0,
                    low_price=100.0,
                    close_price=102.0,
                    volume=1200,
                    source="fixture-refresh",
                )
            )
            bars = repository.list_bars(
                ticker="AAPL",
                timeframe="1d",
                end_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                available_at=datetime(2024, 1, 2, 23, 59, 59, tzinfo=timezone.utc),
                limit=10,
            )
            self.assertEqual(2, len(bars))
            self.assertEqual(103.0, bars[-1].high_price)
            self.assertEqual("fixture-refresh", bars[-1].source)
        finally:
            session.close()

    def test_create_batch_creates_daily_slices_from_universe_preset(self) -> None:
        session = create_session()
        try:
            service = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
            )
            batch = service.create_batch(
                name="Replay MVP",
                mode="research",
                universe_preset="us_large_cap_top20_v1",
                as_of_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 1, 3, 23, 59, 59, tzinfo=timezone.utc),
            )
            repository = HistoricalReplayRepository(session)
            slices = repository.list_slices(batch.id or 0)
            self.assertEqual(3, len(slices))
            self.assertEqual(["planned", "planned", "planned"], [item.status for item in slices])
            summary = repository.summarize_batch(batch.id or 0)
            self.assertEqual(3, summary["slice_count"])
            self.assertEqual(3, summary["planned_count"])
            self.assertEqual("us_large_cap_top20_v1", batch.universe_preset)
            self.assertEqual("next_open", batch.entry_timing)
        finally:
            session.close()

    def test_enqueue_and_execute_single_slice_run_with_market_data_coverage(self) -> None:
        session = create_session()
        try:
            historical_replay = HistoricalReplayService(
                historical_replays=HistoricalReplayRepository(session),
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_market_data=HistoricalMarketDataService(
                    HistoricalMarketDataRepository(session),
                    provider=StubHistoricalBarProvider(),
                ),
            )
            batch = historical_replay.create_batch(
                name="Replay single day",
                mode="research",
                tickers=["AAPL", "MSFT"],
                entry_timing="next_close",
                as_of_start=datetime(2024, 2, 5, tzinfo=timezone.utc),
                as_of_end=datetime(2024, 2, 5, 23, 59, 59, tzinfo=timezone.utc),
            )
            queued_runs = historical_replay.enqueue_batch(batch.id or 0)
            self.assertEqual(1, len(queued_runs))
            queued_run = queued_runs[0]
            self.assertEqual(JobType.HISTORICAL_REPLAY, queued_run.job_type)

            execution = JobExecutionService(
                jobs=JobRepository(session),
                runs=RunRepository(session),
                historical_replay=historical_replay,
            )
            claimed = RunRepository(session).claim_next_queued_run(worker_id="worker-test")
            assert claimed is not None
            final_run, _ = execution.execute_claimed_run(claimed, worker_id="worker-test")
            self.assertEqual(RunStatus.COMPLETED, final_run.status)
            summary = json.loads(final_run.summary_json or "{}")
            self.assertEqual(batch.id, summary["replay_batch_id"])
            self.assertEqual("research", summary["mode"])
            self.assertEqual("next_close", summary["entry_timing"])
            self.assertEqual(1.0, summary["coverage_ratio"])

            repository = HistoricalReplayRepository(session)
            refreshed_batch = repository.get_batch(batch.id or 0)
            self.assertEqual("completed", refreshed_batch.status)
            slice_row = repository.list_slices(batch.id or 0)[0]
            self.assertEqual("completed", slice_row.status)
            output_summary = json.loads(slice_row.output_summary_json)
            self.assertEqual("Historical replay market-data input assembly completed.", output_summary["message"])
            self.assertEqual("market_inputs_prepared", output_summary["pipeline_stage"])
            input_summary = json.loads(slice_row.input_summary_json)
            self.assertEqual(2, input_summary["market_input"]["covered_ticker_count"])
            self.assertEqual("market_inputs_prepared", input_summary["pipeline_stage"])
        finally:
            session.close()
