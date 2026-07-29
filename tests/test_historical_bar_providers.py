import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.persistence.models import Base, HistoricalMarketBarRecord
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.bars_refresh import BarsRefreshService
from trade_proposer_app.services.etoro_bar_shadow_comparison import (
    EtoroBarShadowComparisonConfig,
    EtoroBarShadowComparisonService,
)
from trade_proposer_app.services.historical_market_data import (
    EtoroHistoricalBarProvider,
    HistoricalBarFetchResult,
    HistoricalBarProvider,
    HistoricalMarketDataError,
)


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class FakeEtoroClient:
    def __init__(
        self,
        *,
        search_payload=None,
        candle_payload=None,
        display_payloads=None,
    ) -> None:
        self.search_payload = search_payload or {
            "items": [{"instrumentId": 1001, "internalSymbolFull": "AAPL", "name": "Apple"}]
        }
        self.candle_payload = candle_payload or {
            "interval": "OneMinute",
            "candles": [
                {
                    "instrumentId": 1001,
                    "candles": [
                        {
                            "instrumentID": 1001,
                            "fromDate": "2026-07-25T14:30:00Z",
                            "open": 100.0,
                            "high": 101.0,
                            "low": 99.5,
                            "close": 100.5,
                            "volume": 1200,
                        }
                    ],
                }
            ],
        }
        self.display_payloads = display_payloads or {}
        self.search_calls: list[str] = []
        self.display_calls: list[str] = []
        self.candle_calls: list[dict[str, object]] = []

    def search_market_data(self, symbol: str):
        self.search_calls.append(symbol)
        if callable(self.search_payload):
            return self.search_payload(symbol)
        if isinstance(self.search_payload, dict) and symbol in self.search_payload:
            return self.search_payload[symbol]
        return self.search_payload

    def get_instrument_display_data(self, instrument_id):
        self.display_calls.append(str(instrument_id))
        return self.display_payloads.get(
            str(instrument_id),
            {"instrumentDisplayDatas": []},
        )

    def get_instrument_candles(self, **kwargs):
        self.candle_calls.append(kwargs)
        return self.candle_payload


class StubIntradayProvider(HistoricalBarProvider):
    provider_name = "stub"
    source_tier = "test"
    supported_timeframes = ("1m",)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    def fetch_bars(self, ticker, timeframe, start_at, end_at):
        self.calls.append(
            {
                "ticker": ticker,
                "timeframe": timeframe,
                "start_at": start_at,
                "end_at": end_at,
            }
        )
        bar_time = start_at + timedelta(minutes=1)
        return HistoricalBarFetchResult(
            provider=self.provider_name,
            source_tier=self.source_tier,
            timeframe=timeframe,
            bars=[
                HistoricalMarketBar(
                    ticker=ticker,
                    timeframe=timeframe,
                    bar_time=bar_time,
                    available_at=bar_time + timedelta(minutes=1),
                    open_price=100,
                    high_price=101,
                    low_price=99,
                    close_price=100.5,
                    volume=1000,
                    source="stub",
                    source_tier="test",
                )
            ],
        )

    def fetch_daily_bars(self, ticker, start_at, end_at):
        raise NotImplementedError


class StubComparisonProvider(HistoricalBarProvider):
    provider_name = "etoro"
    source_tier = "broker"
    supported_timeframes = ("1m",)

    def fetch_bars(self, ticker, timeframe, start_at, end_at):
        bar_time = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)
        return HistoricalBarFetchResult(
            provider="etoro",
            source_tier="broker",
            timeframe=timeframe,
            bars=[
                HistoricalMarketBar(
                    ticker=ticker,
                    timeframe=timeframe,
                    bar_time=bar_time,
                    available_at=bar_time + timedelta(minutes=1),
                    open_price=100.0,
                    high_price=101.0,
                    low_price=99.0,
                    close_price=100.1,
                    volume=0.0,
                    source="etoro",
                    source_tier="broker",
                )
            ],
        )

    def fetch_daily_bars(self, ticker, start_at, end_at):
        raise NotImplementedError


class HistoricalBarProviderTests(unittest.TestCase):
    def test_etoro_provider_normalizes_candle_payload(self) -> None:
        client = FakeEtoroClient()
        provider = EtoroHistoricalBarProvider(client=client)  # type: ignore[arg-type]
        start_at = datetime(2026, 7, 25, 14, 29, tzinfo=timezone.utc)
        end_at = datetime(2026, 7, 25, 14, 31, tzinfo=timezone.utc)

        result = provider.fetch_bars("AAPL", "1m", start_at, end_at)

        self.assertEqual("etoro", result.provider)
        self.assertEqual("OneMinute", client.candle_calls[0]["interval"])
        self.assertEqual(1, len(result.bars))
        bar = result.bars[0]
        self.assertEqual("AAPL", bar.ticker)
        self.assertEqual("1m", bar.timeframe)
        self.assertEqual(datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc), bar.bar_time)
        self.assertEqual(100.5, bar.close_price)
        self.assertEqual("etoro", bar.source)
        self.assertEqual("broker", bar.source_tier)

    def test_etoro_provider_enriches_thin_search_rows_before_candle_fetch(self) -> None:
        client = FakeEtoroClient(
            search_payload={"items": [{"instrumentId": 1001}, {"instrumentId": 15569}]},
            display_payloads={
                "1001": {
                    "instrumentDisplayDatas": [
                        {
                            "instrumentID": 1001,
                            "symbolFull": "AAPL",
                            "instrumentDisplayName": "Apple",
                        }
                    ]
                },
                "15569": {
                    "instrumentDisplayDatas": [
                        {
                            "instrumentID": 15569,
                            "symbolFull": "AAPL.24-7",
                            "instrumentDisplayName": "Apple 24/7",
                        }
                    ]
                },
            },
        )
        provider = EtoroHistoricalBarProvider(client=client)  # type: ignore[arg-type]

        result = provider.fetch_bars(
            "AAPL",
            "1m",
            datetime(2026, 7, 25, 14, 29, tzinfo=timezone.utc),
            datetime(2026, 7, 25, 14, 31, tzinfo=timezone.utc),
        )

        self.assertEqual([1001], [call["instrument_id"] for call in client.candle_calls])
        self.assertEqual(["1001", "15569"], client.display_calls)
        self.assertEqual("matched", result.diagnostics["instrument_resolution"]["status"])
        self.assertEqual("AAPL", result.diagnostics["instrument_resolution"]["raw_symbol"])

    def test_etoro_provider_resolves_safe_symbol_punctuation_alias(self) -> None:
        client = FakeEtoroClient(
            search_payload={"items": [{"instrumentId": 321}]},
            display_payloads={
                "321": {
                    "instrumentDisplayDatas": [
                        {
                            "instrumentID": 321,
                            "symbolFull": "BRK.B",
                            "instrumentDisplayName": "Berkshire Hathaway",
                        }
                    ]
                }
            },
        )
        provider = EtoroHistoricalBarProvider(client=client)  # type: ignore[arg-type]

        instrument_id, resolution = provider.resolve_instrument_id("BRK-B")

        self.assertEqual(321, instrument_id)
        self.assertEqual("matched", resolution["status"])
        self.assertEqual(["BRK-B", "BRK.B"], client.search_calls)

    def test_etoro_provider_resolves_suffixed_class_share_alias(self) -> None:
        client = FakeEtoroClient(
            search_payload={
                "MAERSK-B.CO": {"items": []},
                "MAERSK.B.CO": {"items": []},
                "MAERSK-B-CO": {"items": []},
                "MAERSKB.CO": {"items": [{"instrumentId": 5569}]},
            },
            display_payloads={
                "5569": {
                    "instrumentDisplayDatas": [
                        {
                            "instrumentID": 5569,
                            "symbolFull": "MAERSKB.CO",
                            "instrumentDisplayName": "A P Moller Maersk",
                        }
                    ]
                }
            },
        )
        provider = EtoroHistoricalBarProvider(client=client)  # type: ignore[arg-type]

        instrument_id, resolution = provider.resolve_instrument_id("MAERSK-B.CO")

        self.assertEqual(5569, instrument_id)
        self.assertEqual("MAERSKB.CO", resolution["raw_symbol"])
        self.assertIn("MAERSKB.CO", resolution["aliases"])

    def test_etoro_provider_rejects_ambiguous_instrument_resolution(self) -> None:
        provider = EtoroHistoricalBarProvider(
            client=FakeEtoroClient(  # type: ignore[arg-type]
                search_payload={
                    "items": [
                        {"instrumentId": 1001, "internalSymbolFull": "AAPL"},
                        {"instrumentId": 2002, "internalSymbolFull": "AAPL"},
                    ]
                }
            )
        )

        with self.assertRaises(HistoricalMarketDataError):
            provider.fetch_bars(
                "AAPL",
                "1m",
                datetime(2026, 7, 25, 14, 29, tzinfo=timezone.utc),
                datetime(2026, 7, 25, 14, 31, tzinfo=timezone.utc),
            )

    def test_bars_refresh_delegates_intraday_fetch_to_provider(self) -> None:
        session = create_session()
        try:
            provider = StubIntradayProvider()
            repository = HistoricalMarketDataRepository(session)
            service = BarsRefreshService(repository, provider=provider)

            result = service.refresh_bars(["AAPL"], lookback_days=2)

            self.assertEqual(1, len(provider.calls))
            self.assertEqual("1m", provider.calls[0]["timeframe"])
            self.assertEqual(1, result["total_ingested"])
            stored = repository.list_bars(ticker="AAPL", timeframe="1m", limit=5)
            self.assertEqual(1, len(stored))
            self.assertEqual("stub", stored[0].source)
        finally:
            session.close()

    def test_etoro_shadow_comparison_uses_cache_without_persisting_candidate_bars(self) -> None:
        session = create_session()
        try:
            repository = HistoricalMarketDataRepository(session)
            bar_time = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)
            repository.upsert_bar(
                HistoricalMarketBar(
                    ticker="AAPL",
                    timeframe="1m",
                    bar_time=bar_time,
                    available_at=bar_time + timedelta(minutes=1),
                    open_price=100.0,
                    high_price=101.0,
                    low_price=99.0,
                    close_price=100.0,
                    volume=1000,
                    source="yfinance_refresh",
                    source_tier="tier_a",
                )
            )
            service = EtoroBarShadowComparisonService(
                repository=repository,
                etoro_provider=StubComparisonProvider(),
                config=EtoroBarShadowComparisonConfig(
                    max_tickers=10,
                    max_median_abs_close_diff_bps=20.0,
                ),
            )

            result = service.compare(
                tickers=["AAPL"],
                end_at=datetime(2026, 7, 25, 14, 31, tzinfo=timezone.utc),
            )

            self.assertEqual("passed", result["status"])
            metrics = result["metrics"]
            self.assertEqual(1, metrics["compared_ticker_count"])
            self.assertEqual(1, metrics["overlap_bar_count"])
            self.assertEqual(10.0, metrics["median_abs_close_diff_bps"])
            stored_etoro = (
                session.query(HistoricalMarketBarRecord)
                .filter(HistoricalMarketBarRecord.source == "etoro")
                .count()
            )
            self.assertEqual(0, stored_etoro)
        finally:
            session.close()

    def test_etoro_shadow_comparison_fails_closed_when_provider_missing(self) -> None:
        session = create_session()
        try:
            service = EtoroBarShadowComparisonService(
                repository=HistoricalMarketDataRepository(session),
                etoro_provider=None,
                unavailable_reason="etoro_credentials_missing",
            )

            result = service.compare(
                tickers=["AAPL"],
                end_at=datetime(2026, 7, 25, 14, 31, tzinfo=timezone.utc),
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual(["etoro_credentials_missing"], result["warnings"])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
