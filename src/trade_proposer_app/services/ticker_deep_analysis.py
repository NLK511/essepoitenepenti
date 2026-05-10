from __future__ import annotations

import json
from typing import Any

import math

import pandas as pd

from trade_proposer_app.domain.enums import RecommendationDirection, RecommendationState, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics, RunOutput
from trade_proposer_app.services.proposals import ProposalExecutionError, ProposalService, _sanitize_for_json
from trade_proposer_app.services.taxonomy import TickerTaxonomyService
from trade_proposer_app.services.ticker_analysis_payloads import TickerAnalysisPayloadService
from trade_proposer_app.services.ticker_technical_features import TickerTechnicalFeatureService


class TickerDeepAnalysisError(Exception):
    pass


class TickerDeepAnalysisService:
    def __init__(
        self,
        proposal_service: ProposalService,
        *,
        taxonomy_service: TickerTaxonomyService | None = None,
        model_name: str = "ticker_deep_analysis_v2",
    ) -> None:
        self.proposal_service = proposal_service
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.model_name = model_name
        self.technical_features = TickerTechnicalFeatureService()
        self.analysis_payloads = TickerAnalysisPayloadService(
            macro_context_score=self._macro_context_score,
            macro_context_label=self._macro_context_label,
            industry_context_score=self._industry_context_score,
            industry_context_label=self._industry_context_label,
            context_quality_status=self._context_quality_status,
        )
        self._reference_history_cache: dict[tuple[str, str | None], pd.DataFrame | None] = {}

    def analyze(self, ticker: str, *, horizon: StrategyHorizon | None = None, as_of: datetime | None = None) -> RunOutput:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise TickerDeepAnalysisError("ticker is required")
        if not self._supports_native_execution():
            return self._analyze_with_compatibility_fallback(normalized_ticker, horizon=horizon, as_of=as_of)
        try:
            history = self.proposal_service._fetch_price_history(normalized_ticker, as_of=as_of)
            enriched = self._enrich_history(history)
            context = self._build_context(enriched)
            context["price_history_diagnostics"] = dict(getattr(self.proposal_service, "_last_price_history_fetch_diagnostics", {}) or {})
            context = self._apply_context_enrichment(context, normalized_ticker, as_of=as_of)
            context = self._apply_support_aliases(context)
            context = self._apply_taxonomy_profile(context, normalized_ticker)
            context.update(self._build_reference_features(normalized_ticker, history, context.get("ticker_profile", {}), as_of=as_of))
            reference_notes = context.get("reference_features", {}).get("notes", []) if isinstance(context.get("reference_features"), dict) else []
            if isinstance(reference_notes, list) and reference_notes:
                context["problems"] = list(dict.fromkeys([*(context.get("problems", []) or []), *[str(note) for note in reference_notes if note]]))
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
            direction = self._resolve_direction(context, aggregations)
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
                technical_direction=context.get("technical_direction", context.get("direction", direction.value)),
                direction_score=float(aggregations.get("direction_score", 0.5) or 0.5),
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

    def _analyze_with_compatibility_fallback(self, ticker: str, *, horizon: StrategyHorizon | None, as_of: datetime | None = None) -> RunOutput:
        generate = getattr(self.proposal_service, "generate", None)
        if not callable(generate):
            raise TickerDeepAnalysisError("ticker deep analysis engine is missing native pipeline methods and generate() fallback")
        try:
            output = generate(ticker, as_of=as_of)
        except Exception as exc:  # noqa: BLE001
            raise TickerDeepAnalysisError(str(exc)) from exc
        diagnostics = output.diagnostics
        analysis_payload = self._load_json(diagnostics.analysis_json) or {"summary": {"text": diagnostics.raw_output or "compatibility fallback analysis"}}
        existing_ticker_deep_analysis = analysis_payload.get("ticker_deep_analysis") if isinstance(analysis_payload.get("ticker_deep_analysis"), dict) else {}
        analysis_payload["ticker_deep_analysis"] = {
            **existing_ticker_deep_analysis,
            "model": self.model_name,
            "execution_path": "compatibility_fallback",
            "horizon": horizon.value if horizon is not None else None,
            "setup_family": existing_ticker_deep_analysis.get("setup_family", "uncategorized"),
            "confidence_components": existing_ticker_deep_analysis.get("confidence_components", {}),
            "transmission_analysis": existing_ticker_deep_analysis.get("transmission_analysis", {}),
            "price_history": existing_ticker_deep_analysis.get("price_history", dict(getattr(self.proposal_service, "_last_price_history_fetch_diagnostics", {}) or {})),
        }
        analysis_json = json.dumps(_sanitize_for_json(analysis_payload), indent=2, sort_keys=True)
        diagnostics = diagnostics.model_copy(update={"analysis_json": analysis_json, "raw_output": analysis_json})
        return output.model_copy(update={"diagnostics": diagnostics})

    def _supports_native_execution(self) -> bool:
        return callable(getattr(self.proposal_service, "_fetch_price_history", None))

    def _apply_context_enrichment(self, context: dict[str, Any], ticker: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        apply_news_context = getattr(self.proposal_service, "_apply_news_context", None)
        if callable(apply_news_context):
            return apply_news_context(context, ticker, as_of=as_of)
        return context

    @staticmethod
    def _apply_support_aliases(context: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(context)
        enriched["macro_context_score"] = enriched.get("macro_sentiment_score", enriched.get("macro_context_score", 0.0))
        enriched["macro_context_label"] = enriched.get("macro_sentiment_label", enriched.get("macro_context_label", "NEUTRAL"))
        enriched["industry_context_score"] = enriched.get("industry_sentiment_score", enriched.get("industry_context_score", 0.0))
        enriched["industry_context_label"] = enriched.get("industry_sentiment_label", enriched.get("industry_context_label", "NEUTRAL"))
        return enriched

    def _apply_taxonomy_profile(self, context: dict[str, Any], ticker: str) -> dict[str, Any]:
        profile = context.get("ticker_profile") if isinstance(context.get("ticker_profile"), dict) else {}
        merged = {**self.taxonomy_service.get_ticker_profile(ticker), **profile}
        merged["relationship_edges"] = self.taxonomy_service.get_ticker_relationships(ticker)
        context["ticker_profile"] = merged
        return context

    def _build_reference_features(
        self,
        ticker: str,
        history: pd.DataFrame,
        profile: dict[str, Any],
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        features: dict[str, Any] = {
            "rel_return_5d_vs_spy": 0.0,
            "rel_return_20d_vs_spy": 0.0,
            "rel_return_5d_vs_sector": 0.0,
            "rel_return_20d_vs_sector": 0.0,
            "volume_ratio_20": self._volume_ratio(history, periods=20),
            "dollar_volume_ratio_20": self._dollar_volume_ratio(history, periods=20),
            "reference_features": {
                "benchmark_symbol": "SPY",
                "sector_etf_symbol": None,
                "benchmark_available": False,
                "sector_available": False,
                "notes": [],
            },
        }
        notes: list[str] = []

        benchmark_history = self._safe_fetch_reference_history("SPY", as_of=as_of, notes=notes)
        if benchmark_history is not None:
            features["rel_return_5d_vs_spy"] = self._relative_return(history, benchmark_history, periods=5)
            features["rel_return_20d_vs_spy"] = self._relative_return(history, benchmark_history, periods=20)
            features["reference_features"]["benchmark_available"] = True
        else:
            notes.append("reference feature fallback: SPY history unavailable")

        sector_etf = self._sector_etf_symbol(profile)
        features["reference_features"]["sector_etf_symbol"] = sector_etf
        if sector_etf:
            sector_history = self._safe_fetch_reference_history(sector_etf, as_of=as_of, notes=notes)
            if sector_history is not None:
                features["rel_return_5d_vs_sector"] = self._relative_return(history, sector_history, periods=5)
                features["rel_return_20d_vs_sector"] = self._relative_return(history, sector_history, periods=20)
                features["reference_features"]["sector_available"] = True
            else:
                notes.append(f"reference feature fallback: {sector_etf} history unavailable")
        else:
            notes.append("reference feature fallback: sector ETF mapping unavailable")

        features["reference_features"]["notes"] = list(dict.fromkeys(notes))
        return features

    def _safe_fetch_reference_history(
        self,
        symbol: str,
        *,
        as_of: datetime | None,
        notes: list[str],
    ) -> pd.DataFrame | None:
        cache_key = (symbol, as_of.isoformat() if as_of is not None else None)
        if cache_key in self._reference_history_cache:
            cached = self._reference_history_cache[cache_key]
            if cached is None:
                notes.append(f"reference feature cache hit: no usable history for {symbol}")
            return cached
        try:
            history = self.proposal_service._fetch_price_history(symbol, as_of=as_of)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"reference feature fetch failed for {symbol}: {exc}")
            self._reference_history_cache[cache_key] = None
            return None
        if not isinstance(history, pd.DataFrame) or history.empty or "Close" not in history.columns:
            notes.append(f"reference feature fetch returned no usable close history for {symbol}")
            self._reference_history_cache[cache_key] = None
            return None
        self._reference_history_cache[cache_key] = history
        return history

    @staticmethod
    def _sector_etf_symbol(profile: dict[str, Any]) -> str | None:
        raw_sector = str(profile.get("sector", "") or "").strip().lower()
        mapping = {
            "technology": "XLK",
            "information technology": "XLK",
            "financial services": "XLF",
            "financials": "XLF",
            "energy": "XLE",
            "healthcare": "XLV",
            "health care": "XLV",
            "industrials": "XLI",
            "consumer discretionary": "XLY",
            "consumer cyclical": "XLY",
            "consumer staples": "XLP",
            "utilities": "XLU",
            "materials": "XLB",
            "real estate": "XLRE",
            "communication services": "XLC",
            "communications": "XLC",
        }
        return mapping.get(raw_sector)

    @staticmethod
    def _period_return(history: pd.DataFrame, periods: int) -> float:
        if periods <= 0 or len(history.index) <= periods or "Close" not in history.columns:
            return 0.0
        closes = history["Close"].astype(float)
        end = float(closes.iloc[-1])
        start = float(closes.iloc[-(periods + 1)])
        if start == 0.0 or math.isnan(start) or math.isnan(end):
            return 0.0
        return (end / start) - 1.0

    @classmethod
    def _relative_return(cls, left: pd.DataFrame, right: pd.DataFrame, *, periods: int) -> float:
        return round(cls._period_return(left, periods) - cls._period_return(right, periods), 6)

    @staticmethod
    def _volume_ratio(history: pd.DataFrame, *, periods: int) -> float:
        if "Volume" not in history.columns or len(history.index) < periods:
            return 1.0
        volume = history["Volume"].astype(float)
        baseline = float(volume.tail(periods).mean())
        latest = float(volume.iloc[-1])
        if baseline <= 0.0:
            return 1.0
        return round(latest / baseline, 6)

    @staticmethod
    def _dollar_volume_ratio(history: pd.DataFrame, *, periods: int) -> float:
        if "Volume" not in history.columns or "Close" not in history.columns or len(history.index) < periods:
            return 1.0
        dollar_volume = history["Close"].astype(float) * history["Volume"].astype(float)
        baseline = float(dollar_volume.tail(periods).mean())
        latest = float(dollar_volume.iloc[-1])
        if baseline <= 0.0:
            return 1.0
        return round(latest / baseline, 6)

    def _enrich_history(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.technical_features.enrich_history(df)

    @staticmethod
    def _calculate_rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
        return TickerTechnicalFeatureService.calculate_rsi(df, window=window)

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        return TickerTechnicalFeatureService.calculate_atr(df, period=period)

    @staticmethod
    def _compute_ratio_series(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        return TickerTechnicalFeatureService.compute_ratio_series(numerator, denominator)

    def _build_context(self, df: pd.DataFrame) -> dict[str, Any]:
        return self.technical_features.build_context(df)

    @staticmethod
    def _compute_column_ranges(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
        return TickerTechnicalFeatureService.compute_column_ranges(df)

    def _build_feature_vector(self, context: dict[str, Any]) -> dict[str, float]:
        return self.technical_features.build_feature_vector(context)

    def _normalize_feature_vector(
        self,
        feature_vector: dict[str, float],
        column_ranges: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        return self.technical_features.normalize_feature_vector(feature_vector, column_ranges)

    @staticmethod
    def _normalize_value(value: float, bounds: tuple[float, float]) -> float:
        return TickerTechnicalFeatureService.normalize_value(value, bounds)

    def _compute_aggregations(self, normalized: dict[str, float], atr: float, price: float) -> dict[str, float]:
        return self.technical_features.compute_aggregations(
            normalized,
            atr,
            price,
            weights=getattr(self.proposal_service, "weights", {}) or {},
        )

    def _resolve_direction(self, context: dict[str, Any], aggregations: dict[str, float]) -> RecommendationDirection:
        direction_score = aggregations.get("direction_score")
        if isinstance(direction_score, (int, float)):
            if float(direction_score) > 0.5:
                return RecommendationDirection.LONG
            if float(direction_score) < 0.5:
                return RecommendationDirection.SHORT
        raw_direction = str(context.get("technical_direction", context.get("direction", "LONG")) or "LONG").strip().upper()
        if raw_direction == RecommendationDirection.SHORT.value:
            return RecommendationDirection.SHORT
        return RecommendationDirection.LONG

    def _build_confidence_components(
        self,
        context: dict[str, Any],
        direction: RecommendationDirection,
    ) -> dict[str, float]:
        directional_multiplier = 1.0 if direction == RecommendationDirection.LONG else -1.0
        relative_strength = self._aligned_relative_strength(context, direction)
        volume_confirmation = self._volume_confirmation_signal(context)
        context_confidence = self._scale_signed(
            (TickerDeepAnalysisService._macro_context_score(context) * 0.45)
            + (TickerDeepAnalysisService._industry_context_score(context) * 0.55),
            directional_multiplier=directional_multiplier,
        )
        directional_confidence = self._scale_signed(
            (float(context.get("ticker_sentiment_score", 0.0) or 0.0) * 0.55)
            + (float(context.get("momentum_medium", 0.0) or 0.0) * 1.2)
            + (relative_strength * 0.65),
            directional_multiplier=directional_multiplier,
        )
        catalyst_confidence = self._scale_unsigned(
            min(1.0, (float(context.get("news_item_count", 0.0) or 0.0) / 5.0)) * 0.7
            + min(1.0, (float(context.get("context_count", 0.0) or 0.0) / 3.0)) * 0.3
        )
        technical_clarity = self._scale_unsigned(
            (float(context.get("price_above_sma50", 0.0) or 0.0) * 0.22)
            + (float(context.get("price_above_sma200", 0.0) or 0.0) * 0.31)
            + max(0.0, 1.0 - abs((float(context.get("rsi", 50.0) or 50.0) - 55.0) / 55.0)) * 0.35
            + min(1.0, max(0.0, relative_strength) / 0.06) * 0.06
            + volume_confirmation * 0.06
        )
        execution_clarity = self._scale_unsigned(
            max(0.0, 1.0 - min(1.0, (float(context.get("atr_pct", 0.0) or 0.0) / 8.0))) * 0.5
            + min(1.0, abs(float(context.get("momentum_short", 0.0) or 0.0)) * 8.0) * 0.38
            + volume_confirmation * 0.12
        )
        context_quality_multiplier = self._context_quality_multiplier(context)
        data_quality_cap = self._scale_unsigned(
            (1.0
            - min(0.7, (len(context.get("problems", []) or []) * 0.12) + (len(context.get("news_feed_errors", []) or []) * 0.1)))
            * context_quality_multiplier
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
    def _aligned_relative_strength(context: dict[str, Any], direction: RecommendationDirection) -> float:
        values = [
            float(context.get("rel_return_5d_vs_spy", 0.0) or 0.0),
            float(context.get("rel_return_20d_vs_spy", 0.0) or 0.0),
            float(context.get("rel_return_5d_vs_sector", 0.0) or 0.0),
            float(context.get("rel_return_20d_vs_sector", 0.0) or 0.0),
        ]
        average = sum(values) / len(values)
        return average if direction == RecommendationDirection.LONG else -average

    @staticmethod
    def _volume_confirmation_signal(context: dict[str, Any]) -> float:
        volume_ratio = max(0.0, float(context.get("volume_ratio_20", 1.0) or 1.0))
        dollar_volume_ratio = max(0.0, float(context.get("dollar_volume_ratio_20", 1.0) or 1.0))
        average_ratio = (volume_ratio + dollar_volume_ratio) / 2.0
        if average_ratio <= 1.0:
            return 0.0
        return min(1.0, (average_ratio - 1.0) / 0.75)

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

    def _build_transmission_analysis(
        self,
        context: dict[str, Any],
        direction: RecommendationDirection,
    ) -> dict[str, Any]:
        macro_score = TickerDeepAnalysisService._macro_context_score(context)
        industry_score = TickerDeepAnalysisService._industry_context_score(context)
        ticker_score = float(context.get("ticker_sentiment_score", 0.0) or 0.0)
        profile = context.get("ticker_profile") if isinstance(context.get("ticker_profile"), dict) else {}
        macro_events = TickerDeepAnalysisService._context_events(context.get("macro_context_events") or context.get("macro_context_active_themes"))
        industry_events = TickerDeepAnalysisService._context_events(context.get("industry_context_events") or context.get("industry_context_active_drivers"))
        directional_multiplier = 1.0 if direction == RecommendationDirection.LONG else -1.0
        score_alignment = ((macro_score * 0.35) + (industry_score * 0.4) + (ticker_score * 0.25)) * directional_multiplier
        base_alignment_percent = max(0.0, min(100.0, 50.0 + (score_alignment * 50.0)))
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
        macro_event_strength = TickerDeepAnalysisService._event_relevance_strength(
            macro_events,
            profile,
            keywords=TickerDeepAnalysisService._profile_macro_keywords(profile),
        )
        industry_event_strength = TickerDeepAnalysisService._event_relevance_strength(
            industry_events,
            profile,
            keywords=TickerDeepAnalysisService._profile_industry_keywords(profile),
        )
        contradiction_count = TickerDeepAnalysisService._context_contradiction_count(context, macro_events, industry_events)
        matched_ticker_relationships = TickerDeepAnalysisService._matched_ticker_relationships(context, profile, macro_events, industry_events)
        freshness_bonus = TickerDeepAnalysisService._freshness_bonus(macro_events, industry_events)
        contradiction_penalty = min(12.0, contradiction_count * 4.0)
        alignment_percent = max(
            0.0,
            min(
                100.0,
                base_alignment_percent
                + ((macro_event_strength * 0.4) + (industry_event_strength * 0.6)) * (0.1 if base_alignment_percent >= 50.0 else -0.1)
                + freshness_bonus
                - contradiction_penalty,
            ),
        )
        if alignment_percent >= 62.0:
            bias = "tailwind"
        elif alignment_percent <= 42.0:
            bias = "headwind"
        else:
            bias = "mixed"
        transmission_tags = self._transmission_tags(
            macro_score=macro_score,
            industry_score=industry_score,
            catalyst_intensity=catalyst_intensity,
        )
        primary_drivers = self._primary_transmission_drivers(
            macro_event_strength=macro_event_strength,
            industry_event_strength=industry_event_strength,
            macro_score=macro_score,
            industry_score=industry_score,
            ticker_score=ticker_score,
            catalyst_intensity=catalyst_intensity,
            bias=bias,
        )
        conflict_flags = self._transmission_conflict_flags(
            macro_score=macro_score,
            industry_score=industry_score,
            ticker_score=ticker_score,
            catalyst_intensity=catalyst_intensity,
            alignment_percent=alignment_percent,
            bias=bias,
            direction=direction,
            contradiction_count=contradiction_count,
            context=context,
        )
        decay_state = TickerDeepAnalysisService._decay_state(catalyst_intensity, context, macro_events=macro_events, industry_events=industry_events)
        industry_exposure_channels = self._industry_exposure_channels(macro_score, industry_score, macro_events, industry_events, profile)
        ticker_exposure_channels = self._ticker_exposure_channels(ticker_score, catalyst_intensity, profile, macro_events, industry_events)
        return {
            "macro_score": round(macro_score, 3),
            "industry_score": round(industry_score, 3),
            "ticker_score": round(ticker_score, 3),
            "base_alignment_percent": round(base_alignment_percent, 1),
            "alignment_percent": round(alignment_percent, 1),
            "context_bias": bias,
            "catalyst_intensity_percent": round(catalyst_intensity, 1),
            "context_strength_percent": round(max(0.0, min(100.0, (macro_event_strength * 45.0) + (industry_event_strength * 55.0))), 1),
            "context_event_relevance_percent": round(max(0.0, min(100.0, (macro_event_strength * 100.0 + industry_event_strength * 100.0) / 2.0)), 1),
            "contradiction_count": contradiction_count,
            "transmission_tags": transmission_tags,
            "transmission_tag_details": self._transmission_tag_details(transmission_tags),
            "primary_drivers": primary_drivers,
            "primary_driver_labels": [self._label_for_driver(driver) for driver in primary_drivers],
            "primary_driver_details": self._primary_driver_details(primary_drivers),
            "industry_exposure_channels": industry_exposure_channels,
            "industry_exposure_channel_details": self._channel_details(industry_exposure_channels),
            "ticker_exposure_channels": ticker_exposure_channels,
            "ticker_exposure_channel_details": self._channel_details(ticker_exposure_channels),
            "ticker_relationship_edges": profile.get("relationship_edges", []) if isinstance(profile.get("relationship_edges"), list) else [],
            "matched_ticker_relationships": matched_ticker_relationships,
            "expected_transmission_window": TickerDeepAnalysisService._expected_transmission_window(catalyst_intensity, macro_score, industry_score, macro_events, industry_events),
            "expected_transmission_window_detail": self.taxonomy_service.get_transmission_window_definition(
                TickerDeepAnalysisService._expected_transmission_window(catalyst_intensity, macro_score, industry_score, macro_events, industry_events)
            ),
            "context_quality_status": TickerDeepAnalysisService._context_quality_status(context),
            "macro_context_quality_status": context.get("macro_context_quality_status"),
            "industry_context_quality_status": context.get("industry_context_quality_status"),
            "macro_context_quality_score": context.get("macro_context_quality_score"),
            "industry_context_quality_score": context.get("industry_context_quality_score"),
            "conflict_flags": conflict_flags,
            "conflict_flag_details": self._conflict_flag_details(conflict_flags),
            "decay_state": decay_state,
            "macro_event_keys": [str(item.get("key", "")) for item in macro_events if str(item.get("key", "")).strip()][:5],
            "industry_event_keys": [str(item.get("key", "")) for item in industry_events if str(item.get("key", "")).strip()][:5],
        }

    @staticmethod
    def _context_events(raw: object) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def _profile_macro_keywords(profile: dict[str, Any]) -> list[str]:
        keywords = []
        for key in ("macro_sensitivity", "themes", "industry_keywords"):
            raw_values = profile.get(key)
            if isinstance(raw_values, list):
                for value in raw_values:
                    text = str(value).strip().lower()
                    if text:
                        keywords.append(text)
        return list(dict.fromkeys(keywords))

    @staticmethod
    def _profile_industry_keywords(profile: dict[str, Any]) -> list[str]:
        keywords = []
        for key in ("industry", "sector", "themes", "industry_keywords"):
            raw_values = profile.get(key)
            if isinstance(raw_values, list):
                for value in raw_values:
                    text = str(value).strip().lower()
                    if text:
                        keywords.append(text)
            else:
                text = str(raw_values or "").strip().lower()
                if text:
                    keywords.append(text)
        return list(dict.fromkeys(keywords))

    @staticmethod
    def _event_relevance_strength(
        events: list[dict[str, Any]],
        profile: dict[str, Any],
        *,
        keywords: list[str],
    ) -> float:
        if not events:
            return 0.0
        profile_text = " ".join(keywords)
        relevance_scores: list[float] = []
        for event in events[:5]:
            channels = event.get("transmission_channels", []) if isinstance(event.get("transmission_channels"), list) else []
            tags = event.get("regime_tags", []) if isinstance(event.get("regime_tags"), list) else []
            event_text = " ".join([str(event.get("key", "")), str(event.get("label", "")), *[str(item) for item in channels], *[str(item) for item in tags]]).lower()
            keyword_hits = sum(1 for keyword in keywords if keyword and keyword in event_text)
            channel_hits = sum(1 for channel in channels if isinstance(channel, str) and channel.lower() in profile_text)
            base = float(event.get("saliency_weight", 0.0) or 0.0)
            lifecycle = str(event.get("persistence_state", "new") or "new")
            lifecycle_multiplier = {"new": 1.0, "escalating": 1.1, "persistent": 0.95, "fading": 0.72}.get(lifecycle, 0.9)
            relevance = base * lifecycle_multiplier * (1.0 + min(0.6, (keyword_hits * 0.18) + (channel_hits * 0.22)))
            relevance_scores.append(relevance)
        if not relevance_scores:
            return 0.0
        return min(1.0, sum(relevance_scores) / max(1, len(relevance_scores)))

    @staticmethod
    def _context_contradiction_count(context: dict[str, Any], macro_events: list[dict[str, Any]], industry_events: list[dict[str, Any]]) -> int:
        count = 0
        count += sum(1 for event in macro_events if bool(event.get("contradiction_flag")))
        count += sum(1 for event in industry_events if bool(event.get("contradiction_flag")))
        raw_macro = context.get("macro_context_contradictory_event_labels")
        raw_industry = context.get("industry_context_contradictory_event_labels")
        if isinstance(raw_macro, list):
            count += len(raw_macro)
        if isinstance(raw_industry, list):
            count += len(raw_industry)
        return count

    @staticmethod
    def _freshness_bonus(macro_events: list[dict[str, Any]], industry_events: list[dict[str, Any]]) -> float:
        events = macro_events[:3] + industry_events[:3]
        bonus = 0.0
        for event in events:
            lifecycle = str(event.get("persistence_state", "new") or "new")
            recency = str(event.get("recency_bucket", "unknown") or "unknown")
            if lifecycle == "escalating":
                bonus += 3.5
            elif lifecycle == "new":
                bonus += 2.0
            if recency == "fresh":
                bonus += 2.0
            elif recency == "recent":
                bonus += 1.0
        return min(8.0, bonus)

    @staticmethod
    def _matched_ticker_relationships(
        context: dict[str, Any],
        profile: dict[str, Any],
        macro_events: list[dict[str, Any]],
        industry_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_edges = profile.get("relationship_edges") if isinstance(profile.get("relationship_edges"), list) else []
        if not raw_edges:
            return []
        active_channels = {
            str(channel).strip().lower()
            for event in macro_events + industry_events
            for channel in (event.get("transmission_channels") if isinstance(event.get("transmission_channels"), list) else [])
            if str(channel).strip()
        }
        ontology_relationships = (
            context.get("industry_context_metadata", {}).get("matched_ontology_relationships", [])
            if isinstance(context.get("industry_context_metadata"), dict)
            else []
        )
        ontology_channels = {
            str(item.get("channel", "")).strip().lower()
            for item in ontology_relationships
            if isinstance(item, dict) and str(item.get("channel", "")).strip()
        }
        evidence_text = " ".join(
            str(item.get("title", "") or "") + " " + str(item.get("summary", "") or "")
            for item in (context.get("news_items") if isinstance(context.get("news_items"), list) else [])
            if isinstance(item, dict)
        ).lower()
        matched: list[dict[str, Any]] = []
        for edge in raw_edges:
            if not isinstance(edge, dict):
                continue
            channel = str(edge.get("channel", "")).strip().lower()
            target = str(edge.get("target", "")).strip().lower()
            target_label = str(edge.get("target_label", "")).strip().lower()
            target_industry = str(edge.get("target_industry", "")).strip().lower()
            relevance = 0
            if channel and (channel in active_channels or channel in ontology_channels):
                relevance += 1
            if target and target in evidence_text:
                relevance += 1
            if target_label and target_label in evidence_text:
                relevance += 1
            if target_industry and target_industry in evidence_text:
                relevance += 1
            if relevance <= 0:
                continue
            matched.append(
                {
                    **edge,
                    "direction": str(edge.get("direction", "mixed")).strip() or "mixed",
                    "mechanism": str(edge.get("mechanism", channel or "")).strip() or channel or "unknown",
                    "confidence": str(edge.get("confidence", "medium")).strip() or "medium",
                    "provenance": str(edge.get("provenance", "curated")).strip() or "curated",
                    "relationship_score": float(edge.get("relationship_score", 0.0) or 0.0),
                    "relevance_hits": relevance,
                }
            )
        matched.sort(key=lambda item: (int(item.get("relevance_hits", 0)), float(item.get("relationship_score", 0.0))), reverse=True)
        return matched[:6]

    @staticmethod
    def _transmission_tags(
        *,
        macro_score: float,
        industry_score: float,
        catalyst_intensity: float,
    ) -> list[str]:
        tags: list[str] = []
        if abs(macro_score) >= 0.25:
            tags.append("macro_dominant")
        if abs(industry_score) >= 0.25:
            tags.append("industry_dominant")
        if catalyst_intensity >= 65.0:
            tags.append("catalyst_active")
        return list(dict.fromkeys(tags))

    @staticmethod
    def _primary_transmission_drivers(
        *,
        macro_event_strength: float,
        industry_event_strength: float,
        macro_score: float,
        industry_score: float,
        ticker_score: float,
        catalyst_intensity: float,
        bias: str,
    ) -> list[str]:
        candidates = [
            (("macro_context_headwind" if bias == "headwind" else "macro_context_support"), abs(macro_score)),
            (("industry_context_headwind" if bias == "headwind" else "industry_context_support"), abs(industry_score)),
            (("ticker_sentiment_conflict" if bias == "headwind" else "ticker_sentiment_confirmation"), abs(ticker_score)),
            ("fresh_catalyst_pressure", catalyst_intensity / 100.0),
            (("macro_event_cluster_headwind" if bias == "headwind" else "macro_event_cluster"), macro_event_strength),
            (("industry_event_cluster_headwind" if bias == "headwind" else "industry_event_cluster"), industry_event_strength),
        ]
        ranked = [key for key, score in sorted(candidates, key=lambda item: item[1], reverse=True) if score >= 0.12]
        return list(dict.fromkeys(ranked))[:3]

    def _industry_exposure_channels(
        self,
        macro_score: float,
        industry_score: float,
        macro_events: list[dict[str, Any]],
        industry_events: list[dict[str, Any]],
        profile: dict[str, Any],
    ) -> list[str]:
        channels: list[str] = []
        if abs(macro_score) >= 0.2:
            channels.append("macro_regime")
        if abs(industry_score) >= 0.2:
            channels.append("industry_demand")
        if abs(industry_score) >= 0.3:
            channels.append("industry_read_through")
        for event in macro_events[:3] + industry_events[:3]:
            raw_channels = event.get("transmission_channels")
            if isinstance(raw_channels, list):
                for channel in raw_channels:
                    if isinstance(channel, str) and channel.strip():
                        channels.append(channel.strip())
        industry_profile = profile.get("industry_profile") if isinstance(profile.get("industry_profile"), dict) else {}
        raw_industry_channels = industry_profile.get("transmission_channels") if isinstance(industry_profile.get("transmission_channels"), list) else []
        for channel in raw_industry_channels[:3]:
            if isinstance(channel, str) and channel.strip():
                channels.append(channel.strip())
        return self._canonical_channel_keys(channels)[:6]

    def _ticker_exposure_channels(
        self,
        ticker_score: float,
        catalyst_intensity: float,
        profile: dict[str, Any],
        macro_events: list[dict[str, Any]],
        industry_events: list[dict[str, Any]],
    ) -> list[str]:
        channels: list[str] = []
        if abs(ticker_score) >= 0.18:
            channels.append("ticker_sentiment")
        if catalyst_intensity >= 45.0:
            channels.append("news_catalyst")
        if catalyst_intensity >= 70.0:
            channels.append("event_follow_through")
        relationship_edges = profile.get("relationship_edges") if isinstance(profile.get("relationship_edges"), list) else []
        for edge in relationship_edges[:5]:
            if not isinstance(edge, dict):
                continue
            channel = str(edge.get("channel", "")).strip()
            if channel:
                channels.append(channel)
        if macro_events or industry_events:
            channels.append("context_linked")
        return self._canonical_channel_keys(channels)[:6]

    def _canonical_channel_keys(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            definition = self.taxonomy_service.get_transmission_channel_definition(str(value))
            key = str(definition.get("key", "")).strip() or str(value).strip().lower().replace(" ", "_")
            if key and key not in normalized:
                normalized.append(key)
        return normalized

    def _channel_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        for value in self._canonical_channel_keys(values):
            definition = self.taxonomy_service.get_transmission_channel_definition(value)
            key = str(definition.get("key", value)).strip() or value
            label = str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " ")
            details.append({"key": key, "label": label})
        return details

    def _transmission_tag_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        for value in values:
            definition = self.taxonomy_service.get_transmission_tag_definition(value)
            key = str(definition.get("key", value)).strip() or value
            label = str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " ")
            details.append({"key": key, "label": label})
        return details

    def _primary_driver_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        for value in values:
            definition = self.taxonomy_service.get_transmission_primary_driver_definition(value)
            key = str(definition.get("key", value)).strip() or value
            label = str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " ")
            details.append({"key": key, "label": label})
        return details

    def _conflict_flag_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        for value in values:
            definition = self.taxonomy_service.get_transmission_conflict_flag_definition(value)
            key = str(definition.get("key", value)).strip() or value
            label = str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " ")
            details.append({"key": key, "label": label})
        return details

    def _label_for_driver(self, value: str) -> str:
        definition = self.taxonomy_service.get_transmission_primary_driver_definition(value)
        return str(definition.get("label", str(value or "").strip().replace("_", " "))).strip() or str(value or "").strip().replace("_", " ")

    @staticmethod
    def _expected_transmission_window(
        catalyst_intensity: float,
        macro_score: float,
        industry_score: float,
        macro_events: list[dict[str, Any]],
        industry_events: list[dict[str, Any]],
    ) -> str:
        windows: list[str] = []
        for event in macro_events[:3] + industry_events[:3]:
            window = str(event.get("window_hint", "") or "").strip()
            if window:
                windows.append(window)
        for candidate in ("1d", "2d_5d", "1w_plus"):
            if candidate in windows:
                return candidate
        if catalyst_intensity >= 70.0:
            return "1d"
        if catalyst_intensity >= 45.0:
            return "2d_5d"
        if abs(macro_score) >= 0.3 or abs(industry_score) >= 0.3:
            return "1w_plus"
        return "unknown"

    @staticmethod
    def _decay_state(
        catalyst_intensity: float,
        context: dict[str, Any],
        *,
        macro_events: list[dict[str, Any]],
        industry_events: list[dict[str, Any]],
    ) -> str:
        for event in macro_events[:2] + industry_events[:2]:
            lifecycle = str(event.get("persistence_state", "") or "")
            recency = str(event.get("recency_bucket", "") or "")
            if lifecycle == "escalating" or recency == "fresh":
                return "fresh"
            if lifecycle in {"new", "persistent"} or recency == "recent":
                return "active"
            if lifecycle == "fading" or recency == "aging":
                return "fading"
        news_items = float(context.get("news_item_count", 0.0) or 0.0)
        if catalyst_intensity >= 75.0 and news_items >= 4.0:
            return "fresh"
        if catalyst_intensity >= 45.0:
            return "active"
        if news_items >= 1.0:
            return "fading"
        return "unknown"

    @staticmethod
    def _transmission_conflict_flags(
        *,
        macro_score: float,
        industry_score: float,
        ticker_score: float,
        catalyst_intensity: float,
        alignment_percent: float,
        bias: str,
        direction: RecommendationDirection,
        contradiction_count: int,
        context: dict[str, Any],
    ) -> list[str]:
        flags: list[str] = []
        context_sign = (macro_score + industry_score) / 2.0
        if bias == "headwind" and abs(ticker_score) >= 0.18:
            flags.append("technical_context_conflict")
        if macro_score * industry_score < -0.02:
            flags.append("macro_industry_conflict")
        if context_sign * ticker_score < -0.02:
            flags.append("industry_ticker_conflict")
        if catalyst_intensity >= 65.0 and 45.0 <= alignment_percent <= 60.0:
            flags.append("timing_conflict")
        if contradiction_count > 0:
            flags.append("context_contradiction")
        if direction == RecommendationDirection.SHORT and ticker_score > 0.2:
            flags.append("directional_conflict")
        if direction == RecommendationDirection.LONG and ticker_score < -0.2:
            flags.append("directional_conflict")
        quality_status = TickerDeepAnalysisService._context_quality_status(context)
        if quality_status == "blocked":
            flags.append("context_quality_blocked")
        elif quality_status == "degraded":
            flags.append("context_quality_degraded")
        if str(context.get("macro_context_status", "")) == "warning" or str(context.get("industry_context_status", "")) == "warning":
            flags.append("context_quality_conflict")
        return list(dict.fromkeys(flags))

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
        macro_score = TickerDeepAnalysisService._macro_context_score(context)
        industry_score = TickerDeepAnalysisService._industry_context_score(context)
        direction_score = float(aggregations.get("direction_score", 0.5) or 0.5)
        relative_strength = TickerDeepAnalysisService._aligned_relative_strength(context, direction)
        volume_confirmation = TickerDeepAnalysisService._volume_confirmation_signal(context)

        if news_count >= 4 and abs(float(context.get("ticker_sentiment_score", 0.0) or 0.0)) >= 0.2:
            return "catalyst_follow_through"
        if direction == RecommendationDirection.LONG and momentum_medium > 0.08 and direction_score >= 0.58:
            return "continuation"
        if direction == RecommendationDirection.SHORT and momentum_medium < -0.08 and direction_score <= 0.42:
            return "continuation"
        if direction == RecommendationDirection.LONG and momentum_medium > 0.05 and relative_strength >= 0.015 and volume_confirmation >= 0.1:
            return "continuation"
        if direction == RecommendationDirection.SHORT and momentum_medium < -0.05 and relative_strength >= 0.015 and volume_confirmation >= 0.1:
            return "continuation"
        if direction == RecommendationDirection.LONG and momentum_short > 0.04 and rsi >= 60:
            return "breakout"
        if direction == RecommendationDirection.SHORT and momentum_short < -0.04 and rsi <= 40:
            return "breakdown"
        if direction == RecommendationDirection.LONG and momentum_short > 0.03 and rsi >= 55 and relative_strength >= 0.015 and volume_confirmation >= 0.2:
            return "breakout"
        if direction == RecommendationDirection.SHORT and momentum_short < -0.03 and rsi <= 45 and relative_strength >= 0.015 and volume_confirmation >= 0.2:
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
    def _macro_context_score(context: dict[str, Any]) -> float:
        return float(context.get("macro_context_score", context.get("macro_sentiment_score", 0.0)) or 0.0)

    @staticmethod
    def _industry_context_score(context: dict[str, Any]) -> float:
        return float(context.get("industry_context_score", context.get("industry_sentiment_score", 0.0)) or 0.0)

    @staticmethod
    def _macro_context_label(context: dict[str, Any]) -> str:
        return str(context.get("macro_context_label", context.get("macro_sentiment_label", "NEUTRAL")) or "NEUTRAL")

    @staticmethod
    def _industry_context_label(context: dict[str, Any]) -> str:
        return str(context.get("industry_context_label", context.get("industry_sentiment_label", "NEUTRAL")) or "NEUTRAL")

    @staticmethod
    def _context_quality_status(context: dict[str, Any]) -> str:
        statuses = [
            str(context.get("macro_context_quality_status", "")).strip().lower(),
            str(context.get("industry_context_quality_status", "")).strip().lower(),
        ]
        if "blocked" in statuses:
            return "blocked"
        if "degraded" in statuses:
            return "degraded"
        if "usable" in statuses:
            return "usable"
        return "unknown"

    @staticmethod
    def _context_quality_multiplier(context: dict[str, Any]) -> float:
        multiplier = 1.0
        for status in (
            str(context.get("macro_context_quality_status", "")).strip().lower(),
            str(context.get("industry_context_quality_status", "")).strip().lower(),
        ):
            if status == "blocked":
                multiplier *= 0.65
            elif status == "degraded":
                multiplier *= 0.9
        return multiplier

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
        technical_direction: str,
        direction_score: float,
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
        return self.analysis_payloads.build_analysis_payload(
            ticker=ticker,
            direction=direction,
            technical_direction=technical_direction,
            direction_score=direction_score,
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
            model_name=self.model_name,
        )

    def _build_diagnostics(
        self,
        analysis_json: str,
        feature_vector: dict[str, float],
        normalized_vector: dict[str, float],
        aggregations: dict[str, float],
        context: dict[str, Any],
    ) -> RunDiagnostics:
        return self.analysis_payloads.build_diagnostics(
            analysis_json,
            feature_vector,
            normalized_vector,
            aggregations,
            context,
            weights=getattr(self.proposal_service, "weights", {}) or {},
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
