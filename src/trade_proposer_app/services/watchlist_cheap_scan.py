from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pandas as pd
import time
import yfinance as yf
from pydantic import BaseModel, Field

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.retry_utils import bounded_backoff_seconds


class CheapScanSignal(BaseModel):
    ticker: str
    horizon: StrategyHorizon
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ok"
    directional_bias: str = "neutral"
    directional_score: float = 0.0
    confidence_percent: float = 0.0
    attention_score: float = 0.0
    trend_score: float = 0.0
    momentum_score: float = 0.0
    breakout_score: float = 0.0
    volatility_score: float = 0.0
    liquidity_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    diagnostics: dict[str, object] = Field(default_factory=dict)
    indicator_summary: str = ""


class CheapScanError(Exception):
    pass


class CheapScanSignalService:
    MIN_HISTORY_BARS_LIVE = 30
    MIN_HISTORY_BARS_REPLAY = 10
    REMOTE_FALLBACK_MIN_BARS = 30
    FULL_SMA_LOOKBACK_BARS = 50
    LIVE_REMOTE_FETCH_ATTEMPTS = 3
    LIVE_REMOTE_FETCH_BACKOFF_SECONDS = (0.0, 1.0, 3.0)

    def __init__(
        self,
        history_fetcher: Callable[[str, str, datetime | None], pd.DataFrame] | None = None,
        repository: HistoricalMarketDataRepository | None = None,
    ) -> None:
        self.repository = repository
        self.history_fetcher = history_fetcher or self._fetch_price_history

    def score(self, ticker: str, horizon: StrategyHorizon, as_of: datetime | None = None) -> CheapScanSignal:
        normalized_ticker = ticker.strip().upper()
        period = self._period_for_horizon(horizon)
        
        from trade_proposer_app.services.watchlist_orchestration import logger
        logger.info(f"    [CheapScan] {normalized_ticker} as_of={as_of}")
        
        history = pd.DataFrame()
        history_source = "unavailable"
        is_replay = bool(as_of)
        remote_attempt_count = 0
        remote_errors: list[str] = []

        # 1. Prefer local DB data
        if self.repository:
            history = self._fetch_from_db(normalized_ticker, as_of or datetime.now(timezone.utc), is_replay=is_replay)
            if not history.empty:
                history_source = "database"

        # 2. Fallback to remote data if local is missing or insufficient for the live minimum feature set.
        if history.empty or len(history) < self.REMOTE_FALLBACK_MIN_BARS:
            remote_history, remote_attempt_count, remote_errors = self._fetch_remote_history_with_retry(normalized_ticker, period, as_of=as_of)
            if not remote_history.empty:
                # Use remote data if it's better/longer than what we have locally
                if len(remote_history) > len(history):
                    history = remote_history
                    history_source = "yahoo"
                    # 3. Take the opportunity to persist it locally
                    if self.repository:
                        try:
                            self._persist_history(normalized_ticker, history)
                        except Exception as e:
                            logger.warning(f"    [CheapScan] failed to persist remote history for {normalized_ticker}: {e}")

        if history.empty:
            raise CheapScanError(f"no price history available for {normalized_ticker}")

        min_history = self.MIN_HISTORY_BARS_REPLAY if is_replay else self.MIN_HISTORY_BARS_LIVE
        if len(history) < min_history:
            raise CheapScanError(f"insufficient price history for {normalized_ticker} (found {len(history)} bars)")

        closes = self._series(history, "Close")
        volumes = self._series(history, "Volume")
        latest_close = float(closes.iloc[-1])
        sma20 = float(closes.tail(20).mean())
        sma50 = float(closes.tail(min(50, len(closes))).mean())
        returns = closes.pct_change().dropna()
        ret5 = self._pct_change(closes, 5)
        ret20 = self._pct_change(closes, 20)
        rolling_high_20 = float(closes.tail(20).max())
        rolling_low_20 = float(closes.tail(20).min())
        avg_traded_value_20 = float((closes * volumes).tail(20).mean())
        realized_volatility_20 = float(returns.tail(20).std(ddof=0) * 100.0) if len(returns) >= 5 else 0.0

        trend_component = self._clamp(((latest_close / sma20) - 1.0) * 8.0 + ((latest_close / sma50) - 1.0) * 6.0, -1.0, 1.0)
        momentum_component = self._clamp((ret5 * 4.0) + (ret20 * 3.0), -1.0, 1.0)
        breakout_component = self._breakout_component(latest_close, rolling_high_20, rolling_low_20)

        directional_score = self._clamp(
            0.45 * trend_component + 0.4 * momentum_component + 0.15 * breakout_component,
            -1.0,
            1.0,
        )
        directional_bias = "neutral"
        if directional_score >= 0.12:
            directional_bias = "long"
        elif directional_score <= -0.12:
            directional_bias = "short"

        trend_score = round(self._scale_signed_to_percent(trend_component), 2)
        momentum_score = round(self._scale_signed_to_percent(momentum_component), 2)
        breakout_score = round(self._scale_signed_to_percent(breakout_component), 2)
        volatility_score = round(self._scale_value(realized_volatility_20, 1.0, 6.0), 2)
        liquidity_score = round(self._scale_value(avg_traded_value_20, 5_000_000.0, 150_000_000.0), 2)
        confidence_percent = round(
            self._clamp(
                abs(directional_score) * 70.0 + liquidity_score * 0.15 + (100.0 - abs(50.0 - volatility_score)) * 0.15,
                0.0,
                100.0,
            ),
            2,
        )
        attention_score = round(
            self._clamp(
                abs(directional_score) * 45.0 + breakout_score * 0.2 + volatility_score * 0.15 + liquidity_score * 0.2,
                0.0,
                100.0,
            ),
            2,
        )

        warnings: list[str] = []
        history_bar_count = len(history)
        if avg_traded_value_20 < 5_000_000:
            warnings.append("low average traded value on cheap scan")
        if history_bar_count < self.FULL_SMA_LOOKBACK_BARS:
            warnings.append("cheap scan used limited lookback history")

        summary_parts = [
            f"trend {trend_score:.0f}",
            f"momentum {momentum_score:.0f}",
            f"breakout {breakout_score:.0f}",
            f"attention {attention_score:.0f}",
        ]
        return CheapScanSignal(
            ticker=normalized_ticker,
            horizon=horizon,
            computed_at=as_of or datetime.now(timezone.utc),
            status="partial" if warnings else "ok",
            directional_bias=directional_bias,
            directional_score=round(directional_score, 4),
            confidence_percent=confidence_percent,
            attention_score=attention_score,
            trend_score=trend_score,
            momentum_score=momentum_score,
            breakout_score=breakout_score,
            volatility_score=volatility_score,
            liquidity_score=liquidity_score,
            warnings=warnings,
            diagnostics={
                "latest_close": round(latest_close, 4),
                "sma20": round(sma20, 4),
                "sma50": round(sma50, 4),
                "return_5d_percent": round(ret5 * 100.0, 4),
                "return_20d_percent": round(ret20 * 100.0, 4),
                "avg_traded_value_20": round(avg_traded_value_20, 2),
                "liquidity_metric_currency": "raw_quote_currency_not_normalized",
                "realized_volatility_20": round(realized_volatility_20, 4),
                "history_bar_count": history_bar_count,
                "effective_sma50_window": min(self.FULL_SMA_LOOKBACK_BARS, history_bar_count),
                "model": "cheap_scan_v1",
                "data_source": history_source,
                "price_history": {
                    "ticker": normalized_ticker,
                    "mode": "replay" if is_replay else "live",
                    "source": history_source,
                    "fallback_used": history_source == "yahoo" and bool(self.repository),
                    "remote_attempt_count": remote_attempt_count,
                    "remote_errors": remote_errors,
                    "selected_bar_count": history_bar_count,
                },
            },
            indicator_summary=" · ".join(summary_parts),
        )

    def _fetch_from_db(self, ticker: str, as_of: datetime, is_replay: bool = True) -> pd.DataFrame:
        if self.repository is None:
            return pd.DataFrame()
        
        # 1. First choice: 1m bars resampled to daily
        # We fetch a large number of bars to cover the required history (e.g., 60-90 days)
        bars = self.repository.list_bars(
            ticker=ticker,
            timeframe="1m",
            end_at=as_of,
            available_at=as_of,
            limit=50000
        )
        
        if bars:
            data = []
            for b in bars:
                data.append({
                    "Date": b.bar_time,
                    "Open": b.open_price,
                    "High": b.high_price,
                    "Low": b.low_price,
                    "Close": b.close_price,
                    "Volume": b.volume
                })
            df = pd.DataFrame(data)
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
            
            # Resample to daily OHLCV
            # Using '1D' and labeling with 'left' so the date is the start of the day
            resampled = df.resample('1D').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            
            # For replay, we might have very limited history in the database (e.g. 6-7 days)
            # We relax the requirement slightly but keep it high enough to be meaningful.
            min_bars = self.MIN_HISTORY_BARS_REPLAY if is_replay else self.MIN_HISTORY_BARS_LIVE
            if not resampled.empty and len(resampled) >= min_bars:
                return resampled

        # 2. Fallback: 1d bars (ONLY for replay)
        if not is_replay:
            return pd.DataFrame()

        bars = self.repository.list_bars(
            ticker=ticker,
            timeframe="1d",
            end_at=as_of,
            available_at=as_of,
            limit=100
        )
        if not bars:
            return pd.DataFrame()
            
        data = []
        for b in bars:
            data.append({
                "Date": b.bar_time,
                "Open": b.open_price,
                "High": b.high_price,
                "Low": b.low_price,
                "Close": b.close_price,
                "Volume": b.volume
            })
        
        df = pd.DataFrame(data)
        df.set_index("Date", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _persist_history(self, ticker: str, df: pd.DataFrame) -> None:
        if self.repository is None:
            return
            
        bars = []
        for timestamp, row in df.iterrows():
            # If the index is a DatetimeIndex
            bar_time = timestamp if isinstance(timestamp, datetime) else pd.to_datetime(timestamp)
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            
            bars.append(HistoricalMarketBar(
                ticker=ticker,
                timeframe="1d",
                bar_time=bar_time,
                available_at=datetime.combine(bar_time.date(), datetime.max.time(), tzinfo=timezone.utc),
                open_price=float(row["Open"]),
                high_price=float(row["High"]),
                low_price=float(row["Low"]),
                close_price=float(row["Close"]),
                volume=int(row["Volume"]),
                source="yahoo_fallback",
                source_tier="tier_b",
                point_in_time_confidence=0.8,
            ))
        
        if bars:
            self.repository.upsert_bars(bars)

    @staticmethod
    def _series(history: pd.DataFrame, column: str) -> pd.Series:
        if column not in history.columns:
            raise CheapScanError(f"missing required column: {column}")
        return pd.to_numeric(history[column], errors="coerce").dropna()

    @staticmethod
    def _pct_change(series: pd.Series, periods: int) -> float:
        if len(series) <= periods:
            return 0.0
        previous = float(series.iloc[-periods - 1])
        current = float(series.iloc[-1])
        if previous == 0:
            return 0.0
        return (current / previous) - 1.0

    @staticmethod
    def _breakout_component(latest_close: float, rolling_high: float, rolling_low: float) -> float:
        if rolling_high <= rolling_low:
            return 0.0
        midpoint = (rolling_high + rolling_low) / 2.0
        half_range = max((rolling_high - rolling_low) / 2.0, 1e-9)
        return CheapScanSignalService._clamp((latest_close - midpoint) / half_range, -1.0, 1.0)

    @staticmethod
    def _scale_signed_to_percent(value: float) -> float:
        return max(0.0, min(100.0, (value + 1.0) * 50.0))

    @staticmethod
    def _scale_value(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        normalized = (value - low) / (high - low)
        return max(0.0, min(100.0, normalized * 100.0))

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _period_for_horizon(horizon: StrategyHorizon) -> str:
        if horizon == StrategyHorizon.ONE_DAY:
            return "3mo"
        if horizon == StrategyHorizon.ONE_MONTH:
            return "1y"
        return "6mo"

    def _fetch_remote_history_with_retry(self, ticker: str, period: str, *, as_of: datetime | None = None) -> tuple[pd.DataFrame, int, list[str]]:
        attempts = 1 if as_of is not None else self.LIVE_REMOTE_FETCH_ATTEMPTS
        errors: list[str] = []
        for attempt in range(attempts):
            backoff = bounded_backoff_seconds(self.LIVE_REMOTE_FETCH_BACKOFF_SECONDS, attempt, enabled=as_of is None)
            if backoff > 0:
                time.sleep(backoff)
            try:
                history = self.history_fetcher(ticker, period, as_of)
            except Exception as exc:
                errors.append(str(exc))
                continue
            if history is not None and not history.empty:
                return history, attempt + 1, errors
            errors.append(f"no remote price history returned for {ticker}")
        return pd.DataFrame(), attempts, errors

    @staticmethod
    def _fetch_price_history(ticker: str, period: str, as_of: datetime | None = None) -> pd.DataFrame:
        # yfinance doesn't easily support 'as_of' for history without manual start/end
        if as_of:
            # Calculate a start date based on the period
            # period is typically '3mo', '6mo', '1y'
            days_map = {'3mo': 90, '6mo': 180, '1y': 365, '2y': 730}
            days = days_map.get(period, 180)
            start_at = as_of - timedelta(days=days)
            
            # yfinance expects strings or date objects
            history = yf.download(
                ticker,
                start=start_at.date().isoformat(),
                end=(as_of + timedelta(days=1)).date().isoformat(),
                interval="1d",
                progress=False,
                auto_adjust=False,
            )
            if history is None or history.empty:
                return pd.DataFrame()
            
            # Handle MultiIndex if present (yfinance v0.2.x behavior)
            if isinstance(history.columns, pd.MultiIndex):
                if ticker in history.columns.get_level_values(1):
                    history = history.xs(ticker, axis=1, level=1)
                elif ticker in history.columns.get_level_values(0):
                    history = history.xs(ticker, axis=1, level=0)
            
            return history

        history = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
        if history is None or history.empty:
            return pd.DataFrame()

        # Handle MultiIndex if present
        if isinstance(history.columns, pd.MultiIndex):
            if ticker in history.columns.get_level_values(1):
                history = history.xs(ticker, axis=1, level=1)
            elif ticker in history.columns.get_level_values(0):
                history = history.xs(ticker, axis=1, level=0)

        return history
