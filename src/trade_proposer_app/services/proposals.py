from __future__ import annotations

import json
import math
import re
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd
import yfinance as yf

from trade_proposer_app.domain.enums import RecommendationDirection, RecommendationState
from trade_proposer_app.domain.models import HistoricalMarketBar, NewsArticle, Recommendation, RunDiagnostics, RunOutput, TechnicalSnapshot
from trade_proposer_app.services.constants import DEFAULT_CONTEXT_FLAGS
from trade_proposer_app.services.news import (
    NaiveSentimentAnalyzer,
    NEWS_SUMMARY_ARTICLE_LIMIT,
    NewsIngestionService,
    NEGATIVE_KEYWORD_WEIGHTS,
    POSITIVE_KEYWORD_WEIGHTS,
    SUMMARY_KEYWORD_WEIGHT,
    SUMMARY_METHOD_NEWS_DIGEST,
)
from trade_proposer_app.services.signals import SignalIngestionService
from trade_proposer_app.services.context_snapshot_resolver import ContextSnapshotResolver
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.summary import SummaryRequest, SummaryService
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository


FEATURE_COLUMN_MAP: dict[str, str] = {
    "price_close": "Close",
    "sma20": "SMA_20",
    "sma50": "SMA_50",
    "sma200": "SMA_200",
    "rsi": "RSI_14",
    "atr": "ATR_14",
    "atr_pct": "atr_pct",
    "momentum_short": "momentum_short",
    "momentum_medium": "momentum_medium",
    "momentum_long": "momentum_long",
    "price_change_1d": "price_change_1d",
    "price_change_10d": "price_change_10d",
    "price_change_63d": "price_change_63d",
    "price_change_126d": "price_change_126d",
    "price_vs_sma20_ratio": "price_vs_sma20_ratio",
    "price_vs_sma50_ratio": "price_vs_sma50_ratio",
    "price_vs_sma200_ratio": "price_vs_sma200_ratio",
    "price_vs_sma20_slope": "price_vs_sma20_slope",
    "price_vs_sma50_slope": "price_vs_sma50_slope",
    "price_vs_sma200_slope": "price_vs_sma200_slope",
    "volatility_band_upper": "volatility_band_upper",
    "volatility_band_lower": "volatility_band_lower",
    "volatility_band_width": "volatility_band_width",
    "entry_delta_2w": "entry_delta_2w",
    "entry_delta_3m": "entry_delta_3m",
    "entry_delta_12m": "entry_delta_12m",
}

RANGE_COLUMNS = [
    "Close",
    "SMA_20",
    "SMA_50",
    "SMA_200",
    "RSI_14",
    "ATR_14",
    "atr_pct",
    "momentum_short",
    "momentum_medium",
    "momentum_long",
    "price_change_1d",
    "price_change_10d",
    "price_change_63d",
    "price_change_126d",
    "price_vs_sma20_ratio",
    "price_vs_sma50_ratio",
    "price_vs_sma200_ratio",
    "price_vs_sma20_slope",
    "price_vs_sma50_slope",
    "price_vs_sma200_slope",
    "volatility_band_upper",
    "volatility_band_lower",
    "volatility_band_width",
    "entry_delta_2w",
    "entry_delta_3m",
    "entry_delta_12m",
]

MANUAL_FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "short_bullish": (0.0, 5.0),
    "short_bearish": (0.0, 5.0),
    "medium_bullish": (0.0, 5.0),
    "medium_bearish": (0.0, 5.0),
    "sentiment_score": (-1.0, 1.0),
    "enhanced_sentiment_score": (-1.0, 1.0),
    "news_sentiment_score": (-1.0, 1.0),
    "social_sentiment_score": (-1.0, 1.0),
    "macro_sentiment_score": (-1.0, 1.0),
    "industry_sentiment_score": (-1.0, 1.0),
    "ticker_sentiment_score": (-1.0, 1.0),
    "social_item_count": (0.0, 50.0),
    "macro_item_count": (0.0, 50.0),
    "industry_item_count": (0.0, 50.0),
    "ticker_item_count": (0.0, 50.0),
    "source_count": (0.0, 30.0),
    "context_count": (0.0, 5.0),
    "context_tag_earnings": (0.0, 1.0),
    "context_tag_geopolitical": (0.0, 1.0),
    "context_tag_industry": (0.0, 1.0),
    "context_tag_general": (0.0, 1.0),
    "news_point_count": (0.0, 50.0),
    "polarity_trend": (-1.0, 1.0),
    "sentiment_volatility": (0.0, 1.0),
    "normalized_atr_pct": (0.0, 1.0),
}

NEWS_COVERAGE_SCALE = 5.0
CONTEXT_COVERAGE_SCALE = 3.0

AGGREGATOR_DEFAULTS = {
    "direction": {
        "short_momentum": 0.2,
        "medium_momentum": 0.3,
        "long_momentum": 0.15,
        "sentiment_bias": 0.8,
        "base": 0.0,
    },
    "risk": {
        "atr": 0.2,
        "momentum": 0.3,
        "sentiment_volatility": -0.5,
        "base": 0.0,
    },
    "entry": {
        "short_trend": 0.15,
        "medium_trend": 0.25,
        "long_trend": 0.1,
        "volatility": -0.2,
        "base": 0.0,
    },
}

DEFAULT_SUMMARY_METHOD = "price_only"
DEFAULT_SUMMARY_TEXT = "Price-based signal only (news feeds not configured)."

WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "weights.json"


class ProposalExecutionError(Exception):
    pass


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    return value


class ProposalService:
    LIVE_REMOTE_FETCH_ATTEMPTS = 3
    LIVE_REMOTE_FETCH_BACKOFF_SECONDS = (0.0, 1.0, 3.0)

    def __init__(
        self,
        weights_path: Path | None = None,
        *,
        news_service: NewsIngestionService | None = None,
        social_service: SocialIngestionService | None = None,
        signal_service: SignalIngestionService | None = None,
        snapshot_resolver: ContextSnapshotResolver | None = None,
        sentiment_analyzer: NaiveSentimentAnalyzer | None = None,
        summary_service: SummaryService | None = None,
        historical_market_data: HistoricalMarketDataRepository | None = None,
    ) -> None:
        self.weights_path = weights_path or WEIGHTS_PATH
        self.weights = self._load_weights()
        self.news_service = news_service
        self.social_service = social_service
        self.signal_service = signal_service
        self.snapshot_resolver = snapshot_resolver
        self.sentiment_analyzer = sentiment_analyzer or NaiveSentimentAnalyzer()
        self.summary_service = summary_service or SummaryService()
        self.historical_market_data = historical_market_data
        self._last_price_history_fetch_diagnostics: dict[str, Any] = {}

    def generate(self, ticker: str, *, as_of: datetime | None = None) -> RunOutput:
        normalized_ticker = ticker.upper()
        history = self._fetch_price_history(normalized_ticker, as_of=as_of)
        enriched = self._enrich_history(history)
        context = self._build_context(enriched)
        context["price_history_diagnostics"] = dict(self._last_price_history_fetch_diagnostics)
        context = self._apply_news_context(context, normalized_ticker, as_of=as_of)
        feature_vector = self._build_feature_vector(context)
        column_ranges = self._compute_column_ranges(enriched)
        normalized_vector = self._normalize_feature_vector(feature_vector, column_ranges)
        normalized_vector["normalized_atr_pct"] = normalized_vector.get("atr_pct", 0.5)
        feature_vector["normalized_atr_pct"] = normalized_vector["normalized_atr_pct"]
        aggregations = self._compute_aggregations(normalized_vector, context["atr"], context["price"])
        direction = RecommendationDirection.LONG if context["direction"] == "LONG" else RecommendationDirection.SHORT
        confidence = self._calculate_confidence(
            direction,
            context["sentiment_score"],
            context.get("enhanced_sentiment_score", context["sentiment_score"]),
            self._macro_context_score(context),
            self._industry_context_score(context),
            context.get("ticker_sentiment_score", 0.0),
            context["rsi"],
            context["price_above_sma50"],
            context["price_above_sma200"],
            context["atr_pct"],
            context["momentum_medium"],
            context.get("news_item_count", 0.0),
            context.get("context_count", 0.0),
            context.get("sentiment_volatility", 0.0),
            context.get("polarity_trend", 0.0),
        )
        entry_price, stop_loss, take_profit = self._suggest_price_levels(
            direction,
            context["price"],
            context["atr"],
            aggregations,
        )
        analysis = self._build_analysis_payload(
            ticker=normalized_ticker,
            direction=context["direction"],
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            context=context,
            feature_vector=feature_vector,
            normalized_vector=normalized_vector,
            aggregations=aggregations,
        )
        analysis_json = json.dumps(analysis, indent=2, sort_keys=True)
        diagnostics = self._build_diagnostics(analysis_json, feature_vector, normalized_vector, aggregations, context)
        recommendation = Recommendation(
            ticker=normalized_ticker,
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            indicator_summary=self._build_indicator_summary(context, aggregations),
            state=RecommendationState.PENDING,
            created_at=as_of or datetime.now(timezone.utc),
        )
        return RunOutput(recommendation=recommendation, diagnostics=diagnostics)

    def _build_indicator_summary(self, context: dict[str, Any], aggregations: dict[str, float]) -> str:
        parts: list[str] = []
        sentiment_label = context.get("sentiment_label")
        if sentiment_label:
            parts.append(f"Sentiment {sentiment_label}")
        rsi = context.get("rsi")
        if isinstance(rsi, (int, float)):
            parts.append(f"RSI {float(rsi):.1f}")
        atr_pct = context.get("atr_pct")
        if isinstance(atr_pct, (int, float)):
            parts.append(f"ATR {float(atr_pct):.2f}%")
        if context.get("price_above_sma200"):
            parts.append("Above SMA200")
        else:
            parts.append("Below SMA200")
        direction = context.get("direction")
        if direction:
            parts.append(direction)
        return " · ".join(parts[:4])

    def _build_analysis_payload(
        self,
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
    ) -> dict[str, Any]:
        summary_text = context.get("summary_text", DEFAULT_SUMMARY_TEXT)
        summary_method = context.get("summary_method", DEFAULT_SUMMARY_METHOD)
        summary_error = context.get("summary_error")
        news_items = context.get("news_items", [])
        context_flags = {
            key.removeprefix("context_tag_"): context.get(key)
            for key in context
            if key.startswith("context_tag_")
        }
        summary_section = {
            "text": summary_text,
            "method": summary_method,
            "backend": context.get("summary_backend"),
            "model": context.get("summary_model"),
            "runtime_seconds": context.get("summary_runtime_seconds"),
            "metadata": context.get("summary_metadata", {}),
            "digest": context.get("news_digest", ""),
            "error": summary_error,
            "llm_error": context.get("llm_error"),
        }
        news_section = {
            "digest": context.get("news_digest", ""),
            "items": news_items,
            "item_count": context.get("news_item_count", 0),
            "point_count": context.get("news_point_count", 0),
            "feeds_used": context.get("news_feeds_used", []),
            "feed_errors": context.get("news_feed_errors", []),
            "source_count": context.get("source_count", 0),
            "context_count": context.get("context_count", 0),
            "sentiment": {
                "score": context.get("news_sentiment_score", 0.0),
                "volatility": context.get("sentiment_volatility", 0.0),
                "polarity_trend": context.get("polarity_trend", 0.0),
                "sources": context.get("sentiment_sources") or [],
            },
        }
        sentiment_section = {
            "score": context.get("sentiment_score"),
            "label": context.get("sentiment_label"),
            "enhanced": {
                "score": context.get("enhanced_sentiment_score"),
                "label": context.get("enhanced_sentiment_label"),
                "components": context.get("enhanced_sentiment_components", {}),
            },
            "macro": {
                "source": context.get("macro_snapshot_source", "computed"),
                "snapshot_id": context.get("macro_snapshot_id"),
                "subject_key": context.get("macro_snapshot_subject_key", "global_macro"),
                "subject_label": context.get("macro_snapshot_subject_label", "Global Macro"),
                "score": self._macro_context_score(context),
                "label": self._macro_context_label(context),
                "coverage_insights": context.get("macro_coverage_insights", []),
                "coverage": context.get("macro_snapshot_coverage", {}),
                "drivers": context.get("macro_snapshot_drivers", []),
                "context_snapshot_id": context.get("macro_context_snapshot_id"),
                "context_summary": context.get("macro_context_summary"),
                "context_status": context.get("macro_context_status"),
                "context_saliency_score": context.get("macro_context_saliency_score", 0.0),
                "context_confidence_percent": context.get("macro_context_confidence_percent", 0.0),
                "context_regime_tags": context.get("macro_context_regime_tags", []),
                "context_lifecycle": context.get("macro_context_lifecycle", {}),
                "context_contradictory_event_labels": context.get("macro_context_contradictory_event_labels", []),
                "context_events": context.get("macro_context_events") or context.get("macro_context_active_themes") or [],
                "source_breakdown": context.get("macro_snapshot_source_breakdown", {
                    "news": {"score": context.get("macro_news_sentiment_score", 0.0), "item_count": context.get("macro_news_item_count", 0)},
                    "social": {"score": context.get("macro_social_sentiment_score", 0.0), "item_count": context.get("macro_social_item_count", 0)},
                }),
            },
            "industry": {
                "source": context.get("industry_snapshot_source", "computed"),
                "snapshot_id": context.get("industry_snapshot_id"),
                "subject_key": context.get("industry_snapshot_subject_key"),
                "subject_label": context.get("industry_snapshot_subject_label", context.get("ticker_profile", {}).get("industry", "")),
                "score": self._industry_context_score(context),
                "label": self._industry_context_label(context),
                "coverage_insights": context.get("industry_coverage_insights", []),
                "coverage": context.get("industry_snapshot_coverage", {}),
                "drivers": context.get("industry_snapshot_drivers", []),
                "context_snapshot_id": context.get("industry_context_snapshot_id"),
                "context_summary": context.get("industry_context_summary"),
                "context_status": context.get("industry_context_status"),
                "context_saliency_score": context.get("industry_context_saliency_score", 0.0),
                "context_confidence_percent": context.get("industry_context_confidence_percent", 0.0),
                "context_regime_tags": context.get("industry_context_regime_tags", []),
                "context_lifecycle": context.get("industry_context_lifecycle", {}),
                "context_contradictory_event_labels": context.get("industry_context_contradictory_event_labels", []),
                "context_events": context.get("industry_context_events") or context.get("industry_context_active_drivers") or [],
                "industry": context.get("ticker_profile", {}).get("industry", ""),
                "source_breakdown": context.get("industry_snapshot_source_breakdown", {
                    "news": {"score": context.get("industry_news_sentiment_score", 0.0), "item_count": context.get("industry_news_item_count", 0)},
                    "social": {"score": context.get("industry_social_sentiment_score", 0.0), "item_count": context.get("industry_social_item_count", 0)},
                }),
            },
            "ticker": {
                "source": "live",
                "score": context.get("ticker_sentiment_score", context.get("sentiment_score")),
                "label": context.get("ticker_sentiment_label", context.get("sentiment_label")),
                "coverage_insights": context.get("social_coverage_insights", []),
                "source_breakdown": {
                    "news": {"score": context.get("news_sentiment_score", 0.0), "item_count": context.get("news_item_count", 0)},
                    "social": {"score": context.get("social_sentiment_score", 0.0), "item_count": context.get("social_item_count", len(context.get("social_items", [])))},
                },
            },
            "overall": {
                "score": context.get("enhanced_sentiment_score", context.get("sentiment_score")),
                "label": context.get("enhanced_sentiment_label", context.get("sentiment_label")),
                "weights": {"macro": 0.2, "industry": 0.3, "ticker": 0.5, "news": 0.55, "social_max": 0.45},
                "divergence_signals": self._build_sentiment_divergence_signals(context),
            },
            "keyword_hits": context.get("sentiment_keyword_hits", 0),
            "coverage_insights": context.get("sentiment_coverage_insights", []),
        }
        signals_section = {
            "version": "0.1",
            "items": context.get("signal_items", []),
            "feeds_used": context.get("signal_feeds_used", []),
            "feed_errors": context.get("signal_feed_errors", []),
            "coverage": context.get("signal_coverage", {}),
            "query_diagnostics": context.get("signal_query_diagnostics", {}),
        }
        social_section = {
            "provider": "nitter",
            "enabled": bool(context.get("social_items") or context.get("signal_query_diagnostics")),
            "items_fetched": len(context.get("social_items", [])),
            "top_items": context.get("social_items", [])[:5],
            "query_diagnostics": context.get("signal_query_diagnostics", {}),
        }
        diagnostics_section = {
            "problems": context.get("problems", []),
            "news_feed_errors": context.get("news_feed_errors", []),
            "signal_feed_errors": context.get("signal_feed_errors", []),
            "summary_error": summary_error,
            "llm_error": context.get("llm_error"),
        }
        entities_section = {
            "ticker": ticker,
            "company_aliases": context.get("ticker_profile", {}).get("aliases", []),
            "sector": context.get("ticker_profile", {}).get("sector", ""),
            "industry": context.get("ticker_profile", {}).get("industry", ""),
            "themes": context.get("ticker_profile", {}).get("themes", []),
            "matched_keywords": context.get("signal_query_diagnostics", {}),
        }
        payload = {
            "metadata": {
                "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
                "analysis_version": "2.0",
                "ticker": ticker,
            },
            "trade": {
                "direction": direction,
                "confidence": confidence,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            },
            "summary": summary_section,
            "news": news_section,
            "signals": signals_section,
            "social": social_section,
            "entities": entities_section,
            "sentiment": sentiment_section,
            "context_flags": context_flags,
            "feature_vectors": {
                "raw": feature_vector,
                "normalized": normalized_vector,
            },
            "aggregations": aggregations,
            "confidence_weights": self.weights.get("confidence", {}),
            "aggregation_weights": self.weights.get("aggregators", {}),
            "diagnostics": diagnostics_section,
        }
        return _sanitize_for_json(payload)

    def _build_diagnostics(
        self,
        analysis_json: str,
        feature_vector: dict[str, float],
        normalized_vector: dict[str, float],
        aggregations: dict[str, float],
        context: dict[str, Any],
    ) -> RunDiagnostics:
        safe_feature_vector = _sanitize_for_json(feature_vector)
        safe_normalized_vector = _sanitize_for_json(normalized_vector)
        safe_aggregations = _sanitize_for_json(aggregations)
        safe_confidence_weights = _sanitize_for_json(self.weights.get("confidence", {}))
        diagnostics = RunDiagnostics(
            warnings=list(dict.fromkeys(context.get("problems", []))),
            provider_errors=[],
            problems=context.get("problems", []),
            news_feed_errors=context.get("news_feed_errors", []),
            summary_error=context.get("summary_error"),
            llm_error=context.get("llm_error"),
            raw_output=analysis_json,
            analysis_json=analysis_json,
            feature_vector_json=json.dumps(safe_feature_vector, indent=2, sort_keys=True),
            normalized_feature_vector_json=json.dumps(safe_normalized_vector, indent=2, sort_keys=True),
            aggregations_json=json.dumps(safe_aggregations, indent=2, sort_keys=True),
            confidence_weights_json=json.dumps(safe_confidence_weights, indent=2, sort_keys=True),
            summary_method=context.get("summary_method", DEFAULT_SUMMARY_METHOD),
        )
        return diagnostics

    def _load_weights(self) -> dict[str, dict[str, float]]:
        if not self.weights_path.exists():
            return {
                "confidence": {},
                "aggregators": {section: dict(values) for section, values in AGGREGATOR_DEFAULTS.items()},
            }
        try:
            with open(self.weights_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise ProposalExecutionError("invalid weights payload") from exc
        confidence = {k: float(v) for k, v in payload.get("confidence", {}).items()}
        aggregators = {
            section: {key: float(values.get(key, default_value)) for key, default_value in defaults.items()}
            for section, defaults in AGGREGATOR_DEFAULTS.items()
            for values in [payload.get("aggregators", {}).get(section, {})]
        }
        return {"confidence": confidence, "aggregators": aggregators}

    def _fetch_price_history(self, ticker: str, *, as_of: datetime | None = None) -> pd.DataFrame:
        normalized_ticker = ticker.strip().upper()
        is_replay = as_of is not None
        local_history = self._fetch_price_history_from_local_store(normalized_ticker, as_of=as_of)
        local_bar_count = len(local_history)
        self._last_price_history_fetch_diagnostics = {
            "ticker": normalized_ticker,
            "mode": "replay" if is_replay else "live",
            "source": "unavailable",
            "fallback_used": False,
            "remote_attempt_count": 0,
            "remote_attempted": False,
            "remote_errors": [],
            "local_bar_count": local_bar_count,
            "selected_bar_count": 0,
            "latest_bar_time": self._latest_bar_time_iso(local_history),
        }
        if is_replay and not local_history.empty:
            self._last_price_history_fetch_diagnostics.update(
                {
                    "source": "local_replay",
                    "selected_bar_count": local_bar_count,
                    "fallback_used": False,
                }
            )
            return local_history

        remote_error: ProposalExecutionError | None = None
        remote_history = pd.DataFrame()
        remote_attempts = 1 if is_replay else self.LIVE_REMOTE_FETCH_ATTEMPTS
        for attempt in range(remote_attempts):
            backoff = self.LIVE_REMOTE_FETCH_BACKOFF_SECONDS[min(attempt, len(self.LIVE_REMOTE_FETCH_BACKOFF_SECONDS) - 1)] if not is_replay else 0.0
            if backoff > 0:
                import time
                time.sleep(backoff)
            self._last_price_history_fetch_diagnostics["remote_attempted"] = True
            self._last_price_history_fetch_diagnostics["remote_attempt_count"] = attempt + 1
            try:
                remote_history = self._fetch_price_history_remote(normalized_ticker, as_of=as_of)
            except ProposalExecutionError as exc:
                remote_error = exc
                self._last_price_history_fetch_diagnostics.setdefault("remote_errors", []).append(str(exc))
                continue
            if not remote_history.empty:
                self._last_price_history_fetch_diagnostics.update(
                    {
                        "source": "remote",
                        "fallback_used": False,
                        "selected_bar_count": len(remote_history),
                        "latest_bar_time": self._latest_bar_time_iso(remote_history),
                    }
                )
                self._persist_price_history(normalized_ticker, remote_history)
                return remote_history
            remote_error = ProposalExecutionError(f"could not retrieve historical data for '{normalized_ticker}'")
            self._last_price_history_fetch_diagnostics.setdefault("remote_errors", []).append(str(remote_error))

        if not local_history.empty:
            self._last_price_history_fetch_diagnostics.update(
                {
                    "source": "local_fallback",
                    "fallback_used": True,
                    "selected_bar_count": local_bar_count,
                    "latest_bar_time": self._latest_bar_time_iso(local_history),
                }
            )
            return local_history
        if remote_error is not None:
            raise remote_error
        raise ProposalExecutionError(f"could not retrieve historical data for '{normalized_ticker}'")

    @staticmethod
    def _latest_bar_time_iso(history: pd.DataFrame) -> str | None:
        if history.empty:
            return None
        latest = history.index[-1]
        if not isinstance(latest, datetime):
            latest = pd.to_datetime(latest).to_pydatetime()
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        else:
            latest = latest.astimezone(timezone.utc)
        return latest.isoformat()

    def _fetch_price_history_remote(self, ticker: str, *, as_of: datetime | None = None) -> pd.DataFrame:
        try:
            if as_of:
                start_at = as_of - timedelta(days=365)
                history = yf.download(ticker, start=start_at.date().isoformat(), end=(as_of + timedelta(days=1)).date().isoformat(), interval="1d", progress=False, auto_adjust=False)
            else:
                history = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=False)
        except Exception as exc:
            raise ProposalExecutionError(f"failed to download historical data: {exc}") from exc
        if history is None or history.empty:
            return pd.DataFrame()
        if isinstance(history.columns, pd.MultiIndex):
            if ticker in history.columns.get_level_values(1):
                history = history.xs(ticker, axis=1, level=1)
            elif ticker in history.columns.get_level_values(0):
                history = history.xs(ticker, axis=1, level=0)
            else:
                history = history.copy()
                history.columns = history.columns.get_level_values(0)
        return history

    def _fetch_price_history_from_local_store(self, ticker: str, *, as_of: datetime | None = None) -> pd.DataFrame:
        if self.historical_market_data is None:
            return pd.DataFrame()
        end_at = as_of or datetime.now(timezone.utc)
        bars = self.historical_market_data.list_bars(
            ticker=ticker,
            timeframe="1d",
            end_at=end_at,
            available_at=end_at,
            limit=260,
        )
        if not bars:
            return pd.DataFrame()
        records = [
            {
                "Date": bar.bar_time,
                "Open": bar.open_price,
                "High": bar.high_price,
                "Low": bar.low_price,
                "Close": bar.close_price,
                "Volume": bar.volume,
            }
            for bar in bars
        ]
        history = pd.DataFrame(records)
        history.set_index("Date", inplace=True)
        history.sort_index(inplace=True)
        return history

    def _persist_price_history(self, ticker: str, history: pd.DataFrame) -> None:
        if self.historical_market_data is None or history.empty:
            return
        bars: list[HistoricalMarketBar] = []
        for timestamp, row in history.iterrows():
            bar_time = timestamp if isinstance(timestamp, datetime) else pd.to_datetime(timestamp).to_pydatetime()
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)
            bars.append(
                HistoricalMarketBar(
                    ticker=ticker,
                    timeframe="1d",
                    bar_time=bar_time,
                    available_at=datetime.combine(bar_time.date(), datetime.max.time(), tzinfo=timezone.utc),
                    open_price=float(row["Open"]),
                    high_price=float(row["High"]),
                    low_price=float(row["Low"]),
                    close_price=float(row["Close"]),
                    volume=float(row.get("Volume", 0.0) or 0.0),
                    adjusted_close=float(row["Adj Close"]) if "Adj Close" in history.columns and pd.notna(row.get("Adj Close")) else None,
                    source="yahoo_fallback",
                    source_tier="tier_b",
                    point_in_time_confidence=0.8,
                )
            )
        if bars:
            try:
                self.historical_market_data.upsert_bars(bars)
            except Exception:
                pass

    def _enrich_history(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["SMA_20"] = enriched["Close"].rolling(window=20).mean()
        enriched["SMA_50"] = enriched["Close"].rolling(window=50).mean()
        enriched["SMA_200"] = enriched["Close"].rolling(window=200).mean()
        enriched["RSI_14"] = self._calculate_rsi(enriched)
        enriched["ATR_14"] = self._calculate_atr(enriched)
        enriched = self._enrich_ratios(enriched)
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
    def _enrich_ratios(df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
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
        enriched["price_vs_sma20_ratio"] = ProposalService._compute_ratio_series(enriched["Close"], enriched["SMA_20"])
        enriched["price_vs_sma50_ratio"] = ProposalService._compute_ratio_series(enriched["Close"], enriched["SMA_50"])
        enriched["price_vs_sma200_ratio"] = ProposalService._compute_ratio_series(enriched["Close"], enriched["SMA_200"])
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
    def _compute_ratio_series(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
        safe_den = denominator.replace(0, pd.NA)
        ratio = numerator.divide(safe_den)
        ratio = ratio.replace([float("inf"), float("-inf")], pd.NA)
        return (ratio - 1).fillna(0.0)

    def _build_context(self, df: pd.DataFrame) -> dict[str, Any]:
        latest = df.iloc[-1]
        price = float(latest.get("Close", 0.0))
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
        trend_bullish = price > sma200
        direction = "LONG" if trend_bullish else "SHORT"
        short_bullish = short_bearish = 0
        if price > sma20:
            short_bullish += 1
        else:
            short_bearish += 1
        if rsi < 30:
            short_bullish += 1
        elif rsi > 70:
            short_bearish += 1
        if price_above_sma50:
            short_bullish += 1
        else:
            short_bearish += 1
        med_bullish = med_bearish = 0
        if price > sma50:
            med_bullish += 1
        else:
            med_bearish += 1
        if price > sma200:
            med_bullish += 1
        else:
            med_bearish += 1
        if price_above_sma200:
            med_bullish += 1
        else:
            med_bearish += 1
        problems: list[str] = []
        if sma200 == 0.0:
            problems.append("history: insufficient data for SMA200")
        context: dict[str, Any] = {
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
            "short_bullish": float(short_bullish),
            "short_bearish": float(short_bearish),
            "medium_bullish": float(med_bullish),
            "medium_bearish": float(med_bearish),
            "direction": direction,
        }
        news_context = self._build_news_context_base()
        context.update(news_context)
        context["sentiment_label"] = "PRICE_ONLY"
        context["news_feeds_used"] = []
        context["news_feed_errors"] = []
        context["problems"] = problems
        return context

    def _build_news_context_base(self) -> dict[str, Any]:
        base_context = {
            "sentiment_score": 0.0,
            "sentiment_label": None,
            "sentiment_sources": [],
            "source_count": 0,
            "context_count": 0,
            "news_point_count": 0,
            "news_item_count": 0,
            "news_items": [],
            "polarity_trend": 0.0,
            "sentiment_volatility": 0.0,
            "news_feeds_used": [],
            "news_feed_errors": [],
            "summary_text": DEFAULT_SUMMARY_TEXT,
            "summary_method": DEFAULT_SUMMARY_METHOD,
            "summary_error": None,
            "news_digest": "",
            "summary_backend": None,
            "summary_model": None,
            "summary_runtime_seconds": None,
            "summary_metadata": {},
            "llm_error": None,
            "news_sentiment_score": 0.0,
            "enhanced_sentiment_score": 0.0,
            "enhanced_sentiment_label": None,
            "enhanced_sentiment_components": {},
            "signal_items": [],
            "signal_feeds_used": [],
            "signal_feed_errors": [],
            "signal_coverage": {"news_count": 0, "social_count": 0, "total_count": 0},
            "signal_query_diagnostics": {},
            "social_items": [],
            "social_sentiment_score": 0.0,
            "social_sentiment_label": None,
            "social_sentiment_volatility": 0.0,
            "social_keyword_hits": 0,
            "social_coverage_insights": [],
            "social_item_count": 0,
            "macro_sentiment_score": 0.0,
            "macro_sentiment_label": "NEUTRAL",
            "macro_context_score": 0.0,
            "macro_context_label": "NEUTRAL",
            "macro_coverage_insights": [],
            "macro_item_count": 0,
            "industry_sentiment_score": 0.0,
            "industry_sentiment_label": "NEUTRAL",
            "industry_context_score": 0.0,
            "industry_context_label": "NEUTRAL",
            "industry_coverage_insights": [],
            "industry_item_count": 0,
            "ticker_sentiment_score": 0.0,
            "ticker_sentiment_label": None,
            "ticker_item_count": 0,
            "ticker_profile": {},
        }
        base_context.update(dict(DEFAULT_CONTEXT_FLAGS))
        return base_context

    def _build_technical_snapshot(self, context: dict[str, Any]) -> TechnicalSnapshot:
        return TechnicalSnapshot(
            price=float(context.get("price", 0.0)),
            sma20=self._to_optional_float(context.get("sma20")),
            sma50=self._to_optional_float(context.get("sma50")),
            sma200=self._to_optional_float(context.get("sma200")),
            rsi=self._to_optional_float(context.get("rsi"), preserve_zero=True),
            atr=self._to_optional_float(context.get("atr"), preserve_zero=True),
        )

    def _compute_enhanced_sentiment(
        self,
        *,
        base_score: float,
        summary_text: str,
        snapshot: TechnicalSnapshot,
    ) -> dict[str, object]:
        summary_score = self._score_summary_text(summary_text)
        technical_score = self._score_technical_snapshot(snapshot)
        combined = (base_score * 0.45) + (summary_score * 0.35) + (technical_score * 0.2)
        combined = self._clamp_value(combined)
        label = "NEUTRAL"
        if combined > 0.25:
            label = "POSITIVE"
        elif combined < -0.25:
            label = "NEGATIVE"
        return {
            "score": combined,
            "label": label,
            "components": {
                "news_sentiment": base_score,
                "summary_sentiment": summary_score,
                "technical_sentiment": technical_score,
            },
        }

    def _build_sentiment_divergence_signals(self, context: dict[str, Any]) -> list[str]:
        news_score = float(context.get("news_sentiment_score", 0.0) or 0.0)
        social_score = float(context.get("social_sentiment_score", 0.0) or 0.0)
        social_count = int(context.get("social_item_count", 0) or 0)
        macro_score = self._macro_context_score(context)
        ticker_score = float(context.get("ticker_sentiment_score", 0.0) or 0.0)
        signals: list[str] = []
        if social_count > 0 and abs(news_score - social_score) >= 0.45:
            signals.append("news and social sentiment are materially divergent for this ticker")
        if social_count == 0:
            signals.append("social sentiment unavailable; ticker score relies on news-only sentiment")
        if abs(macro_score - ticker_score) >= 0.45:
            signals.append("macro and ticker sentiment are materially divergent")
        return signals

    def _blend_ticker_sentiment(
        self,
        *,
        news_sentiment_score: float,
        social_sentiment_score: float,
        social_item_count: int,
    ) -> float:
        if social_item_count <= 0:
            return self._clamp_value(news_sentiment_score)
        social_weight = min(0.45, 0.15 + (min(social_item_count, 10) / 10.0) * 0.3)
        news_weight = 1.0 - social_weight
        return self._clamp_value((news_sentiment_score * news_weight) + (social_sentiment_score * social_weight))

    def _fuse_scope_sentiment(
        self,
        *,
        news_score: float,
        news_item_count: int,
        social_score: float,
        social_item_count: int,
        base_news_weight: float,
        max_social_weight: float,
    ) -> float:
        if social_item_count <= 0:
            return self._clamp_value(news_score)
        social_weight = min(max_social_weight, 0.1 + (min(social_item_count, 10) / 10.0) * max_social_weight)
        news_weight = max(base_news_weight, 1.0 - social_weight)
        total_weight = news_weight + social_weight
        return self._clamp_value(((news_score * news_weight) + (social_score * social_weight)) / max(total_weight, 1e-9))

    def _derive_news_scope_scores(
        self,
        *,
        news_sentiment_score: float,
        context_flags: dict[str, float],
        news_item_count: int,
    ) -> dict[str, float | int | list[str]]:
        macro_item_count = news_item_count if context_flags.get("context_tag_geopolitical") or context_flags.get("context_tag_general") else 0
        industry_item_count = news_item_count if context_flags.get("context_tag_industry") else 0
        macro_score = news_sentiment_score * (0.7 if macro_item_count else 0.0)
        industry_score = news_sentiment_score * (0.8 if industry_item_count else 0.0)
        macro_coverage_insights = [] if macro_item_count else ["macro: no explicit macro-tagged news detected; relying on social or neutral fallback."]
        industry_coverage_insights = [] if industry_item_count else ["industry: no explicit industry-tagged news detected; relying on social or neutral fallback."]
        return {
            "macro_news_sentiment_score": self._clamp_value(macro_score),
            "macro_news_item_count": macro_item_count,
            "industry_news_sentiment_score": self._clamp_value(industry_score),
            "industry_news_item_count": industry_item_count,
            "macro_news_coverage_insights": macro_coverage_insights,
            "industry_news_coverage_insights": industry_coverage_insights,
        }

    def _compute_hierarchical_sentiment(
        self,
        *,
        news_sentiment_score: float,
        news_item_count: int,
        social_breakdown: dict[str, Any],
        context_flags: dict[str, float],
    ) -> dict[str, Any]:
        news_scopes = self._derive_news_scope_scores(
            news_sentiment_score=news_sentiment_score,
            context_flags=context_flags,
            news_item_count=news_item_count,
        )
        macro_social_score = float((social_breakdown.get("macro") or {}).get("score", 0.0) or 0.0)
        macro_social_count = int((social_breakdown.get("macro") or {}).get("item_count", 0) or 0)
        industry_social_score = float((social_breakdown.get("industry") or {}).get("score", 0.0) or 0.0)
        industry_social_count = int((social_breakdown.get("industry") or {}).get("item_count", 0) or 0)
        ticker_social_score = float((social_breakdown.get("ticker") or {}).get("score", 0.0) or 0.0)
        ticker_social_count = int((social_breakdown.get("ticker") or {}).get("item_count", 0) or 0)

        macro_score = self._fuse_scope_sentiment(
            news_score=float(news_scopes["macro_news_sentiment_score"]),
            news_item_count=int(news_scopes["macro_news_item_count"]),
            social_score=macro_social_score,
            social_item_count=macro_social_count,
            base_news_weight=0.7,
            max_social_weight=0.3,
        )
        industry_score = self._fuse_scope_sentiment(
            news_score=float(news_scopes["industry_news_sentiment_score"]),
            news_item_count=int(news_scopes["industry_news_item_count"]),
            social_score=industry_social_score,
            social_item_count=industry_social_count,
            base_news_weight=0.6,
            max_social_weight=0.4,
        )
        ticker_score = self._blend_ticker_sentiment(
            news_sentiment_score=news_sentiment_score,
            social_sentiment_score=ticker_social_score,
            social_item_count=ticker_social_count,
        )
        return {
            **news_scopes,
            "macro_social_sentiment_score": macro_social_score,
            "macro_social_item_count": macro_social_count,
            "industry_social_sentiment_score": industry_social_score,
            "industry_social_item_count": industry_social_count,
            "macro_sentiment_score": macro_score,
            "macro_sentiment_label": self._label_sentiment(macro_score),
            "macro_context_score": macro_score,
            "macro_context_label": self._label_sentiment(macro_score),
            "macro_item_count": int(news_scopes["macro_news_item_count"]) + macro_social_count,
            "macro_coverage_insights": list(dict.fromkeys(list(news_scopes["macro_news_coverage_insights"]) + (["macro: no social macro items matched."] if macro_social_count == 0 else []))),
            "industry_sentiment_score": industry_score,
            "industry_sentiment_label": self._label_sentiment(industry_score),
            "industry_context_score": industry_score,
            "industry_context_label": self._label_sentiment(industry_score),
            "industry_item_count": int(news_scopes["industry_news_item_count"]) + industry_social_count,
            "industry_coverage_insights": list(dict.fromkeys(list(news_scopes["industry_news_coverage_insights"]) + (["industry: no social industry items matched."] if industry_social_count == 0 else []))),
            "ticker_sentiment_score": ticker_score,
            "ticker_sentiment_label": self._label_sentiment(ticker_score),
            "ticker_item_count": news_item_count + ticker_social_count,
        }

    @staticmethod
    def _label_sentiment(score: float | None) -> str | None:
        if score is None:
            return None
        if score > 0.15:
            return "POSITIVE"
        if score < -0.15:
            return "NEGATIVE"
        return "NEUTRAL"

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

    def _score_summary_text(self, text: str) -> float:
        tokens = self._tokenize_text(text)
        if not tokens:
            return 0.0
        positive = sum(POSITIVE_KEYWORD_WEIGHTS.get(token, 0.0) * SUMMARY_KEYWORD_WEIGHT for token in tokens)
        negative = sum(NEGATIVE_KEYWORD_WEIGHTS.get(token, 0.0) * SUMMARY_KEYWORD_WEIGHT for token in tokens)
        total = positive + negative + 0.5
        if total == 0:
            return 0.0
        return self._clamp_value((positive - negative) / total)

    def _score_technical_snapshot(self, snapshot: TechnicalSnapshot) -> float:
        components: list[float] = []
        price = snapshot.price
        if price and snapshot.sma200:
            components.append((price - snapshot.sma200) / price)
        if price and snapshot.sma50:
            components.append((price - snapshot.sma50) / price)
        if snapshot.rsi is not None:
            components.append((snapshot.rsi - 50.0) / 50.0)
        if not components:
            return 0.0
        return self._clamp_value(sum(components) / len(components))

    @staticmethod
    def _tokenize_text(text: str) -> list[str]:
        if not text:
            return []
        return re.findall(r"[a-z0-9]+", text.lower())

    @staticmethod
    def _clamp_value(value: float) -> float:
        return max(-1.0, min(1.0, value))

    @staticmethod
    def _to_optional_float(value: object | None, *, preserve_zero: bool = False) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not preserve_zero and numeric == 0.0:
            return None
        return numeric

    def _apply_news_context(self, context: dict[str, Any], ticker: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        context.update(self._build_news_context_base())
        
        effective_now = as_of or datetime.now(timezone.utc)
        start_at = effective_now - timedelta(hours=24)
        
        signal_bundle = self.signal_service.fetch(ticker, start_at=start_at, end_at=effective_now) if self.signal_service is not None else None
        if signal_bundle is not None:
            signal_items = [item.model_dump(mode="json") for item in signal_bundle.items]
            social_items = [item for item in signal_items if item.get("source_type") == "social"]
            context.update(
                {
                    "signal_items": signal_items,
                    "signal_feeds_used": signal_bundle.feeds_used,
                    "signal_feed_errors": signal_bundle.feed_errors,
                    "signal_coverage": signal_bundle.coverage,
                    "signal_query_diagnostics": signal_bundle.query_diagnostics,
                    "social_items": social_items,
                }
            )
        social_sentiment: dict[str, Any] = {}
        social_scope_breakdown: dict[str, Any] = {}
        if self.social_service is not None:
            social_result = self.social_service.analyze(ticker, start_at=start_at, end_at=effective_now)
            social_sentiment = social_result.get("sentiment", {})
            social_scope_breakdown = social_sentiment.get("scope_breakdown", {})
            context.update(
                {
                    "ticker_profile": social_result.get("profile", {}),
                    "social_sentiment_score": social_sentiment.get("score", 0.0),
                    "social_sentiment_label": social_sentiment.get("label"),
                    "social_sentiment_volatility": social_sentiment.get("sentiment_volatility", 0.0),
                    "social_keyword_hits": social_sentiment.get("keyword_hits", 0),
                    "social_coverage_insights": social_sentiment.get("coverage_insights", []),
                    "social_item_count": social_sentiment.get("item_count", len(context.get("social_items", []))),
                    "social_items": social_sentiment.get("items", context.get("social_items", [])),
                    "social_scope_breakdown": social_scope_breakdown,
                }
            )
        if self.news_service is None:
            merged_problems = list(dict.fromkeys(context.get("problems", []) + context.get("signal_feed_errors", [])))
            context["problems"] = merged_problems
            return context
        bundle = self.news_service.fetch(ticker, start_at=start_at, end_at=effective_now)
        sentiment = self.sentiment_analyzer.analyze(bundle)
        feeds = list(dict.fromkeys(bundle.feeds_used))
        news_items = sentiment.get("news_items") or sentiment.get("news_points", [])
        digest = self._build_news_summary(news_items or bundle.articles)
        technical_snapshot = self._build_technical_snapshot(context)
        summary_result = self.summary_service.summarize(
            SummaryRequest(
                ticker=ticker,
                news_items=news_items,
                technical_snapshot=technical_snapshot,
            )
        )
        if summary_result.summary:
            summary_text = summary_result.summary
            summary_method = summary_result.method
        else:
            summary_text = digest or ""
            summary_method = SUMMARY_METHOD_NEWS_DIGEST if digest else DEFAULT_SUMMARY_METHOD
        news_sentiment_score = sentiment.get("score", 0.0)
        hierarchical = self._compute_hierarchical_sentiment(
            news_sentiment_score=news_sentiment_score,
            news_item_count=len(news_items),
            social_breakdown=social_scope_breakdown,
            context_flags=sentiment.get("context_flags", {}),
        )
        macro_snapshot = self.snapshot_resolver.resolve_macro_snapshot(as_of=as_of) if self.snapshot_resolver is not None else None
        if macro_snapshot is not None:
            hierarchical.update(
                {
                    "macro_sentiment_score": float(macro_snapshot.get("score", 0.0) or 0.0),
                    "macro_sentiment_label": macro_snapshot.get("label", "NEUTRAL"),
                    "macro_context_score": float(macro_snapshot.get("score", 0.0) or 0.0),
                    "macro_context_label": macro_snapshot.get("label", "NEUTRAL"),
                    "macro_snapshot_id": macro_snapshot.get("snapshot_id"),
                    "macro_snapshot_subject_key": macro_snapshot.get("subject_key"),
                    "macro_snapshot_subject_label": macro_snapshot.get("subject_label"),
                    "macro_snapshot_source": macro_snapshot.get("source", "snapshot"),
                    "macro_snapshot_coverage": macro_snapshot.get("coverage", {}),
                    "macro_snapshot_source_breakdown": macro_snapshot.get("source_breakdown", {}),
                    "macro_snapshot_drivers": macro_snapshot.get("drivers", []),
                    "macro_context_snapshot_id": macro_snapshot.get("context_snapshot_id"),
                    "macro_context_status": macro_snapshot.get("context_status"),
                    "macro_context_summary": macro_snapshot.get("context_summary"),
                    "macro_context_saliency_score": float(macro_snapshot.get("context_saliency_score", 0.0) or 0.0),
                    "macro_context_confidence_percent": float(macro_snapshot.get("context_confidence_percent", 0.0) or 0.0),
                    "macro_context_events": macro_snapshot.get("context_active_events", []),
                    "macro_context_active_themes": macro_snapshot.get("context_active_themes", []),
                    "macro_context_regime_tags": macro_snapshot.get("context_regime_tags", []),
                    "macro_context_lifecycle": macro_snapshot.get("context_lifecycle", {}),
                    "macro_context_contradictory_event_labels": macro_snapshot.get("context_contradictory_event_labels", []),
                    "macro_context_source_breakdown": macro_snapshot.get("context_source_breakdown", {}),
                    "macro_context_metadata": macro_snapshot.get("context_metadata", {}),
                    "macro_coverage_insights": list(
                        dict.fromkeys(
                            hierarchical.get("macro_coverage_insights", [])
                            + list((macro_snapshot.get("diagnostics", {}) or {}).get("warnings", []))
                        )
                    ),
                }
            )
        industry_snapshot = self.snapshot_resolver.resolve_industry_snapshot(ticker, as_of=as_of) if self.snapshot_resolver is not None else None
        if industry_snapshot is not None:
            hierarchical.update(
                {
                    "industry_sentiment_score": float(industry_snapshot.get("score", 0.0) or 0.0),
                    "industry_sentiment_label": industry_snapshot.get("label", "NEUTRAL"),
                    "industry_context_score": float(industry_snapshot.get("score", 0.0) or 0.0),
                    "industry_context_label": industry_snapshot.get("label", "NEUTRAL"),
                    "industry_snapshot_id": industry_snapshot.get("snapshot_id"),
                    "industry_snapshot_subject_key": industry_snapshot.get("subject_key"),
                    "industry_snapshot_subject_label": industry_snapshot.get("subject_label"),
                    "industry_snapshot_source": industry_snapshot.get("source", "snapshot"),
                    "industry_snapshot_coverage": industry_snapshot.get("coverage", {}),
                    "industry_snapshot_source_breakdown": industry_snapshot.get("source_breakdown", {}),
                    "industry_snapshot_drivers": industry_snapshot.get("drivers", []),
                    "industry_context_snapshot_id": industry_snapshot.get("context_snapshot_id"),
                    "industry_context_status": industry_snapshot.get("context_status"),
                    "industry_context_summary": industry_snapshot.get("context_summary"),
                    "industry_context_saliency_score": float(industry_snapshot.get("context_saliency_score", 0.0) or 0.0),
                    "industry_context_confidence_percent": float(industry_snapshot.get("context_confidence_percent", 0.0) or 0.0),
                    "industry_context_events": industry_snapshot.get("context_active_events", []),
                    "industry_context_active_drivers": industry_snapshot.get("context_active_drivers", []),
                    "industry_context_regime_tags": industry_snapshot.get("context_regime_tags", []),
                    "industry_context_lifecycle": industry_snapshot.get("context_lifecycle", {}),
                    "industry_context_contradictory_event_labels": industry_snapshot.get("context_contradictory_event_labels", []),
                    "industry_context_source_breakdown": industry_snapshot.get("context_source_breakdown", {}),
                    "industry_context_metadata": industry_snapshot.get("context_metadata", {}),
                    "industry_coverage_insights": list(
                        dict.fromkeys(
                            hierarchical.get("industry_coverage_insights", [])
                            + list((industry_snapshot.get("diagnostics", {}) or {}).get("warnings", []))
                        )
                    ),
                }
            )
        ticker_sentiment_score = float(hierarchical.get("ticker_sentiment_score", 0.0) or 0.0)
        ticker_sentiment_label = hierarchical.get("ticker_sentiment_label")
        overall_base_score = self._clamp_value(
            (float(hierarchical.get("macro_context_score", hierarchical.get("macro_sentiment_score", 0.0))) * 0.2)
            + (float(hierarchical.get("industry_context_score", hierarchical.get("industry_sentiment_score", 0.0))) * 0.3)
            + (ticker_sentiment_score * 0.5)
        )
        enhanced = self._compute_enhanced_sentiment(
            base_score=overall_base_score,
            summary_text=summary_text,
            snapshot=technical_snapshot,
        )
        use_enhanced = summary_method.startswith("llm_summary") and summary_result.llm_error is None and bool(summary_result.summary)
        final_score = enhanced["score"] if use_enhanced else overall_base_score
        final_label = enhanced["label"] if use_enhanced else self._label_sentiment(overall_base_score)
        context.update(
            {
                "news_feeds_used": feeds,
                "news_feed_errors": bundle.feed_errors,
                "source_count": len(feeds),
                "context_count": len(sentiment.get("contexts", [])),
                "news_point_count": len(news_items),
                "news_item_count": len(news_items),
                "news_items": news_items,
                "polarity_trend": sentiment.get("polarity_trend", 0.0),
                "sentiment_volatility": sentiment.get("sentiment_volatility", 0.0),
                "sentiment_keyword_hits": sentiment.get("keyword_hits", 0),
                "sentiment_score": final_score,
                "sentiment_label": final_label,
                "sentiment_sources": sentiment.get("sources") or feeds,
                "sentiment_coverage_insights": list(dict.fromkeys(sentiment.get("coverage_insights", []) + context.get("social_coverage_insights", []))),
                "news_digest": digest,
                "news_sentiment_score": news_sentiment_score,
                "summary_text": summary_text or DEFAULT_SUMMARY_TEXT,
                "summary_method": summary_method,
                "summary_backend": summary_result.backend,
                "summary_model": summary_result.model,
                "summary_runtime_seconds": summary_result.duration_seconds,
                "summary_metadata": summary_result.metadata,
                "summary_error": summary_result.llm_error,
                "llm_error": summary_result.llm_error,
                "enhanced_sentiment_score": enhanced["score"],
                "enhanced_sentiment_label": enhanced["label"],
                "enhanced_sentiment_components": enhanced["components"],
                **hierarchical,
            }
        )
        context_flags = sentiment.get("context_flags", {})
        for tag, value in context_flags.items():
            context[tag] = value
        merged_problems = list(
            dict.fromkeys(
                context.get("problems", [])
                + sentiment.get("problems", [])
                + context.get("signal_feed_errors", [])
            )
        )
        summary_problem = summary_result.llm_error
        if summary_problem:
            merged_problems.append(summary_problem)
        context["problems"] = list(dict.fromkeys(merged_problems))
        return context

    def _build_news_summary(self, news_items: list[Any]) -> str:
        titles: list[str] = []
        for item in news_items:
            title = ""
            if isinstance(item, NewsArticle):
                title = item.title
            elif isinstance(item, dict):
                title = item.get("title", "")
            if title:
                titles.append(title.strip())
        if not titles:
            return ""
        return " | ".join(titles[:NEWS_SUMMARY_ARTICLE_LIMIT])

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
            vector[key] = float(context.get(key, 0.0))
        return vector

    def _normalize_feature_vector(
        self,
        feature_vector: dict[str, float],
        column_ranges: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, raw_value in feature_vector.items():
            column = FEATURE_COLUMN_MAP.get(key)
            if column and column in column_ranges:
                bounds = column_ranges[column]
            else:
                bounds = MANUAL_FEATURE_RANGES.get(key, (0.0, 1.0))
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

        direction_weights = self.weights.get("aggregators", {}).get("direction", {})
        risk_weights = self.weights.get("aggregators", {}).get("risk", {})
        entry_weights = self.weights.get("aggregators", {}).get("entry", {})

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
            "direction_score": direction_score,
            "risk_offset_pct": risk_offset_pct,
            "risk_stop_offset": risk_stop_offset,
            "risk_take_profit_offset": risk_take_profit_offset,
            "entry_adjustment": entry_adjustment,
            "entry_drift_signal": entry_signal,
        }

    def _calculate_confidence(
        self,
        direction: RecommendationDirection,
        sentiment_score: float,
        enhanced_sentiment_score: float,
        macro_sentiment_score: float,
        industry_sentiment_score: float,
        ticker_sentiment_score: float,
        rsi: float,
        price_above_sma50: int,
        price_above_sma200: int,
        atr_pct: float,
        momentum_medium: float,
        news_item_count: float,
        context_count: float,
        sentiment_volatility: float,
        polarity_trend: float,
    ) -> float:
        weights = self.weights.get("confidence", {})
        base = weights.get("base", 0.0)
        total = base
        sentiment_weight = weights.get("sentiment", 0.0)
        enhanced_weight = weights.get("enhanced_sentiment", 0.0)
        macro_weight = weights.get("macro_sentiment", 1.0)
        industry_weight = weights.get("industry_sentiment", 1.5)
        ticker_weight = weights.get("ticker_sentiment", 2.0)
        momentum_weight = weights.get("momentum_medium", 0.0)
        news_coverage_weight = weights.get("news_coverage", 0.0)
        context_coverage_weight = weights.get("context_coverage", 0.0)
        polarity_weight = weights.get("polarity_trend", 0.0)
        swing_penalty = weights.get("sentiment_volatility", 0.0)
        sma50_weight = weights.get("price_above_sma50", 0.0)
        sma200_weight = weights.get("price_above_sma200", 0.0)
        rsi_penalty = weights.get("rsi_penalty", 0.0)
        atr_penalty = weights.get("atr_penalty", 0.0)

        sent_f = sentiment_score if direction == RecommendationDirection.LONG else -sentiment_score
        enhanced_f = enhanced_sentiment_score if direction == RecommendationDirection.LONG else -enhanced_sentiment_score
        macro_f = macro_sentiment_score if direction == RecommendationDirection.LONG else -macro_sentiment_score
        industry_f = industry_sentiment_score if direction == RecommendationDirection.LONG else -industry_sentiment_score
        ticker_f = ticker_sentiment_score if direction == RecommendationDirection.LONG else -ticker_sentiment_score
        momentum_f = momentum_medium if direction == RecommendationDirection.LONG else -momentum_medium
        sma50_f = price_above_sma50 if direction == RecommendationDirection.LONG else 1.0 - price_above_sma50
        sma200_f = price_above_sma200 if direction == RecommendationDirection.LONG else 1.0 - price_above_sma200
        rsi_f = rsi if direction == RecommendationDirection.LONG else (100.0 - rsi)
        polarity_f = polarity_trend if direction == RecommendationDirection.LONG else -polarity_trend

        news_coverage = min(news_item_count / NEWS_COVERAGE_SCALE, 1.0)
        context_coverage = min(context_count / CONTEXT_COVERAGE_SCALE, 1.0)

        total += sent_f * sentiment_weight
        total += enhanced_f * enhanced_weight
        total += macro_f * macro_weight
        total += industry_f * industry_weight
        total += ticker_f * ticker_weight
        total += momentum_f * momentum_weight
        total += news_coverage * news_coverage_weight
        total += context_coverage * context_coverage_weight
        total += polarity_f * polarity_weight
        total += sentiment_volatility * swing_penalty
        total += sma50_f * sma50_weight
        total += sma200_f * sma200_weight
        total += rsi_f * rsi_penalty
        total += atr_pct * atr_penalty
        return round(max(0.0, min(95.0, total)), 2)

    def _suggest_price_levels(
        self,
        direction: RecommendationDirection,
        price: float,
        atr: float,
        aggregations: dict[str, float],
    ) -> tuple[float, float, float]:
        risk_stop_offset = aggregations.get("risk_stop_offset", 0.0)
        risk_take_profit_offset = aggregations.get("risk_take_profit_offset", 0.0)
        entry_adjustment = aggregations.get("entry_adjustment", price)

        stop_distance = self._compute_stop_distance(price, atr, risk_stop_offset)
        take_profit_distance = self._compute_take_profit_distance(price, stop_distance, risk_take_profit_offset)

        entry_price = round(float(entry_adjustment or price), 4)
        if direction == RecommendationDirection.LONG:
            stop_loss = round(entry_price - stop_distance, 4)
            take_profit = round(entry_price + take_profit_distance, 4)
        else:
            stop_loss = round(entry_price + stop_distance, 4)
            take_profit = round(entry_price - take_profit_distance, 4)
        return entry_price, stop_loss, take_profit

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
