from __future__ import annotations

from collections import OrderedDict
from typing import Any

import pandas as pd

from trade_proposer_app.services.proposals import (
    AGGREGATOR_DEFAULTS,
    DEFAULT_SUMMARY_METHOD,
    DEFAULT_SUMMARY_TEXT,
    FEATURE_COLUMN_MAP,
    MANUAL_FEATURE_RANGES,
    RANGE_COLUMNS,
)


class TickerTechnicalFeatureService:
    """Build technical feature, context, normalization, and aggregate score payloads for ticker deep analysis."""

    def enrich_history(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["SMA_20"] = enriched["Close"].rolling(window=20).mean()
        enriched["SMA_50"] = enriched["Close"].rolling(window=50).mean()
        enriched["SMA_200"] = enriched["Close"].rolling(window=200).mean()
        enriched["RSI_14"] = self.calculate_rsi(enriched)
        enriched["ATR_14"] = self.calculate_atr(enriched)
        enriched["atr_pct"] = (enriched["ATR_14"] / enriched["Close"]) * 100
        enriched["momentum_short"] = enriched["Close"].pct_change(periods=5)
        enriched["momentum_medium"] = enriched["Close"].pct_change(periods=21)
        enriched["momentum_long"] = enriched["Close"].pct_change(periods=63)
        enriched["price_change_1d"] = enriched["Close"].pct_change(periods=1)
        enriched["price_change_10d"] = enriched["Close"].pct_change(periods=10)
        enriched["price_change_63d"] = enriched["Close"].pct_change(periods=63)
        enriched["price_change_126d"] = enriched["Close"].pct_change(periods=126)
        enriched["entry_delta_2w"] = enriched["price_change_10d"]
        enriched["entry_delta_3m"] = enriched["price_change_63d"]
        enriched["entry_delta_12m"] = enriched["Close"].pct_change(periods=252)
        enriched["price_vs_sma20_ratio"] = self.compute_ratio_series(enriched["Close"], enriched["SMA_20"])
        enriched["price_vs_sma50_ratio"] = self.compute_ratio_series(enriched["Close"], enriched["SMA_50"])
        enriched["price_vs_sma200_ratio"] = self.compute_ratio_series(enriched["Close"], enriched["SMA_200"])
        enriched["price_vs_sma20_diff"] = enriched["Close"] - enriched["SMA_20"]
        enriched["price_vs_sma50_diff"] = enriched["Close"] - enriched["SMA_50"]
        enriched["price_vs_sma200_diff"] = enriched["Close"] - enriched["SMA_200"]
        enriched["price_vs_sma20_slope"] = enriched["price_vs_sma20_diff"].pct_change(periods=5)
        enriched["price_vs_sma50_slope"] = enriched["price_vs_sma50_diff"].pct_change(periods=10)
        enriched["price_vs_sma200_slope"] = enriched["price_vs_sma200_diff"].pct_change(periods=20)
        enriched["volatility_band_upper"] = enriched["SMA_20"] + enriched["ATR_14"]
        enriched["volatility_band_lower"] = enriched["SMA_20"] - enriched["ATR_14"]
        enriched["volatility_band_width"] = enriched["volatility_band_upper"] - enriched["volatility_band_lower"]
        return enriched

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).ewm(com=window - 1, min_periods=window).mean()
        loss = -delta.clip(upper=0).ewm(com=window - 1, min_periods=window).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.ffill().fillna(50.0)

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(window=period).mean().ffill().fillna(0.0)

    @staticmethod
    def compute_ratio_series(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        safe_den = denominator.replace(0, pd.NA)
        ratio = numerator.divide(safe_den)
        ratio = ratio.replace([float("inf"), float("-inf")], pd.NA)
        return (ratio - 1).fillna(0.0)

    def build_context(self, df: pd.DataFrame) -> dict[str, Any]:
        latest = df.iloc[-1]
        price = float(latest.get("Close", 0.0) or 0.0)
        sma20 = float(latest.get("SMA_20") or 0.0)
        sma50 = float(latest.get("SMA_50") or 0.0)
        sma200 = float(latest.get("SMA_200") or 0.0)
        rsi = float(latest.get("RSI_14") or 50.0)
        atr = float(latest.get("ATR_14") or 0.0)
        atr_pct = float(latest.get("atr_pct") or 0.0)
        momentum_short = float(latest.get("momentum_short") or 0.0)
        momentum_medium = float(latest.get("momentum_medium") or 0.0)
        momentum_long = float(latest.get("momentum_long") or 0.0)
        price_above_sma50 = 1 if price > sma50 else 0
        price_above_sma200 = 1 if price > sma200 else 0
        direction = "LONG" if price > sma200 else "SHORT"

        short_bullish = 0.0
        short_bearish = 0.0
        if price > sma20:
            short_bullish += 1.0
        else:
            short_bearish += 1.0
        if rsi < 30:
            short_bullish += 1.0
        elif rsi > 70:
            short_bearish += 1.0
        if price_above_sma50:
            short_bullish += 1.0
        else:
            short_bearish += 1.0

        medium_bullish = 0.0
        medium_bearish = 0.0
        if price > sma50:
            medium_bullish += 1.0
        else:
            medium_bearish += 1.0
        if price > sma200:
            medium_bullish += 1.0
        else:
            medium_bearish += 1.0
        if price_above_sma200:
            medium_bullish += 1.0
        else:
            medium_bearish += 1.0

        problems: list[str] = []
        if sma200 == 0.0:
            problems.append("history: insufficient data for SMA200")

        context = {
            "price": price,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "rsi": rsi,
            "atr": atr,
            "atr_pct": atr_pct,
            "momentum_short": momentum_short,
            "momentum_medium": momentum_medium,
            "momentum_long": momentum_long,
            "price_change_1d": float(latest.get("price_change_1d") or 0.0),
            "price_change_10d": float(latest.get("price_change_10d") or 0.0),
            "price_change_63d": float(latest.get("price_change_63d") or 0.0),
            "price_change_126d": float(latest.get("price_change_126d") or 0.0),
            "entry_delta_2w": float(latest.get("entry_delta_2w") or 0.0),
            "entry_delta_3m": float(latest.get("entry_delta_3m") or 0.0),
            "entry_delta_12m": float(latest.get("entry_delta_12m") or 0.0),
            "price_vs_sma20_ratio": float(latest.get("price_vs_sma20_ratio") or 0.0),
            "price_vs_sma50_ratio": float(latest.get("price_vs_sma50_ratio") or 0.0),
            "price_vs_sma200_ratio": float(latest.get("price_vs_sma200_ratio") or 0.0),
            "price_vs_sma20_slope": float(latest.get("price_vs_sma20_slope") or 0.0),
            "price_vs_sma50_slope": float(latest.get("price_vs_sma50_slope") or 0.0),
            "price_vs_sma200_slope": float(latest.get("price_vs_sma200_slope") or 0.0),
            "volatility_band_upper": float(latest.get("volatility_band_upper") or 0.0),
            "volatility_band_lower": float(latest.get("volatility_band_lower") or 0.0),
            "volatility_band_width": float(latest.get("volatility_band_width") or 0.0),
            "price_above_sma50": price_above_sma50,
            "price_above_sma200": price_above_sma200,
            "rel_return_5d_vs_spy": 0.0,
            "rel_return_20d_vs_spy": 0.0,
            "rel_return_5d_vs_sector": 0.0,
            "rel_return_20d_vs_sector": 0.0,
            "volume_ratio_20": 1.0,
            "dollar_volume_ratio_20": 1.0,
            "reference_features": {"benchmark_symbol": "SPY", "sector_etf_symbol": None, "benchmark_available": False, "sector_available": False, "notes": []},
            "short_bullish": short_bullish,
            "short_bearish": short_bearish,
            "medium_bullish": medium_bullish,
            "medium_bearish": medium_bearish,
            "direction": direction,
            "sentiment_score": 0.0,
            "sentiment_label": "PRICE_ONLY",
            "news_sentiment_score": 0.0,
            "enhanced_sentiment_score": 0.0,
            "social_sentiment_score": 0.0,
            "macro_sentiment_score": 0.0,
            "macro_sentiment_label": "NEUTRAL",
            "macro_context_score": 0.0,
            "macro_context_label": "NEUTRAL",
            "macro_item_count": 0,
            "macro_coverage_insights": [],
            "industry_sentiment_score": 0.0,
            "industry_sentiment_label": "NEUTRAL",
            "industry_context_score": 0.0,
            "industry_context_label": "NEUTRAL",
            "industry_item_count": 0,
            "industry_coverage_insights": [],
            "ticker_sentiment_score": 0.0,
            "ticker_sentiment_label": None,
            "ticker_item_count": 0,
            "source_count": 0,
            "context_count": 0,
            "news_point_count": 0,
            "news_item_count": 0,
            "news_items": [],
            "news_feeds_used": [],
            "news_feed_errors": [],
            "signal_feed_errors": [],
            "sentiment_sources": [],
            "sentiment_volatility": 0.0,
            "polarity_trend": 0.0,
            "summary_text": DEFAULT_SUMMARY_TEXT,
            "summary_method": DEFAULT_SUMMARY_METHOD,
            "summary_error": None,
            "llm_error": None,
            "summary_backend": None,
            "summary_model": None,
            "summary_runtime_seconds": None,
            "summary_metadata": {},
            "news_digest": "",
            "ticker_profile": {},
            "problems": problems,
            "context_tag_earnings": 0.0,
            "context_tag_geopolitical": 0.0,
            "context_tag_industry": 0.0,
            "context_tag_general": 0.0,
        }
        return context

    @staticmethod
    def compute_column_ranges(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
        ranges: dict[str, tuple[float, float]] = {}
        for column in RANGE_COLUMNS:
            if column not in df.columns:
                continue
            clean = df[column].dropna()
            if clean.empty:
                ranges[column] = (0.0, 0.0)
                continue
            ranges[column] = (float(clean.min()), float(clean.max()))
        return ranges

    def build_feature_vector(self, context: dict[str, Any]) -> dict[str, float]:
        vector = OrderedDict()
        for key in (
            "price_close",
            "sma20",
            "sma50",
            "sma200",
            "rsi",
            "atr",
            "atr_pct",
            "volatility_band_upper",
            "volatility_band_lower",
            "volatility_band_width",
            "momentum_short",
            "momentum_medium",
            "momentum_long",
            "rel_return_5d_vs_spy",
            "rel_return_20d_vs_spy",
            "rel_return_5d_vs_sector",
            "rel_return_20d_vs_sector",
            "volume_ratio_20",
            "dollar_volume_ratio_20",
            "price_change_1d",
            "price_change_10d",
            "price_change_63d",
            "price_change_126d",
            "entry_delta_2w",
            "entry_delta_3m",
            "entry_delta_12m",
            "price_vs_sma20_ratio",
            "price_vs_sma50_ratio",
            "price_vs_sma200_ratio",
            "price_vs_sma20_slope",
            "price_vs_sma50_slope",
            "price_vs_sma200_slope",
            "short_bullish",
            "short_bearish",
            "medium_bullish",
            "medium_bearish",
            "sentiment_score",
            "enhanced_sentiment_score",
            "news_sentiment_score",
            "social_sentiment_score",
            "macro_sentiment_score",
            "industry_sentiment_score",
            "ticker_sentiment_score",
            "social_item_count",
            "macro_item_count",
            "industry_item_count",
            "ticker_item_count",
            "source_count",
            "context_count",
            "news_point_count",
            "polarity_trend",
            "sentiment_volatility",
            "context_tag_earnings",
            "context_tag_geopolitical",
            "context_tag_industry",
            "context_tag_general",
        ):
            value = context.get(key, context.get("price" if key == "price_close" else key, 0.0))
            vector[key] = float(value or 0.0)
        return vector

    def normalize_feature_vector(
        self,
        feature_vector: dict[str, float],
        column_ranges: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, raw_value in feature_vector.items():
            column = FEATURE_COLUMN_MAP.get(key)
            bounds = column_ranges.get(column, MANUAL_FEATURE_RANGES.get(key, (0.0, 1.0))) if column else MANUAL_FEATURE_RANGES.get(key, (0.0, 1.0))
            normalized[key] = self.normalize_value(raw_value, bounds)
        return normalized

    @staticmethod
    def normalize_value(value: float, bounds: tuple[float, float]) -> float:
        min_val, max_val = bounds
        if max_val == min_val:
            return 0.5
        return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))

    @staticmethod
    def compute_aggregations(normalized: dict[str, float], atr: float, price: float, *, weights: dict[str, object] | None = None) -> dict[str, float]:
        def center(value: float) -> float:
            return value - 0.5

        configured = weights or {}
        configured_aggregators = configured.get("aggregators", {}) if isinstance(configured, dict) else {}
        direction_weights = {**AGGREGATOR_DEFAULTS["direction"], **configured_aggregators.get("direction", {})}
        risk_weights = {**AGGREGATOR_DEFAULTS["risk"], **configured_aggregators.get("risk", {})}
        entry_weights = {**AGGREGATOR_DEFAULTS["entry"], **configured_aggregators.get("entry", {})}

        direction_signal = direction_weights.get("base", 0.0)
        direction_signal += center(normalized.get("momentum_short", 0.5)) * direction_weights.get("short_momentum", 0.0)
        direction_signal += center(normalized.get("momentum_medium", 0.5)) * direction_weights.get("medium_momentum", 0.0)
        direction_signal += center(normalized.get("momentum_long", 0.5)) * direction_weights.get("long_momentum", 0.0)
        direction_signal += center(normalized.get("sentiment_score", 0.5)) * direction_weights.get("sentiment_bias", 0.0)
        direction_score = max(0.0, min(1.0, 0.5 + direction_signal))

        risk_signal = risk_weights.get("base", 0.0)
        risk_signal += center(normalized.get("atr_pct", 0.5)) * risk_weights.get("atr", 0.0)
        risk_signal += center(normalized.get("momentum_medium", 0.5)) * risk_weights.get("momentum", 0.0)
        risk_signal += normalized.get("sentiment_volatility", 0.5) * risk_weights.get("sentiment_volatility", 0.0)
        risk_offset_pct = max(-1.0, min(1.0, risk_signal))
        risk_stop_offset = risk_offset_pct * atr
        risk_take_profit_offset = risk_offset_pct * atr * 2 if atr else 0.0

        entry_signal = entry_weights.get("base", 0.0)
        entry_signal += center(normalized.get("momentum_short", 0.5)) * entry_weights.get("short_trend", 0.0)
        entry_signal += center(normalized.get("momentum_medium", 0.5)) * entry_weights.get("medium_trend", 0.0)
        entry_signal += center(normalized.get("momentum_long", 0.5)) * entry_weights.get("long_trend", 0.0)
        entry_signal += center(normalized.get("volatility_band_width", 0.5)) * entry_weights.get("volatility", 0.0)
        entry_adjustment = price + (entry_signal * atr if atr else 0.0)

        return {
            "direction_score": round(direction_score, 4),
            "risk_offset_pct": round(risk_offset_pct, 4),
            "risk_stop_offset": round(risk_stop_offset, 4),
            "risk_take_profit_offset": round(risk_take_profit_offset, 4),
            "entry_adjustment": round(entry_adjustment, 4),
            "entry_drift_signal": round(entry_signal, 4),
        }

