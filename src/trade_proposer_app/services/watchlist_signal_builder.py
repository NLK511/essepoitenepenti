from __future__ import annotations

from typing import Any

from trade_proposer_app.domain.models import RunOutput, TickerSignalSnapshot, Watchlist


class WatchlistSignalBuilder:
    """Build ticker signal snapshots for watchlist orchestration."""

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def build_signal_snapshot(
        self,
        watchlist: Watchlist,
        candidate: Any,
        *,
        deep_output: RunOutput | None,
        job_id: int | None,
        run_id: int | None,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None = None,
        deep_error: str | None = None,
    ) -> TickerSignalSnapshot:
        o = self._orchestration
        analysis = o._analysis_payload(deep_output or candidate.raw_output)
        deep_recommendation = deep_output.recommendation if deep_output is not None else None
        technical_score = round(
            float(
                deep_recommendation.confidence
                if deep_recommendation is not None
                else (candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else candidate.confidence_percent)
            ),
            2,
        )
        ticker_sentiment_score = o._sentiment_score_to_percent(o._pluck(analysis, "sentiment", "ticker", "score"))
        macro_exposure_score = o._sentiment_score_to_percent(o._pluck(analysis, "sentiment", "macro", "score"))
        industry_alignment_score = o._sentiment_score_to_percent(o._pluck(analysis, "sentiment", "industry", "score"))
        expected_move_score = o._expected_move_score(deep_recommendation)
        execution_quality_score = o._execution_quality_score(deep_recommendation)
        warnings = self._warnings(watchlist, candidate, deep_output=deep_output, deep_error=deep_error)
        transmission = self._transmission_fields(
            analysis,
            watchlist,
            macro_exposure_score=macro_exposure_score,
            industry_alignment_score=industry_alignment_score,
        )
        transmission_alignment_score = transmission["transmission_alignment_score"]
        transmission_bias = transmission["transmission_bias"]
        primary_drivers = transmission["primary_drivers"]
        primary_driver_details = transmission["primary_driver_details"]
        expected_transmission_window = transmission["expected_transmission_window"]
        expected_transmission_window_detail = transmission["expected_transmission_window_detail"]
        market_intelligence = transmission["market_intelligence"]
        market_intelligence_summary = transmission["market_intelligence_summary"]
        conflict_flags = transmission["conflict_flags"]
        conflict_flag_details = transmission["conflict_flag_details"]
        transmission_tags = transmission["transmission_tags"]
        transmission_tag_details = transmission["transmission_tag_details"]
        industry_exposure_channels = transmission["industry_exposure_channels"]
        industry_exposure_channel_details = transmission["industry_exposure_channel_details"]
        ticker_exposure_channels = transmission["ticker_exposure_channels"]
        ticker_exposure_channel_details = transmission["ticker_exposure_channel_details"]
        transmission_effect = transmission["transmission_effect"]
        base_confidence = round(float(deep_recommendation.confidence if deep_recommendation is not None else candidate.confidence_percent), 2)
        adjusted_confidence = round(max(0.0, min(95.0, base_confidence + transmission_effect)), 2)
        return TickerSignalSnapshot(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            status="degraded" if warnings else "ok",
            direction=(o._normalize_direction(deep_recommendation.direction) if deep_recommendation is not None else candidate.direction),
            swing_probability_percent=adjusted_confidence,
            confidence_percent=adjusted_confidence,
            attention_score=round(candidate.attention_score, 2),
            macro_exposure_score=macro_exposure_score,
            industry_alignment_score=industry_alignment_score,
            ticker_sentiment_score=ticker_sentiment_score,
            technical_setup_score=technical_score,
            catalyst_score=o._catalyst_score(analysis),
            expected_move_score=expected_move_score,
            execution_quality_score=execution_quality_score,
            warnings=list(dict.fromkeys(warnings)),
            missing_inputs=[],
            source_breakdown=self._source_breakdown(candidate, analysis, deep_output=deep_output, transmission=transmission, base_confidence=base_confidence),
            diagnostics=self._diagnostics_payload(
                candidate,
                analysis,
                shortlisted=shortlisted,
                shortlist_rank=shortlist_rank,
                shortlist_decision=shortlist_decision,
                deep_error=deep_error,
                transmission=transmission,
                base_confidence=base_confidence,
            ),
            job_id=job_id,
            run_id=run_id,
        )

    def _source_breakdown(
        self,
        candidate: Any,
        analysis: dict[str, Any],
        *,
        deep_output: RunOutput | None,
        transmission: dict[str, Any],
        base_confidence: float,
    ) -> dict[str, Any]:
        o = self._orchestration
        return {
            "cheap_scan_summary": candidate.indicator_summary,
            "cheap_scan_model": candidate.cheap_scan_signal.diagnostics.get("model") if candidate.cheap_scan_signal is not None else None,
            "cheap_scan_price_history": candidate.cheap_scan_signal.diagnostics.get("price_history") if candidate.cheap_scan_signal is not None else None,
            "deep_analysis_available": deep_output is not None,
            "deep_analysis_model": o._pluck(analysis, "ticker_deep_analysis", "model"),
            "deep_analysis_price_history": o._pluck(analysis, "ticker_deep_analysis", "price_history"),
            "summary_method": getattr(deep_output.diagnostics, "summary_method", None) if deep_output is not None else None,
            "transmission_bias": transmission["transmission_bias"],
            "transmission_bias_detail": o._transmission_bias_detail(transmission["transmission_bias"]),
            "transmission_tags": transmission["transmission_tags"],
            "transmission_tag_details": transmission["transmission_tag_details"],
            "primary_drivers": transmission["primary_drivers"],
            "primary_driver_details": transmission["primary_driver_details"],
            "industry_exposure_channels": transmission["industry_exposure_channels"],
            "industry_exposure_channel_details": transmission["industry_exposure_channel_details"],
            "ticker_exposure_channels": transmission["ticker_exposure_channels"],
            "ticker_exposure_channel_details": transmission["ticker_exposure_channel_details"],
            "expected_transmission_window": transmission["expected_transmission_window"],
            "expected_transmission_window_detail": transmission["expected_transmission_window_detail"],
            "market_intelligence": transmission["market_intelligence"],
            "market_intelligence_summary": transmission["market_intelligence_summary"],
            **self._fundamental_payload(analysis),
            "conflict_flags": transmission["conflict_flags"],
            "conflict_flag_details": transmission["conflict_flag_details"],
            "base_confidence_percent": base_confidence,
            "transmission_confidence_adjustment": transmission["transmission_effect"],
        }

    def _diagnostics_payload(
        self,
        candidate: Any,
        analysis: dict[str, Any],
        *,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None,
        deep_error: str | None,
        transmission: dict[str, Any],
        base_confidence: float,
    ) -> dict[str, Any]:
        o = self._orchestration
        return {
            "mode": "deep_analysis" if shortlisted else "cheap_scan_only",
            "shortlisted": shortlisted,
            "shortlist_rank": shortlist_rank,
            "shortlist_reasons": list(shortlist_decision.get("reasons", [])) if isinstance(shortlist_decision, dict) and isinstance(shortlist_decision.get("reasons"), list) else [],
            "shortlist_reason_details": list(shortlist_decision.get("reason_details", [])) if isinstance(shortlist_decision, dict) and isinstance(shortlist_decision.get("reason_details"), list) else [],
            "shortlist_eligible": bool(shortlist_decision.get("eligible")) if isinstance(shortlist_decision, dict) and shortlist_decision.get("eligible") is not None else shortlisted,
            "selection_lane": shortlist_decision.get("selection_lane") if isinstance(shortlist_decision, dict) else None,
            "selection_lane_label": shortlist_decision.get("selection_lane_label") if isinstance(shortlist_decision, dict) else None,
            "cheap_scan_confidence_percent": candidate.confidence_percent,
            "cheap_scan_directional_score": candidate.cheap_scan_signal.directional_score if candidate.cheap_scan_signal is not None else None,
            "cheap_scan_component_scores": self._cheap_scan_component_scores(candidate),
            "cheap_scan_price_history": candidate.cheap_scan_signal.diagnostics.get("price_history") if candidate.cheap_scan_signal is not None else None,
            "deep_analysis_error": deep_error,
            "deep_analysis_price_history": o._pluck(analysis, "ticker_deep_analysis", "price_history"),
            "base_confidence_percent": base_confidence,
            "transmission_confidence_adjustment": transmission["transmission_effect"],
            "transmission_alignment_score": transmission["transmission_alignment_score"],
            "transmission_bias": transmission["transmission_bias"],
            "transmission_bias_detail": o._transmission_bias_detail(transmission["transmission_bias"]),
            "transmission_tags": transmission["transmission_tags"],
            "transmission_tag_details": transmission["transmission_tag_details"],
            "primary_drivers": transmission["primary_drivers"],
            "primary_driver_details": transmission["primary_driver_details"],
            "market_intelligence": transmission["market_intelligence"],
            "market_intelligence_summary": transmission["market_intelligence_summary"],
            **self._fundamental_payload(analysis),
            "industry_exposure_channels": transmission["industry_exposure_channels"],
            "industry_exposure_channel_details": transmission["industry_exposure_channel_details"],
            "ticker_exposure_channels": transmission["ticker_exposure_channels"],
            "ticker_exposure_channel_details": transmission["ticker_exposure_channel_details"],
            "expected_transmission_window": transmission["expected_transmission_window"],
            "expected_transmission_window_detail": transmission["expected_transmission_window_detail"],
            "conflict_flags": transmission["conflict_flags"],
            "conflict_flag_details": transmission["conflict_flag_details"],
        }

    def _fundamental_payload(self, analysis: dict[str, Any]) -> dict[str, Any]:
        o = self._orchestration
        snapshot = o._pluck(analysis, "ticker_deep_analysis", "fundamental_snapshot") or o._pluck(analysis, "fundamental_snapshot") or {}
        buckets = o._pluck(analysis, "ticker_deep_analysis", "fundamental_feature_buckets") or o._pluck(analysis, "fundamental_feature_buckets") or {}
        coverage = o._pluck(analysis, "ticker_deep_analysis", "fundamental_coverage_status")
        valuation_context = (
            o._pluck(analysis, "ticker_deep_analysis", "fundamental_valuation_context")
            or o._pluck(analysis, "fundamental_valuation_context")
            or {}
        )
        if coverage is None and isinstance(snapshot, dict):
            coverage = snapshot.get("coverage_status")
        return {
            "fundamental_snapshot": snapshot if isinstance(snapshot, dict) else {},
            "fundamental_feature_buckets": buckets if isinstance(buckets, dict) else {},
            "fundamental_valuation_context": valuation_context if isinstance(valuation_context, dict) else {},
            "fundamental_coverage_status": coverage,
        }

    @staticmethod
    def _cheap_scan_component_scores(candidate: Any) -> dict[str, object]:
        return {
            "trend_score": candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else None,
            "momentum_score": candidate.cheap_scan_signal.momentum_score if candidate.cheap_scan_signal is not None else None,
            "breakout_score": candidate.cheap_scan_signal.breakout_score if candidate.cheap_scan_signal is not None else None,
            "volatility_score": candidate.cheap_scan_signal.volatility_score if candidate.cheap_scan_signal is not None else None,
            "liquidity_score": candidate.cheap_scan_signal.liquidity_score if candidate.cheap_scan_signal is not None else None,
        }

    def _warnings(self, watchlist: Watchlist, candidate: Any, *, deep_output: RunOutput | None, deep_error: str | None) -> list[str]:
        warnings = list(candidate.warnings)
        if deep_output is not None:
            warnings.extend(deep_output.diagnostics.warnings)
        if candidate.direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
        if deep_error:
            warnings.append(deep_error)
        return warnings

    def _transmission_fields(
        self,
        analysis: dict[str, Any],
        watchlist: Watchlist,
        *,
        macro_exposure_score: float,
        industry_alignment_score: float,
    ) -> dict[str, Any]:
        o = self._orchestration
        alignment_score = o._transmission_alignment_score(analysis)
        bias = o._transmission_bias(analysis)
        if bias == "unknown":
            alignment_score = round((macro_exposure_score * 0.45) + (industry_alignment_score * 0.55), 2)
            bias = o._bias_from_alignment(alignment_score)
        primary_drivers = self._primary_drivers(analysis, bias)
        conflict_flags = self._list_field(analysis, "conflict_flags")
        transmission_tags = self._list_field(analysis, "transmission_tags")
        industry_channels = self._list_field(analysis, "industry_exposure_channels")
        ticker_channels = self._list_field(analysis, "ticker_exposure_channels")
        expected_window = o._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "expected_transmission_window") or o._fallback_transmission_window_placeholder(watchlist.default_horizon)
        return {
            "transmission_alignment_score": alignment_score,
            "transmission_bias": bias,
            "primary_drivers": primary_drivers,
            "primary_driver_details": self._detail_field(analysis, "primary_driver_details", primary_drivers),
            "expected_transmission_window": expected_window,
            "expected_transmission_window_detail": o._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "expected_transmission_window_detail") or o._transmission_window_detail(expected_window),
            "market_intelligence": o._pluck(analysis, "ticker_deep_analysis", "market_intelligence") or o._pluck(analysis, "market_intelligence") or {},
            "market_intelligence_summary": o._pluck(analysis, "ticker_deep_analysis", "market_intelligence_summary") or o._pluck(analysis, "market_intelligence_summary"),
            "conflict_flags": conflict_flags,
            "conflict_flag_details": self._detail_field(analysis, "conflict_flag_details", conflict_flags),
            "transmission_tags": transmission_tags,
            "transmission_tag_details": self._detail_field(analysis, "transmission_tag_details", transmission_tags),
            "industry_exposure_channels": industry_channels,
            "industry_exposure_channel_details": self._channel_detail_field(analysis, "industry_exposure_channel_details", industry_channels),
            "ticker_exposure_channels": ticker_channels,
            "ticker_exposure_channel_details": self._channel_detail_field(analysis, "ticker_exposure_channel_details", ticker_channels),
            "transmission_effect": o._transmission_confidence_adjustment(analysis, transmission_bias=bias, alignment_score=alignment_score),
        }

    def _primary_drivers(self, analysis: dict[str, Any], transmission_bias: str) -> list[object]:
        o = self._orchestration
        value = self._list_field(analysis, "primary_drivers")
        if value:
            return value
        return [
            item for item in [
                "industry_context_support" if transmission_bias != "headwind" else "industry_context_headwind",
                "macro_context_support" if transmission_bias != "headwind" else "macro_context_headwind",
                "fresh_catalyst_pressure" if o._catalyst_score(analysis) >= 45.0 else None,
            ] if isinstance(item, str)
        ]

    def _list_field(self, analysis: dict[str, Any], key: str) -> list[object]:
        value = self._orchestration._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", key) or []
        return value if isinstance(value, list) else []

    def _detail_field(self, analysis: dict[str, Any], key: str, fallback_values: list[object]) -> list[object]:
        value = self._list_field(analysis, key)
        return value or self._orchestration._detail_fallback(fallback_values)

    def _channel_detail_field(self, analysis: dict[str, Any], key: str, fallback_values: list[object]) -> list[object]:
        value = self._list_field(analysis, key)
        return value or self._orchestration._channel_detail_fallback(fallback_values)
