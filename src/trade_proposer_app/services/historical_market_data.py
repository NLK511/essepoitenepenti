from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

import httpx

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository


class HistoricalMarketDataError(Exception):
    pass


@dataclass
class HistoricalBarProvider:
    timeout: float = 20.0

    provider_name: str = "generic"
    source_tier: str = "research"

    def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        raise NotImplementedError


class YahooHistoricalBarProvider(HistoricalBarProvider):
    provider_name = "yahoo"
    source_tier = "research"

    def __init__(self, *, timeout: float = 20.0, base_url: str = "https://query1.finance.yahoo.com") -> None:
        super().__init__(timeout=timeout)
        self.provider_name = "yahoo"
        self.source_tier = "research"
        self.base_url = base_url.rstrip("/")

    def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        normalized_start = self._normalize(start_at)
        normalized_end = self._normalize(end_at)
        period1 = int(datetime.combine(normalized_start.date() - timedelta(days=5), time.min, tzinfo=timezone.utc).timestamp())
        period2 = int(datetime.combine(normalized_end.date() + timedelta(days=2), time.min, tzinfo=timezone.utc).timestamp())
        url = (
            f"{self.base_url}/v8/finance/chart/{ticker}"
            f"?interval=1d&period1={period1}&period2={period2}&includeAdjustedClose=true&events=div%2Csplits"
        )
        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            raise HistoricalMarketDataError(f"daily bar request failed for {ticker}: {exc}") from exc
        if response.status_code != 200:
            raise HistoricalMarketDataError(f"unexpected status {response.status_code} fetching daily bars for {ticker}")
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise HistoricalMarketDataError(f"invalid JSON daily bar payload for {ticker}: {exc}") from exc
        result = ((payload or {}).get("chart") or {}).get("result") or []
        if not result:
            error = ((payload or {}).get("chart") or {}).get("error") or {}
            detail = error.get("description") or "missing chart result"
            raise HistoricalMarketDataError(f"no daily bars returned for {ticker}: {detail}")
        chart = result[0]
        timestamps = chart.get("timestamp") or []
        indicators = chart.get("indicators") or {}
        quote_rows = (indicators.get("quote") or [{}])[0]
        adjclose_rows = (indicators.get("adjclose") or [{}])[0]
        opens = quote_rows.get("open") or []
        highs = quote_rows.get("high") or []
        lows = quote_rows.get("low") or []
        closes = quote_rows.get("close") or []
        volumes = quote_rows.get("volume") or []
        adjcloses = adjclose_rows.get("adjclose") or []

        bars: list[HistoricalMarketBar] = []
        for index, raw_timestamp in enumerate(timestamps):
            if index >= len(opens) or index >= len(highs) or index >= len(lows) or index >= len(closes):
                continue
            open_price = opens[index]
            high_price = highs[index]
            low_price = lows[index]
            close_price = closes[index]
            if None in {open_price, high_price, low_price, close_price}:
                continue
            bar_dt = self._normalize(datetime.fromtimestamp(raw_timestamp, tz=timezone.utc))
            if bar_dt.date() < normalized_start.date() or bar_dt.date() > normalized_end.date():
                continue
            available_at = datetime.combine(bar_dt.date(), time(23, 59, 59), tzinfo=timezone.utc)
            metadata = {
                "provider": self.provider_name,
                "requested_start": normalized_start.isoformat(),
                "requested_end": normalized_end.isoformat(),
            }
            bars.append(
                HistoricalMarketBar(
                    ticker=ticker,
                    timeframe="1d",
                    bar_time=bar_dt,
                    available_at=available_at,
                    open_price=float(open_price),
                    high_price=float(high_price),
                    low_price=float(low_price),
                    close_price=float(close_price),
                    volume=float(volumes[index] or 0.0) if index < len(volumes) else 0.0,
                    adjusted_close=(float(adjcloses[index]) if index < len(adjcloses) and adjcloses[index] is not None else None),
                    source=self.provider_name,
                    source_tier=self.source_tier,
                    point_in_time_confidence=0.6,
                    metadata_json=json.dumps(metadata, sort_keys=True),
                )
            )
        return bars

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class HistoricalMarketDataService:
    def __init__(self, historical_market_data: HistoricalMarketDataRepository, provider: HistoricalBarProvider | None = None) -> None:
        self.historical_market_data = historical_market_data
        self.provider = provider or YahooHistoricalBarProvider()

    def ingest_daily_bars(self, *, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        bars = self.provider.fetch_daily_bars(ticker, start_at, end_at)
        persisted: list[HistoricalMarketBar] = []
        for bar in bars:
            persisted.append(self.historical_market_data.upsert_bar(bar))
        return persisted

    def hydrate_batch_inputs(self, *, tickers: list[str], start_at: datetime, end_at: datetime) -> dict[str, object]:
        ingested_by_ticker: dict[str, int] = {}
        for ticker in tickers:
            persisted = self.ingest_daily_bars(ticker=ticker, start_at=start_at, end_at=end_at)
            ingested_by_ticker[ticker] = len(persisted)
        return {
            "provider": self.provider.provider_name,
            "source_tier": self.provider.source_tier,
            "ticker_count": len(tickers),
            "bars_ingested_by_ticker": ingested_by_ticker,
            "bar_count": sum(ingested_by_ticker.values()),
            "start_at": self._normalize(start_at).isoformat(),
            "end_at": self._normalize(end_at).isoformat(),
        }

    def build_slice_market_input(self, *, tickers: list[str], as_of: datetime, lookback_bars: int = 60) -> dict[str, object]:
        normalized_as_of = self._normalize(as_of)
        ticker_inputs: list[dict[str, object]] = []
        covered = 0
        for ticker in tickers:
            bars = self.historical_market_data.list_bars(
                ticker=ticker,
                timeframe="1d",
                end_at=normalized_as_of,
                available_at=normalized_as_of,
                limit=lookback_bars,
            )
            latest = bars[-1] if bars else None
            if latest is not None:
                covered += 1
            ticker_inputs.append(
                {
                    "ticker": ticker,
                    "bar_count": len(bars),
                    "latest_bar_time": latest.bar_time.isoformat() if latest else None,
                    "latest_open": latest.open_price if latest else None,
                    "latest_close": latest.close_price if latest else None,
                    "latest_source": latest.source if latest else None,
                }
            )
        return {
            "as_of": normalized_as_of.isoformat(),
            "ticker_count": len(tickers),
            "covered_ticker_count": covered,
            "coverage_ratio": round((covered / len(tickers)) if tickers else 0.0, 4),
            "tickers": ticker_inputs,
        }

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
