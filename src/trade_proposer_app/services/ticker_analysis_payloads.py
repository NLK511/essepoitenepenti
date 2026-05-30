from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RunDiagnostics
from trade_proposer_app.services.payload_utils import DEFAULT_SUMMARY_METHOD, DEFAULT_SUMMARY_TEXT, sanitize_for_json


class TickerAnalysisPayloadService:
    """Build ticker deep-analysis payloads and diagnostics without owning analysis execution."""

    def __init__(
        self,
        *,
        macro_context_score: Callable[[dict[str, Any]], float],
        macro_context_label: Callable[[dict[str, Any]], str],
        industry_context_score: Callable[[dict[str, Any]], float],
        industry_context_label: Callable[[dict[str, Any]], str],
        context_quality_status: Callable[[dict[str, Any]], str],
    ) -> None:
        self._macro_context_score = macro_context_score
        self._macro_context_label = macro_context_label
        self._industry_context_score = industry_context_score
        self._industry_context_label = industry_context_label
        self._context_quality_status = context_quality_status

    def build_analysis_payload(
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
        model_name: str,
    ) -> dict[str, Any]:
        return {
            "summary": self._summary_section(context),
            "news": self._news_section(context),
            "market_intelligence": context.get("market_intelligence", {}),
            "sentiment": self._sentiment_section(context),
            "proposal": self._proposal_section(
                ticker=ticker,
                direction=direction,
                technical_direction=technical_direction,
                direction_score=direction_score,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            ),
            "technical": self._technical_section(context),
            "feature_vector": feature_vector,
            "normalized_feature_vector": normalized_vector,
            "aggregations": aggregations,
            "ticker_deep_analysis": self._deep_analysis_section(
                context,
                model_name=model_name,
                horizon=horizon,
                setup_family=setup_family,
                confidence_components=confidence_components,
                transmission_analysis=transmission_analysis,
            ),
        }

    def _summary_section(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "text": context.get("summary_text", DEFAULT_SUMMARY_TEXT),
            "method": context.get("summary_method", DEFAULT_SUMMARY_METHOD),
            "backend": context.get("summary_backend"),
            "model": context.get("summary_model"),
            "runtime_seconds": context.get("summary_runtime_seconds"),
            "metadata": context.get("summary_metadata", {}),
            "digest": context.get("news_digest", ""),
            "error": context.get("summary_error"),
            "llm_error": context.get("llm_error"),
        }

    @staticmethod
    def _news_section(context: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_count": context.get("news_item_count", 0),
            "context_count": context.get("context_count", 0),
            "point_count": context.get("news_point_count", 0),
            "feeds_used": context.get("news_feeds_used", []),
            "feed_errors": context.get("news_feed_errors", []),
            "items": context.get("news_items", []),
        }

    def _sentiment_section(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": context.get("sentiment_score", 0.0),
            "label": context.get("sentiment_label"),
            "macro": {
                "score": self._macro_context_score(context),
                "label": self._macro_context_label(context),
                "coverage_insights": context.get("macro_coverage_insights", []),
                "context_quality_score": context.get("macro_context_quality_score"),
                "context_quality_status": context.get("macro_context_quality_status"),
                "context_quality_flags": context.get("macro_context_quality_flags", {}),
                "context_quality_notes": context.get("macro_context_quality_notes", []),
            },
            "industry": {
                "score": self._industry_context_score(context),
                "label": self._industry_context_label(context),
                "coverage_insights": context.get("industry_coverage_insights", []),
                "context_quality_score": context.get("industry_context_quality_score"),
                "context_quality_status": context.get("industry_context_quality_status"),
                "context_quality_flags": context.get("industry_context_quality_flags", {}),
                "context_quality_notes": context.get("industry_context_quality_notes", []),
            },
            "ticker": {
                "score": context.get("ticker_sentiment_score", context.get("sentiment_score", 0.0)),
                "label": context.get("ticker_sentiment_label", context.get("sentiment_label")),
            },
        }

    @staticmethod
    def _proposal_section(
        *,
        ticker: str,
        direction: str,
        technical_direction: str,
        direction_score: float,
        confidence: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "direction": direction,
            "technical_direction": technical_direction,
            "direction_score": direction_score,
            "confidence": confidence,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

    @staticmethod
    def _technical_section(context: dict[str, Any]) -> dict[str, Any]:
        return {
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
            "rel_return_5d_vs_spy": context.get("rel_return_5d_vs_spy"),
            "rel_return_20d_vs_spy": context.get("rel_return_20d_vs_spy"),
            "rel_return_5d_vs_sector": context.get("rel_return_5d_vs_sector"),
            "rel_return_20d_vs_sector": context.get("rel_return_20d_vs_sector"),
            "volume_ratio_20": context.get("volume_ratio_20"),
            "dollar_volume_ratio_20": context.get("dollar_volume_ratio_20"),
            "reference_features": context.get("reference_features", {}),
        }

    def _deep_analysis_section(
        self,
        context: dict[str, Any],
        *,
        model_name: str,
        horizon: StrategyHorizon | None,
        setup_family: str,
        confidence_components: dict[str, float],
        transmission_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "model": model_name,
            "execution_path": "native",
            "horizon": horizon.value if horizon is not None else None,
            "setup_family": setup_family,
            "confidence_components": confidence_components,
            "transmission_analysis": transmission_analysis,
            "market_intelligence": context.get("market_intelligence", {}),
            "market_intelligence_summary": context.get("market_intelligence_summary"),
            "context_quality": {
                "status": self._context_quality_status(context),
                "macro": {
                    "score": context.get("macro_context_quality_score"),
                    "status": context.get("macro_context_quality_status"),
                    "flags": context.get("macro_context_quality_flags", {}),
                    "notes": context.get("macro_context_quality_notes", []),
                },
                "industry": {
                    "score": context.get("industry_context_quality_score"),
                    "status": context.get("industry_context_quality_status"),
                    "flags": context.get("industry_context_quality_flags", {}),
                    "notes": context.get("industry_context_quality_notes", []),
                },
            },
            "price_history": context.get("price_history_diagnostics", {}),
        }

    def build_diagnostics(
        self,
        analysis_json: str,
        feature_vector: dict[str, float],
        normalized_vector: dict[str, float],
        aggregations: dict[str, float],
        context: dict[str, Any],
        *,
        weights: dict[str, object] | None,
    ) -> RunDiagnostics:
        configured = weights or {}
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
            feature_vector_json=json.dumps(sanitize_for_json(feature_vector), indent=2, sort_keys=True),
            normalized_feature_vector_json=json.dumps(sanitize_for_json(normalized_vector), indent=2, sort_keys=True),
            aggregations_json=json.dumps(sanitize_for_json(aggregations), indent=2, sort_keys=True),
            confidence_weights_json=json.dumps(sanitize_for_json(confidence_weights), indent=2, sort_keys=True),
            summary_method=str(context.get("summary_method", DEFAULT_SUMMARY_METHOD)),
        )
