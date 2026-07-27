from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from math import ceil

import httpx

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroClientError
from trade_proposer_app.services.finite_numbers import finite_float, finite_ohlc, finite_or_default
from trade_proposer_app.services.input_access import stable_hash


class HistoricalMarketDataError(Exception):
    pass


@dataclass(frozen=True)
class HistoricalBarFetchResult:
    provider: str
    source_tier: str
    timeframe: str
    bars: list[HistoricalMarketBar]
    request_count: int = 1
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass
class HistoricalBarProvider:
    timeout: float = 20.0

    provider_name: str = "generic"
    source_tier: str = "research"
    supported_timeframes: tuple[str, ...] = ("1d",)

    def fetch_bars(
        self,
        ticker: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> HistoricalBarFetchResult:
        if timeframe != "1d":
            raise HistoricalMarketDataError(
                f"{self.provider_name} does not support {timeframe} bars"
            )
        bars = self.fetch_daily_bars(ticker, start_at, end_at)
        return HistoricalBarFetchResult(
            provider=self.provider_name,
            source_tier=self.source_tier,
            timeframe=timeframe,
            bars=bars,
        )

    def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        raise NotImplementedError


class YahooHistoricalBarProvider(HistoricalBarProvider):
    provider_name = "yahoo"
    source_tier = "research"

    def __init__(self, *, timeout: float = 20.0, base_url: str = "https://query1.finance.yahoo.com") -> None:
        super().__init__(timeout=timeout)
        self.provider_name = "yahoo"
        self.source_tier = "research"
        self.supported_timeframes = ("1m", "1d")
        self.base_url = base_url.rstrip("/")

    def fetch_bars(
        self,
        ticker: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> HistoricalBarFetchResult:
        if timeframe == "1d":
            bars = self.fetch_daily_bars(ticker, start_at, end_at)
        elif timeframe == "1m":
            bars = self.fetch_intraday_bars(ticker, start_at, end_at)
        else:
            raise HistoricalMarketDataError(f"Yahoo provider does not support {timeframe} bars")
        return HistoricalBarFetchResult(
            provider=self.provider_name,
            source_tier=self.source_tier,
            timeframe=timeframe,
            bars=bars,
            diagnostics={
                "requested_start": self._normalize(start_at).isoformat(),
                "requested_end": self._normalize(end_at).isoformat(),
            },
        )

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
            ohlc = finite_ohlc(open_price, high_price, low_price, close_price)
            if ohlc is None:
                continue
            open_value, high_value, low_value, close_value = ohlc
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
                    open_price=open_value,
                    high_price=high_value,
                    low_price=low_value,
                    close_price=close_value,
                    volume=finite_or_default(volumes[index]) if index < len(volumes) else 0.0,
                    adjusted_close=(finite_float(adjcloses[index]) if index < len(adjcloses) else None),
                    source=self.provider_name,
                    source_tier=self.source_tier,
                    point_in_time_confidence=0.6,
                    metadata_json=json.dumps(metadata, sort_keys=True),
                )
            )
        return bars

    def fetch_intraday_bars(
        self,
        ticker: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[HistoricalMarketBar]:
        import pandas as pd
        import yfinance as yf

        normalized_start = self._normalize(start_at)
        normalized_end = self._normalize(end_at)
        start_str = normalized_start.strftime("%Y-%m-%d")
        end_str = (normalized_end + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            frame = yf.download(
                ticker,
                start=start_str,
                end=end_str,
                interval="1m",
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise HistoricalMarketDataError(f"intraday bar request failed for {ticker}: {exc}") from exc
        if frame is None or frame.empty:
            return []
        frame = self._normalize_downloaded_frame(ticker, frame)
        frame = frame[frame.index >= normalized_start]
        frame = frame[frame.index <= normalized_end]
        bars: list[HistoricalMarketBar] = []
        for timestamp, row in frame.iterrows():
            bar = self._create_intraday_bar_model(ticker, timestamp, row)
            if bar is not None:
                bars.append(bar)
        return bars

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_downloaded_frame(ticker: str, frame):
        import pandas as pd

        if not isinstance(frame.columns, pd.MultiIndex):
            return frame
        if ticker in frame.columns.get_level_values(1):
            return frame.xs(ticker, axis=1, level=1)
        if ticker in frame.columns.get_level_values(0):
            return frame.xs(ticker, axis=1, level=0)

        standard_cols = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        for level in range(frame.columns.nlevels):
            if any(col in standard_cols for col in frame.columns.get_level_values(level)):
                normalized = frame.copy()
                normalized.columns = normalized.columns.get_level_values(level)
                return normalized
        return frame

    def _create_intraday_bar_model(self, ticker: str, timestamp, row) -> HistoricalMarketBar | None:
        import pandas as pd

        try:
            row_dict = {str(k).strip(): v for k, v in row.to_dict().items()}
            close_val = row_dict.get("Close") or row_dict.get("Adj Close")
            close_value = finite_float(close_val)
            if close_value is None or pd.isna(close_val):
                return None

            open_val = row_dict.get("Open", close_value)
            high_val = row_dict.get("High", close_value)
            low_val = row_dict.get("Low", close_value)
            ohlc = finite_ohlc(open_val, high_val, low_val, close_value)
            if ohlc is None:
                return None
            open_value, high_value, low_value, close_value = ohlc
            volume_val = row_dict.get("Volume", 0.0)

            bar_time = timestamp.to_pydatetime()
            bar_time = self._normalize(bar_time)
            metadata = {
                "provider": self.provider_name,
                "requested_timeframe": "1m",
            }
            return HistoricalMarketBar(
                ticker=ticker,
                timeframe="1m",
                bar_time=bar_time,
                available_at=bar_time + timedelta(minutes=1),
                open_price=open_value,
                high_price=high_value,
                low_price=low_value,
                close_price=close_value,
                volume=finite_or_default(volume_val),
                source="yfinance_refresh",
                source_tier=self.source_tier,
                point_in_time_confidence=0.8,
                metadata_json=json.dumps(metadata, sort_keys=True),
            )
        except Exception:
            return None


class EtoroHistoricalBarProvider(HistoricalBarProvider):
    provider_name = "etoro"
    source_tier = "broker"

    _INTERVALS = {
        "1m": ("OneMinute", timedelta(minutes=1)),
        "5m": ("FiveMinutes", timedelta(minutes=5)),
        "10m": ("TenMinutes", timedelta(minutes=10)),
        "15m": ("FifteenMinutes", timedelta(minutes=15)),
        "30m": ("ThirtyMinutes", timedelta(minutes=30)),
        "1h": ("OneHour", timedelta(hours=1)),
        "4h": ("FourHours", timedelta(hours=4)),
        "1d": ("OneDay", timedelta(days=1)),
        "1wk": ("OneWeek", timedelta(weeks=1)),
    }

    def __init__(self, *, client: EtoroClient, timeout: float = 20.0) -> None:
        super().__init__(timeout=timeout)
        self.client = client
        self.provider_name = "etoro"
        self.source_tier = "broker"
        self.supported_timeframes = tuple(self._INTERVALS)

    def fetch_bars(
        self,
        ticker: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> HistoricalBarFetchResult:
        normalized_timeframe = self._normalize_timeframe(timeframe)
        if normalized_timeframe not in self._INTERVALS:
            raise HistoricalMarketDataError(f"eToro provider does not support {timeframe} bars")
        interval, interval_delta = self._INTERVALS[normalized_timeframe]
        normalized_start = self._normalize(start_at)
        normalized_end = self._normalize(end_at)
        instrument_id, resolution = self.resolve_instrument_id(ticker)
        requested_count = min(
            1000,
            max(1, ceil((normalized_end - normalized_start).total_seconds() / interval_delta.total_seconds()) + 2),
        )
        try:
            payload = self.client.get_instrument_candles(
                instrument_id=instrument_id,
                direction="asc",
                interval=interval,
                candles_count=requested_count,
            )
        except EtoroClientError as exc:
            raise HistoricalMarketDataError(f"eToro candle request failed for {ticker}: {exc}") from exc
        bars = self._parse_candles(
            payload=payload,
            ticker=ticker,
            timeframe=normalized_timeframe,
            interval=interval,
            instrument_id=instrument_id,
            start_at=normalized_start,
            end_at=normalized_end,
            available_delta=interval_delta,
        )
        return HistoricalBarFetchResult(
            provider=self.provider_name,
            source_tier=self.source_tier,
            timeframe=normalized_timeframe,
            bars=bars,
            diagnostics={
                "instrument_id": instrument_id,
                "instrument_resolution": resolution,
                "interval": interval,
                "candles_count": requested_count,
                "requested_start": normalized_start.isoformat(),
                "requested_end": normalized_end.isoformat(),
                "max_candles_per_request": 1000,
            },
        )

    def fetch_daily_bars(self, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        return self.fetch_bars(ticker, "1d", start_at, end_at).bars

    def resolve_instrument_id(self, ticker: str) -> tuple[int, dict[str, object]]:
        normalized = ticker.strip().upper()
        payload = self.client.search_market_data(normalized)
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            items = []
        exact = [
            item for item in items
            if isinstance(item, dict)
            and str(item.get("internalSymbolFull") or "").strip().upper() == normalized
            and item.get("instrumentId") is not None
        ]
        if len(exact) != 1:
            raise HistoricalMarketDataError(
                f"eToro instrument resolution for {ticker} returned {len(exact)} exact matches"
            )
        instrument_id = int(exact[0]["instrumentId"])
        return instrument_id, {
            "ticker": normalized,
            "match_count": len(exact),
            "instrument_id": instrument_id,
            "raw_name": exact[0].get("name"),
            "raw_symbol": exact[0].get("internalSymbolFull"),
        }

    @classmethod
    def _parse_candles(
        cls,
        *,
        payload: dict[str, object],
        ticker: str,
        timeframe: str,
        interval: str,
        instrument_id: int,
        start_at: datetime,
        end_at: datetime,
        available_delta: timedelta,
    ) -> list[HistoricalMarketBar]:
        groups = payload.get("candles") if isinstance(payload, dict) else None
        if not isinstance(groups, list):
            return []
        bars: list[HistoricalMarketBar] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            candles = group.get("candles")
            if not isinstance(candles, list):
                continue
            for candle in candles:
                if not isinstance(candle, dict):
                    continue
                bar = cls._bar_from_candle(
                    candle=candle,
                    ticker=ticker,
                    timeframe=timeframe,
                    interval=interval,
                    instrument_id=instrument_id,
                    start_at=start_at,
                    end_at=end_at,
                    available_delta=available_delta,
                )
                if bar is not None:
                    bars.append(bar)
        return bars

    @classmethod
    def _bar_from_candle(
        cls,
        *,
        candle: dict[str, object],
        ticker: str,
        timeframe: str,
        interval: str,
        instrument_id: int,
        start_at: datetime,
        end_at: datetime,
        available_delta: timedelta,
    ) -> HistoricalMarketBar | None:
        try:
            raw_time = candle.get("fromDate")
            if not raw_time:
                return None
            bar_time = cls._normalize_datetime_string(str(raw_time))
            if bar_time < start_at or bar_time > end_at:
                return None
            ohlc = finite_ohlc(
                candle.get("open"),
                candle.get("high"),
                candle.get("low"),
                candle.get("close"),
            )
            if ohlc is None:
                return None
            open_price, high_price, low_price, close_price = ohlc
            volume = finite_or_default(candle.get("volume"))
            if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
                return None
            metadata = {
                "provider": "etoro",
                "instrument_id": instrument_id,
                "interval": interval,
                "raw_from_date": raw_time,
            }
            return HistoricalMarketBar(
                ticker=ticker.strip().upper(),
                timeframe=timeframe,
                bar_time=bar_time,
                available_at=bar_time + available_delta,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
                source="etoro",
                source_tier="broker",
                point_in_time_confidence=0.8,
                metadata_json=json.dumps(metadata, sort_keys=True),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        return "1h" if timeframe == "60m" else timeframe

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _normalize_datetime_string(cls, value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return cls._normalize(parsed)


class HistoricalMarketDataService:
    def __init__(self, historical_market_data: HistoricalMarketDataRepository, provider: HistoricalBarProvider | None = None) -> None:
        self.historical_market_data = historical_market_data
        self.provider = provider or YahooHistoricalBarProvider()

    def fetch_bars(
        self,
        *,
        ticker: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> HistoricalBarFetchResult:
        fetcher = getattr(self.provider, "fetch_bars", None)
        if callable(fetcher):
            return fetcher(ticker, timeframe, start_at, end_at)
        if timeframe != "1d":
            raise HistoricalMarketDataError(
                f"{self.provider.provider_name} does not support {timeframe} bars"
            )
        bars = self.provider.fetch_daily_bars(ticker, start_at, end_at)
        return HistoricalBarFetchResult(
            provider=self.provider.provider_name,
            source_tier=self.provider.source_tier,
            timeframe=timeframe,
            bars=bars,
        )

    def ingest_bars(
        self,
        *,
        ticker: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[HistoricalMarketBar]:
        result = self.fetch_bars(
            ticker=ticker,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )
        return self.persist_bars(result.bars)

    def persist_bars(self, bars: list[HistoricalMarketBar]) -> list[HistoricalMarketBar]:
        if not bars:
            return []
        sub_batch_size = 1000
        for index in range(0, len(bars), sub_batch_size):
            self.historical_market_data.upsert_bars(bars[index : index + sub_batch_size])
        return bars

    def ingest_daily_bars(self, *, ticker: str, start_at: datetime, end_at: datetime) -> list[HistoricalMarketBar]:
        return self.ingest_bars(ticker=ticker, timeframe="1d", start_at=start_at, end_at=end_at)

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

    def build_replay_coverage_report(
        self,
        *,
        tickers: list[str],
        as_of: datetime,
        lookback_days: int = 90,
        resolution_days: int = 5,
        minimum_generation_daily_bars: int = 10,
        input_policy: str = "cache_only",
        source: str = "cache",
    ) -> dict[str, object]:
        """Report point-in-time replay readiness without mixing generation and outcome data."""

        normalized_as_of = self._normalize(as_of)
        generation_start = normalized_as_of - timedelta(days=max(1, lookback_days))
        resolution_end = normalized_as_of + timedelta(days=max(1, resolution_days))
        ticker_reports: list[dict[str, object]] = []
        tier_counts = {"tier_a": 0, "tier_b": 0, "tier_c": 0, "ineligible": 0}
        for ticker in tickers:
            generation_daily_count = self.historical_market_data.count_bars(
                ticker=ticker,
                timeframe="1d",
                start_at=generation_start,
                end_at=normalized_as_of,
                available_at=normalized_as_of,
            )
            generation_intraday_count = self.historical_market_data.count_bars(
                ticker=ticker,
                timeframe="1m",
                start_at=generation_start,
                end_at=normalized_as_of,
                available_at=normalized_as_of,
            )
            resolution_intraday_count = self.historical_market_data.count_bars(
                ticker=ticker,
                timeframe="1m",
                start_at=normalized_as_of,
                end_at=resolution_end,
                available_at=None,
            )
            resolution_daily_count = self.historical_market_data.count_bars(
                ticker=ticker,
                timeframe="1d",
                start_at=normalized_as_of,
                end_at=resolution_end,
                available_at=None,
            )
            blockers: list[str] = []
            warnings: list[str] = []
            if generation_daily_count < minimum_generation_daily_bars:
                blockers.append("insufficient_generation_daily_bars")
            if generation_intraday_count <= 0:
                warnings.append("missing_generation_intraday_bars")
            if resolution_intraday_count <= 0:
                warnings.append("missing_resolution_intraday_bars")
            if resolution_intraday_count > 0 and not blockers:
                tier = "tier_a"
            elif resolution_daily_count > 0 and not blockers:
                tier = "tier_b"
                warnings.append("resolution_daily_fallback_only")
            elif generation_daily_count > 0:
                tier = "tier_c"
                blockers.append("missing_resolution_bars")
            else:
                tier = "ineligible"
            tier_counts[tier] += 1
            ticker_reports.append(
                {
                    "ticker": ticker,
                    "tier": tier,
                    "generation": {
                        "lookback_start": generation_start.isoformat(),
                        "as_of": normalized_as_of.isoformat(),
                        "daily_bar_count": generation_daily_count,
                        "intraday_1m_bar_count": generation_intraday_count,
                        "point_in_time_filter": "available_at <= as_of",
                    },
                    "resolution": {
                        "start_at": normalized_as_of.isoformat(),
                        "end_at": resolution_end.isoformat(),
                        "intraday_1m_bar_count": resolution_intraday_count,
                        "daily_bar_count": resolution_daily_count,
                        "uses_post_as_of_data_for_evaluation_only": True,
                    },
                    "blockers": blockers,
                    "warnings": warnings,
                }
            )
        report = {
            "as_of": normalized_as_of.isoformat(),
            "policy": input_policy,
            "source": source,
            "lookback_days": lookback_days,
            "resolution_days": resolution_days,
            "ticker_count": len(tickers),
            "tier_counts": tier_counts,
            "tier_a_ratio": round((tier_counts["tier_a"] / len(tickers)) if tickers else 0.0, 4),
            "tickers": ticker_reports,
        }
        report["input_coverage_hash"] = stable_hash(report)
        return report

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
