from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import pandas as pd
import yfinance as yf
from pydantic import BaseModel, Field

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository


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
        
        # If we have a repository and an as_of time, use the DB
        if self.repository and as_of:
            history = self._fetch_from_db(normalized_ticker, as_of)
        else:
            history = self.history_fetcher(normalized_ticker, period, as_of)
            
        if history.empty:
            raise CheapScanError(f"no price history available for {normalized_ticker}")
        if len(history) < 30:
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
        avg_dollar_volume_20 = float((closes * volumes).tail(20).mean())
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
        liquidity_score = round(self._scale_value(avg_dollar_volume_20, 5_000_000.0, 150_000_000.0), 2)
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
        if avg_dollar_volume_20 < 5_000_000:
            warnings.append("low average dollar volume on cheap scan")
        if len(history) < 60:
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
                "avg_dollar_volume_20": round(avg_dollar_volume_20, 2),
                "realized_volatility_20": round(realized_volatility_20, 4),
                "model": "cheap_scan_v1",
                "data_source": "database" if self.repository and as_of else "yahoo",
            },
            indicator_summary=" · ".join(summary_parts),
        )

    def _fetch_from_db(self, ticker: str, as_of: datetime) -> pd.DataFrame:
        if self.repository is None:
            return pd.DataFrame()
        
        # Fetch 1d bars from DB where available_at <= as_of
        # We need at least 60 bars for a full SMA50
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

    @staticmethod
    def _fetch_price_history(ticker: str, period: str, as_of: datetime | None = None) -> pd.DataFrame:
        # yfinance doesn't easily support 'as_of' for history without manual start/end
        if as_of:
            # Not implemented for yahoo provider in this simplified version
            return pd.DataFrame()
        history = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
        if history is None or history.empty:
            return pd.DataFrame()
        return history
