from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import pandas as pd

from trade_proposer_app.domain.enums import RecommendationDirection, RecommendationState, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics, RunOutput
from trade_proposer_app.services.proposals import (
    AGGREGATOR_DEFAULTS,
    DEFAULT_SUMMARY_METHOD,
    DEFAULT_SUMMARY_TEXT,
    FEATURE_COLUMN_MAP,
    MANUAL_FEATURE_RANGES,
    RANGE_COLUMNS,
    ProposalExecutionError,
    ProposalService,
    _sanitize_for_json,
)


class TickerDeepAnalysisError(Exception):
    pass


class TickerDeepAnalysisService:
    def __init__(
        self,
        proposal_service: ProposalService,
        *,
        model_name: str = "ticker_deep_analysis_v2",
    ) -> None:
        self.proposal_service = proposal_service
        self.model_name = model_name

    def analyze(self, ticker: str, *, horizon: StrategyHorizon | None = None) -> RunOutput:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise TickerDeepAnalysisError("ticker is required")
        if not self._supports_native_execution():
            return self._analyze_with_compatibility_fallback(normalized_ticker, horizon=horizon)
        try:
            history = self.proposal_service._fetch_price_history(normalized_ticker)
            enriched = self._enrich_history(history)
            context = self._build_context(enriched)
            context = self._apply_context_enrichment(context, normalized_ticker)
            feature_vector = self._build_feature_vector(context)
            column_ranges = self._compute_column_ranges(enriched)
            normalized_vector = self._normalize_feature_vector(feature_vector, column_ranges)
            normalized_vector["normalized_atr_pct"] = normalized_vector.get("atr_pct", 0.5)
            feature_vector["normalized_atr_pct"] = normalized_vector["normalized_atr_pct"]
            aggregations = self._compute_aggregations(
                normalized_vector,
                float(context.get("atr", 0.0) or 0.0),
                float(context.get("price", 0.0) or 0.0),
            )
            direction = self._direction_from_context(context)
            confidence_components = self._build_confidence_components(context, direction)
            confidence = self._compose_confidence(confidence_components)
            entry_price, stop_loss, take_profit = self._suggest_price_levels(
                direction,
                float(context.get("price", 0.0) or 0.0),
                float(context.get("atr", 0.0) or 0.0),
                aggregations,
            )
            setup_family = self._classify_setup(context, aggregations, direction)
            transmission_analysis = self._build_transmission_analysis(context, direction)
            analysis = self._build_analysis_payload(
                ticker=normalized_ticker,
                direction=direction.value,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                context=context,
                feature_vector=feature_vector,
                normalized_vector=normalized_vector,
                aggregations=aggregations,
                setup_family=setup_family,
                confidence_components=confidence_components,
                transmission_analysis=transmission_analysis,
                horizon=horizon,
            )
            analysis_json = json.dumps(_sanitize_for_json(analysis), indent=2, sort_keys=True)
            diagnostics = self._build_diagnostics(analysis_json, feature_vector, normalized_vector, aggregations, context)
            recommendation = Recommendation(
                ticker=normalized_ticker,
                direction=direction,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                indicator_summary=self._build_indicator_summary(context, setup_family),
                state=RecommendationState.PENDING,
            )
            return RunOutput(recommendation=recommendation, diagnostics=diagnostics)
        except ProposalExecutionError as exc:
            raise TickerDeepAnalysisError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise TickerDeepAnalysisError(str(exc)) from exc

    def _analyze_with_compatibility_fallback(self, ticker: str, *, horizon: StrategyHorizon | None) -> RunOutput:
        generate = getattr(self.proposal_service, "generate", None)
        if not callable(generate):
            raise TickerDeepAnalysisError("ticker deep analysis engine is missing native pipeline methods and generate() fallback")
        try:
            output = generate(ticker)
        except Exception as exc:  # noqa: BLE001
            raise TickerDeepAnalysisError(str(exc)) from exc
        diagnostics = output.diagnostics
        analysis_payload = self._load_json(diagnostics.analysis_json) or {"summary": {"text": diagnostics.raw_output or "compatibility fallback analysis"}}
        analysis_payload["ticker_deep_analysis"] = {
            "model": self.model_name,
            "execution_path": "compatibility_fallback",
            "horizon": horizon.value if horizon is not None else None,
            "setup_family": "uncategorized",
            "confidence_components": {},
            "transmission_analysis": {},
        }
        analysis_json = json.dumps(_sanitize_for_json(analysis_payload), indent=2, sort_keys=True)
        diagnostics = diagnostics.model_copy(update={"analysis_json": analysis_json, "raw_output": analysis_json})
        return output.model_copy(update={"diagnostics": diagnostics})

    def _supports_native_execution(self) -> bool:
        return callable(getattr(self.proposal_service, "_fetch_price_history", None))

    def _apply_context_enrichment(self, context: dict[str, Any], ticker: str) -> dict[str, Any]:
        apply_news_context = getattr(self.proposal_service, "_apply_news_context", None)
        if callable(apply_news_context):
            return apply_news_context(context, ticker)
        return context

    def _enrich_history(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["SMA_20"] = enriched["Close"].rolling(window=20).mean()
        enriched["SMA_50"] = enriched["Close"].rolling(window=50).mean()
        enriched["SMA_200"] = enriched["Close"].rolling(window=200).mean()
        enriched["RSI_14"] = self._calculate_rsi(enriched)
        enriched["ATR_14"] = self._calculate_atr(enriched)
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
        enriched["price_vs_sma20_ratio"] = self._compute_ratio_series(enriched["Close"], enriched["SMA_20"])
        enriched["price_vs_sma50_ratio"] = self._compute_ratio_series(enriched["Close"], enriched["SMA_50"])
        enriched["price_vs_sma200_ratio"] = self._compute_ratio_series(enriched["Close"], enriched["SMA_200"])
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
    def _calculate_rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).ewm(com=window - 1, min_periods=window).mean()
        loss = -delta.clip(upper=0).ewm(com=window - 1, min_periods=window).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.ffill().fillna(50.0)

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(window=period).mean().ffill().fillna(0.0)

    @staticmethod
    def _compute_ratio_series(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        safe_den = denominator.replace(0, pd.NA)
        ratio = numerator.divide(safe_den)
        ratio = ratio.replace([float("inf"), float("-inf")], pd.NA)
        return (ratio - 1).fillna(0.0)

    def _build_context(self, df: pd.DataFrame) -> dict[str, Any]:
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
            "macro_item_count": 0,
            "macro_coverage_insights": [],
            "industry_sentiment_score": 0.0,
            "industry_sentiment_label": "NEUTRAL",
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
    def _compute_column_ranges(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
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

    def _build_feature_vector(self, context: dict[str, Any]) -> dict[str, float]:
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

    def _normalize_feature_vector(
        self,
        feature_vector: dict[str, float],
        column_ranges: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, raw_value in feature_vector.items():
            column = FEATURE_COLUMN_MAP.get(key)
            bounds = column_ranges.get(column, MANUAL_FEATURE_RANGES.get(key, (0.0, 1.0))) if column else MANUAL_FEATURE_RANGES.get(key, (0.0, 1.0))
            normalized[key] = self._normalize_value(raw_value, bounds)
        return normalized

    @staticmethod
    def _normalize_value(value: float, bounds: tuple[float, float]) -> float:
        min_val, max_val = bounds
        if max_val == min_val:
            return 0.5
        return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))

    def _compute_aggregations(self, normalized: dict[str, float], atr: float, price: float) -> dict[str, float]:
        def center(value: float) -> float:
            return value - 0.5

        configured = getattr(self.proposal_service, "weights", {}) or {}
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

    @staticmethod
    def _direction_from_context(context: dict[str, Any]) -> RecommendationDirection:
        raw_direction = str(context.get("direction", "LONG") or "LONG").strip().upper()
        if raw_direction == RecommendationDirection.SHORT.value:
            return RecommendationDirection.SHORT
        return RecommendationDirection.LONG

    def _build_confidence_components(
        self,
        context: dict[str, Any],
        direction: RecommendationDirection,
    ) -> dict[str, float]:
        directional_multiplier = 1.0 if direction == RecommendationDirection.LONG else -1.0
        context_confidence = self._scale_signed(
            (float(context.get("macro_sentiment_score", 0.0) or 0.0) * 0.45)
            + (float(context.get("industry_sentiment_score", 0.0) or 0.0) * 0.55),
            directional_multiplier=directional_multiplier,
        )
        directional_confidence = self._scale_signed(
            (float(context.get("ticker_sentiment_score", 0.0) or 0.0) * 0.65)
            + (float(context.get("momentum_medium", 0.0) or 0.0) * 1.4),
            directional_multiplier=directional_multiplier,
        )
        catalyst_confidence = self._scale_unsigned(
            min(1.0, (float(context.get("news_item_count", 0.0) or 0.0) / 5.0)) * 0.7
            + min(1.0, (float(context.get("context_count", 0.0) or 0.0) / 3.0)) * 0.3
        )
        technical_clarity = self._scale_unsigned(
            (float(context.get("price_above_sma50", 0.0) or 0.0) * 0.25)
            + (float(context.get("price_above_sma200", 0.0) or 0.0) * 0.35)
            + max(0.0, 1.0 - abs((float(context.get("rsi", 50.0) or 50.0) - 55.0) / 55.0)) * 0.4
        )
        execution_clarity = self._scale_unsigned(
            max(0.0, 1.0 - min(1.0, (float(context.get("atr_pct", 0.0) or 0.0) / 8.0))) * 0.55
            + min(1.0, abs(float(context.get("momentum_short", 0.0) or 0.0)) * 8.0) * 0.45
        )
        data_quality_cap = self._scale_unsigned(
            1.0
            - min(0.7, (len(context.get("problems", []) or []) * 0.12) + (len(context.get("news_feed_errors", []) or []) * 0.1))
        )
        return {
            "context_confidence": round(context_confidence, 2),
            "directional_confidence": round(directional_confidence, 2),
            "catalyst_confidence": round(catalyst_confidence, 2),
            "technical_clarity": round(technical_clarity, 2),
            "execution_clarity": round(execution_clarity, 2),
            "data_quality_cap": round(data_quality_cap, 2),
        }

    @staticmethod
    def _scale_signed(value: float, *, directional_multiplier: float) -> float:
        adjusted = value * directional_multiplier
        return max(0.0, min(100.0, 50.0 + (adjusted * 50.0)))

    @staticmethod
    def _scale_unsigned(value: float) -> float:
        return max(0.0, min(100.0, value * 100.0))

    @staticmethod
    def _compose_confidence(components: dict[str, float]) -> float:
        weighted = (
            components.get("context_confidence", 0.0) * 0.18
            + components.get("directional_confidence", 0.0) * 0.3
            + components.get("catalyst_confidence", 0.0) * 0.14
            + components.get("technical_clarity", 0.0) * 0.2
            + components.get("execution_clarity", 0.0) * 0.18
        )
        quality_cap = components.get("data_quality_cap", 100.0) / 100.0
        return round(max(0.0, min(95.0, weighted * quality_cap)), 2)

    @staticmethod
    def _build_transmission_analysis(
        context: dict[str, Any],
        direction: RecommendationDirection,
    ) -> dict[str, Any]:
        macro_score = float(context.get("macro_sentiment_score", 0.0) or 0.0)
        industry_score = float(context.get("industry_sentiment_score", 0.0) or 0.0)
        ticker_score = float(context.get("ticker_sentiment_score", 0.0) or 0.0)
        directional_multiplier = 1.0 if direction == RecommendationDirection.LONG else -1.0
        signed_alignment = ((macro_score * 0.35) + (industry_score * 0.4) + (ticker_score * 0.25)) * directional_multiplier
        alignment_percent = max(0.0, min(100.0, 50.0 + (signed_alignment * 50.0)))
        catalyst_intensity = max(
            0.0,
            min(
                100.0,
                (
                    min(1.0, float(context.get("news_item_count", 0.0) or 0.0) / 5.0) * 65.0
                    + min(1.0, float(context.get("context_count", 0.0) or 0.0) / 3.0) * 35.0
                ),
            ),
        )
        if alignment_percent >= 62.0:
            bias = "tailwind"
        elif alignment_percent <= 42.0:
            bias = "headwind"
        else:
            bias = "mixed"
        tags: list[str] = []
        if abs(macro_score) >= 0.25:
            tags.append("macro_dominant")
        if abs(industry_score) >= 0.25:
            tags.append("industry_dominant")
        if catalyst_intensity >= 65.0:
            tags.append("catalyst_active")
        return {
            "macro_score": round(macro_score, 3),
            "industry_score": round(industry_score, 3),
            "ticker_score": round(ticker_score, 3),
            "alignment_percent": round(alignment_percent, 1),
            "context_bias": bias,
            "catalyst_intensity_percent": round(catalyst_intensity, 1),
            "transmission_tags": tags,
        }

    @staticmethod
    def _classify_setup(
        context: dict[str, Any],
        aggregations: dict[str, float],
        direction: RecommendationDirection,
    ) -> str:
        momentum_medium = float(context.get("momentum_medium", 0.0) or 0.0)
        momentum_short = float(context.get("momentum_short", 0.0) or 0.0)
        rsi = float(context.get("rsi", 50.0) or 50.0)
        news_count = int(context.get("news_item_count", 0) or 0)
        macro_score = float(context.get("macro_sentiment_score", 0.0) or 0.0)
        industry_score = float(context.get("industry_sentiment_score", 0.0) or 0.0)
        direction_score = float(aggregations.get("direction_score", 0.5) or 0.5)

        if news_count >= 4 and abs(float(context.get("ticker_sentiment_score", 0.0) or 0.0)) >= 0.2:
            return "catalyst_follow_through"
        if direction == RecommendationDirection.LONG and momentum_medium > 0.08 and direction_score >= 0.58:
            return "continuation"
        if direction == RecommendationDirection.SHORT and momentum_medium < -0.08 and direction_score <= 0.42:
            return "continuation"
        if direction == RecommendationDirection.LONG and momentum_short > 0.04 and rsi >= 60:
            return "breakout"
        if direction == RecommendationDirection.SHORT and momentum_short < -0.04 and rsi <= 40:
            return "breakdown"
        if direction == RecommendationDirection.LONG and rsi < 40:
            return "mean_reversion"
        if direction == RecommendationDirection.SHORT and rsi > 60:
            return "mean_reversion"
        if abs(macro_score) >= 0.25 or abs(industry_score) >= 0.25:
            return "macro_beneficiary_loser"
        return "uncategorized"

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _build_indicator_summary(context: dict[str, Any], setup_family: str) -> str:
        parts = [f"setup {setup_family.replace('_', ' ')}"]
        sentiment_label = context.get("ticker_sentiment_label") or context.get("sentiment_label")
        if sentiment_label:
            parts.append(f"ticker sentiment {sentiment_label}")
        rsi = context.get("rsi")
        if isinstance(rsi, (int, float)):
            parts.append(f"RSI {float(rsi):.1f}")
        if context.get("price_above_sma200"):
            parts.append("above SMA200")
        else:
            parts.append("below SMA200")
        return " · ".join(parts[:4])

    def _build_analysis_payload(
        self,
        *,
        ticker: str,
        direction: str,
        confidence: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        context: dict[str, Any],
        feature_vector: dict[str, float],
        normalized_vector: dict[str, float],
        aggregations: dict[str, float],
        setup_family: str,
        confidence_components: dict[str, float],
        transmission_analysis: dict[str, Any],
        horizon: StrategyHorizon | None,
    ) -> dict[str, Any]:
        return {
            "summary": {
                "text": context.get("summary_text", DEFAULT_SUMMARY_TEXT),
                "method": context.get("summary_method", DEFAULT_SUMMARY_METHOD),
                "backend": context.get("summary_backend"),
                "model": context.get("summary_model"),
                "runtime_seconds": context.get("summary_runtime_seconds"),
                "metadata": context.get("summary_metadata", {}),
                "digest": context.get("news_digest", ""),
                "error": context.get("summary_error"),
                "llm_error": context.get("llm_error"),
            },
            "news": {
                "item_count": context.get("news_item_count", 0),
                "context_count": context.get("context_count", 0),
                "point_count": context.get("news_point_count", 0),
                "feeds_used": context.get("news_feeds_used", []),
                "feed_errors": context.get("news_feed_errors", []),
                "items": context.get("news_items", []),
            },
            "sentiment": {
                "score": context.get("sentiment_score", 0.0),
                "label": context.get("sentiment_label"),
                "macro": {
                    "score": context.get("macro_sentiment_score", 0.0),
                    "label": context.get("macro_sentiment_label", "NEUTRAL"),
                    "coverage_insights": context.get("macro_coverage_insights", []),
                },
                "industry": {
                    "score": context.get("industry_sentiment_score", 0.0),
                    "label": context.get("industry_sentiment_label", "NEUTRAL"),
                    "coverage_insights": context.get("industry_coverage_insights", []),
                },
                "ticker": {
                    "score": context.get("ticker_sentiment_score", context.get("sentiment_score", 0.0)),
                    "label": context.get("ticker_sentiment_label", context.get("sentiment_label")),
                },
            },
            "proposal": {
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            },
            "technical": {
                "price": context.get("price", 0.0),
                "sma20": context.get("sma20"),
                "sma50": context.get("sma50"),
                "sma200": context.get("sma200"),
                "rsi": context.get("rsi"),
                "atr": context.get("atr"),
                "atr_pct": context.get("atr_pct"),
                "price_above_sma50": context.get("price_above_sma50"),
                "price_above_sma200": context.get("price_above_sma200"),
                "momentum_short": context.get("momentum_short"),
                "momentum_medium": context.get("momentum_medium"),
                "momentum_long": context.get("momentum_long"),
            },
            "feature_vector": feature_vector,
            "normalized_feature_vector": normalized_vector,
            "aggregations": aggregations,
            "ticker_deep_analysis": {
                "model": self.model_name,
                "execution_path": "native",
                "horizon": horizon.value if horizon is not None else None,
                "setup_family": setup_family,
                "confidence_components": confidence_components,
                "transmission_analysis": transmission_analysis,
            },
        }

    def _build_diagnostics(
        self,
        analysis_json: str,
        feature_vector: dict[str, float],
        normalized_vector: dict[str, float],
        aggregations: dict[str, float],
        context: dict[str, Any],
    ) -> RunDiagnostics:
        configured = getattr(self.proposal_service, "weights", {}) or {}
        confidence_weights = configured.get("confidence", {}) if isinstance(configured, dict) else {}
        return RunDiagnostics(
            warnings=list(dict.fromkeys(context.get("problems", []))),
            provider_errors=[],
            problems=context.get("problems", []),
            news_feed_errors=context.get("news_feed_errors", []),
            summary_error=context.get("summary_error"),
            llm_error=context.get("llm_error"),
            raw_output=analysis_json,
            analysis_json=analysis_json,
            feature_vector_json=json.dumps(_sanitize_for_json(feature_vector), indent=2, sort_keys=True),
            normalized_feature_vector_json=json.dumps(_sanitize_for_json(normalized_vector), indent=2, sort_keys=True),
            aggregations_json=json.dumps(_sanitize_for_json(aggregations), indent=2, sort_keys=True),
            confidence_weights_json=json.dumps(_sanitize_for_json(confidence_weights), indent=2, sort_keys=True),
            summary_method=str(context.get("summary_method", DEFAULT_SUMMARY_METHOD)),
        )

    def _suggest_price_levels(
        self,
        direction: RecommendationDirection,
        price: float,
        atr: float,
        aggregations: dict[str, float],
    ) -> tuple[float, float, float]:
        risk_stop_offset = float(aggregations.get("risk_stop_offset", 0.0) or 0.0)
        risk_take_profit_offset = float(aggregations.get("risk_take_profit_offset", 0.0) or 0.0)
        entry_adjustment = float(aggregations.get("entry_adjustment", price) or price)

        stop_distance = self._compute_stop_distance(price, atr, risk_stop_offset)
        take_profit_distance = self._compute_take_profit_distance(price, stop_distance, risk_take_profit_offset)

        entry_value = round(entry_adjustment, 4)
        if direction == RecommendationDirection.LONG:
            return (
                entry_value,
                round(entry_value - stop_distance, 4),
                round(entry_value + take_profit_distance, 4),
            )
        return (
            entry_value,
            round(entry_value + stop_distance, 4),
            round(entry_value - take_profit_distance, 4),
        )

    @staticmethod
    def _compute_stop_distance(price: float, atr: float, risk_offset: float) -> float:
        base_stop_distance = atr if atr > 0 else max(price * 0.008, 0.01)
        adjusted_distance = base_stop_distance + risk_offset
        min_distance = max(price * 0.005, base_stop_distance * 0.5, 0.01)
        max_distance = max(price * 0.03, min_distance)
        return min(max_distance, max(min_distance, adjusted_distance))

    @staticmethod
    def _compute_take_profit_distance(price: float, stop_distance: float, risk_offset: float) -> float:
        raw_distance = stop_distance * 1.5 + (risk_offset * 0.5)
        min_distance = max(stop_distance * 1.1, price * 0.0075, 0.01)
        max_distance = max(price * 0.045, min_distance)
        return min(max_distance, max(min_distance, raw_distance))
