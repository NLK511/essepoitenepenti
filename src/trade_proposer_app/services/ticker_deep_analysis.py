from __future__ import annotations

import json
from typing import Any

from trade_proposer_app.domain.enums import RecommendationDirection, RecommendationState, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RunOutput
from trade_proposer_app.services.proposals import ProposalExecutionError, ProposalService, _sanitize_for_json


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
            enriched = self.proposal_service._enrich_history(history)
            context = self.proposal_service._build_context(enriched)
            context = self.proposal_service._apply_news_context(context, normalized_ticker)
            feature_vector = self.proposal_service._build_feature_vector(context)
            column_ranges = self.proposal_service._compute_column_ranges(enriched)
            normalized_vector = self.proposal_service._normalize_feature_vector(feature_vector, column_ranges)
            normalized_vector["normalized_atr_pct"] = normalized_vector.get("atr_pct", 0.5)
            feature_vector["normalized_atr_pct"] = normalized_vector["normalized_atr_pct"]
            aggregations = self.proposal_service._compute_aggregations(
                normalized_vector,
                float(context.get("atr", 0.0) or 0.0),
                float(context.get("price", 0.0) or 0.0),
            )
            direction = self._direction_from_context(context)
            confidence_components = self._build_confidence_components(context, direction)
            confidence = self._compose_confidence(confidence_components)
            entry_price, stop_loss, take_profit = self.proposal_service._suggest_price_levels(
                direction,
                float(context.get("price", 0.0) or 0.0),
                float(context.get("atr", 0.0) or 0.0),
                aggregations,
            )
            setup_family = self._classify_setup(context, aggregations, direction)
            transmission_analysis = self._build_transmission_analysis(context, direction)
            analysis = self.proposal_service._build_analysis_payload(
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
            )
            analysis["ticker_deep_analysis"] = {
                "model": self.model_name,
                "execution_path": "native",
                "horizon": horizon.value if horizon is not None else None,
                "setup_family": setup_family,
                "confidence_components": confidence_components,
                "transmission_analysis": transmission_analysis,
            }
            analysis_json = json.dumps(_sanitize_for_json(analysis), indent=2, sort_keys=True)
            diagnostics = self.proposal_service._build_diagnostics(
                analysis_json,
                feature_vector,
                normalized_vector,
                aggregations,
                context,
            )
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
        required = (
            "_fetch_price_history",
            "_enrich_history",
            "_build_context",
            "_apply_news_context",
            "_build_feature_vector",
            "_compute_column_ranges",
            "_normalize_feature_vector",
            "_compute_aggregations",
            "_suggest_price_levels",
            "_build_analysis_payload",
            "_build_diagnostics",
        )
        return all(callable(getattr(self.proposal_service, name, None)) for name in required)

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
