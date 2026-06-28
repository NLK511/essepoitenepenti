from __future__ import annotations

from typing import Any

from trade_proposer_app.domain.models import TickerSignalSnapshot


class WatchlistTransmissionService:
    """Build transmission and signal-breakdown payloads for watchlist plans."""

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def __getattr__(self, name: str) -> Any:
        return getattr(self._orchestration, name)

    def transmission_confidence_adjustment(
        self,
        analysis: dict[str, Any],
        *,
        transmission_bias: str,
        alignment_score: float,
    ) -> float:
        transmission = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis")
        if not isinstance(transmission, dict):
            return 0.0
        contradiction_count = int(transmission.get("contradiction_count", 0) or 0) if self._is_number(transmission.get("contradiction_count")) else 0
        context_strength = float(transmission.get("context_strength_percent", 0.0) or 0.0) if self._is_number(transmission.get("context_strength_percent")) else 0.0
        event_relevance = float(transmission.get("context_event_relevance_percent", 0.0) or 0.0) if self._is_number(transmission.get("context_event_relevance_percent")) else 0.0
        decay_state = self._string_value(transmission.get("decay_state"), default="unknown")
        adjustment = 0.0
        if transmission_bias == "tailwind":
            adjustment += min(6.0, max(0.0, (alignment_score - 55.0) * 0.12))
        elif transmission_bias == "headwind":
            adjustment -= min(8.0, max(0.0, (55.0 - alignment_score) * 0.16))
        adjustment += min(3.0, context_strength / 40.0)
        adjustment += min(2.0, event_relevance / 50.0)
        if decay_state == "fresh":
            adjustment += 1.5 if transmission_bias == "tailwind" else -1.5
        elif decay_state == "fading":
            adjustment -= 1.5
        adjustment -= min(6.0, contradiction_count * 2.0)
        if "market_intelligence_alignment_percent" in transmission and self._is_number(transmission.get("market_intelligence_alignment_percent")):
            market_intelligence_alignment = float(transmission.get("market_intelligence_alignment_percent", 0.0) or 0.0)
            market_intelligence_adjustment = max(-3.0, min(3.0, (market_intelligence_alignment - 50.0) * 0.04))
            adjustment += market_intelligence_adjustment
        quality_status = self.trade_context_quality_status(
            {
                "context_quality_status": transmission.get("context_quality_status"),
                "macro_context_quality_status": transmission.get("macro_context_quality_status"),
                "industry_context_quality_status": transmission.get("industry_context_quality_status"),
            }
        )
        positive_boost_allowed = transmission_bias == "tailwind" and contradiction_count == 0 and quality_status == "usable"
        if adjustment > 0.0 and not positive_boost_allowed:
            adjustment = -min(6.0, contradiction_count * 2.0) if contradiction_count > 0 else 0.0
        return round(max(-10.0, min(2.0, adjustment)), 2)

    def signal_breakdown(
        self,
        signal: TickerSignalSnapshot,
        *,
        setup_family: str,
        confidence_components: dict[str, float],
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
        intended_action: str | None = None,
        shortlisted: bool | None = None,
        shortlist_rank: int | None = None,
        deep_analysis_confidence_percent: float | None = None,
    ) -> dict[str, object]:
        calibration = calibration_review or {}
        raw_plan_confidence = calibration.get("raw_confidence_percent") if isinstance(calibration.get("raw_confidence_percent"), (int, float)) else signal.confidence_percent
        calibrated_confidence = calibration.get("calibrated_confidence_percent") if isinstance(calibration.get("calibrated_confidence_percent"), (int, float)) else raw_plan_confidence
        cheap_scan_component_scores = signal.diagnostics.get("cheap_scan_component_scores") if isinstance(signal.diagnostics.get("cheap_scan_component_scores"), dict) else {}
        base_confidence_threshold = float(getattr(self._orchestration, "confidence_threshold", 60.0) or 60.0)
        signal_gating = getattr(self._orchestration, "signal_gating_tuning_config", {})
        threshold_offset = float(signal_gating.get("threshold_offset", 0.0) or 0.0) if isinstance(signal_gating, dict) else 0.0
        upstream_effective_threshold = (
            float(calibration.get("effective_confidence_threshold"))
            if isinstance(calibration.get("effective_confidence_threshold"), (int, float))
            else max(0.0, min(100.0, base_confidence_threshold + threshold_offset))
        )
        policy_action_threshold = float(getattr(self._orchestration, "action_confidence_threshold", upstream_effective_threshold) or 0.0)
        try:
            actionable_floor = float(
                self._orchestration._plan_generation_tuning_value("global.actionable_confidence_floor_percent", 60.0)
            )
        except AttributeError:
            actionable_floor = 60.0
        effective_action_threshold = max(min(upstream_effective_threshold, policy_action_threshold), actionable_floor)
        decision_thresholds = {
            "base_confidence_threshold_percent": round(base_confidence_threshold, 2),
            "signal_gating_threshold_offset_percent": round(threshold_offset, 2),
            "upstream_effective_confidence_threshold_percent": round(upstream_effective_threshold, 2),
            "policy_action_confidence_threshold_percent": round(policy_action_threshold, 2),
            "actionable_confidence_floor_percent": round(actionable_floor, 2),
            "effective_action_threshold_percent": round(effective_action_threshold, 2),
        }
        payload = {
            "attention_score": signal.attention_score,
            "macro_exposure_score": signal.macro_exposure_score,
            "industry_alignment_score": signal.industry_alignment_score,
            "ticker_sentiment_score": signal.ticker_sentiment_score,
            "technical_setup_score": signal.technical_setup_score,
            "catalyst_score": signal.catalyst_score,
            "expected_move_score": signal.expected_move_score,
            "execution_quality_score": signal.execution_quality_score,
            "setup_family": setup_family,
            "confidence_components": confidence_components,
            "raw_confidence_percent": round(float(raw_plan_confidence), 2),
            "raw_plan_confidence_percent": round(float(raw_plan_confidence), 2),
            "cheap_scan_confidence_percent": round(float(signal.confidence_percent), 2),
            "cheap_scan_volatility_score": round(float(cheap_scan_component_scores.get("volatility_score", 50.0) or 50.0), 2),
            "deep_analysis_confidence_percent": round(float(deep_analysis_confidence_percent), 2) if deep_analysis_confidence_percent is not None else None,
            "calibrated_confidence_percent": round(float(calibrated_confidence), 2),
            "confidence_bucket": self._confidence_bucket(float(calibrated_confidence)),
            "decision_thresholds": decision_thresholds,
            "effective_action_threshold_percent": decision_thresholds["effective_action_threshold_percent"],
            "calibration_review": calibration,
            "transmission_summary": transmission_summary or {},
            "fundamental_snapshot": signal.diagnostics.get("fundamental_snapshot", {}),
            "fundamental_feature_buckets": signal.diagnostics.get("fundamental_feature_buckets", {}),
            "fundamental_valuation_context": signal.diagnostics.get(
                "fundamental_valuation_context", {}
            ),
            "fundamental_coverage_status": signal.diagnostics.get("fundamental_coverage_status"),
            "mode": signal.diagnostics.get("mode"),
            "shortlisted": shortlisted,
            "shortlist_rank": shortlist_rank,
            "cheap_scan_price_history": signal.diagnostics.get("cheap_scan_price_history"),
            "deep_analysis_price_history": signal.diagnostics.get("deep_analysis_price_history"),
        }
        if intended_action in {"long", "short"}:
            payload["intended_action"] = intended_action
        return payload

    @staticmethod
    def should_block_for_transmission_contradiction(
        transmission_summary: dict[str, object],
        calibrated_confidence: float,
        effective_threshold: float,
    ) -> bool:
        contradiction_count = int(transmission_summary.get("contradiction_count", 0) or 0)
        if contradiction_count <= 0:
            return False
        conflict_flags = transmission_summary.get("conflict_flags")
        normalized_flags = {
            str(flag).strip().lower()
            for flag in conflict_flags
            if str(flag).strip()
        } if isinstance(conflict_flags, list) else set()
        severe_flags = {"directional_conflict", "technical_context_conflict"}
        if not normalized_flags.intersection(severe_flags):
            return False
        return calibrated_confidence < min(95.0, effective_threshold + 4.0)

    @staticmethod
    def trade_context_quality_status(transmission_summary: dict[str, object]) -> str:
        overall_status = str(transmission_summary.get("context_quality_status", "")).strip().lower()
        macro_status = str(transmission_summary.get("macro_context_quality_status", "")).strip().lower()
        industry_status = str(transmission_summary.get("industry_context_quality_status", "")).strip().lower()
        component_statuses = [status for status in (macro_status, industry_status) if status]
        if macro_status == "blocked" and industry_status == "blocked":
            return "blocked"
        if overall_status == "blocked" and component_statuses:
            return "degraded"
        if overall_status == "degraded" or "degraded" in component_statuses:
            return "degraded"
        if overall_status == "usable" or "usable" in component_statuses:
            return "usable"
        return overall_status or "unknown"

    def plan_confidence_components(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: Any,
    ) -> dict[str, float]:
        explicit = self._pluck(analysis, "ticker_deep_analysis", "confidence_components")
        if isinstance(explicit, dict) and explicit:
            normalized = {str(key): round(float(value), 2) for key, value in explicit.items() if self._is_number(value)}
            normalized.setdefault("transmission_quality", round(signal.diagnostics.get("transmission_alignment_score", 0.0) if self._is_number(signal.diagnostics.get("transmission_alignment_score")) else 0.0, 2))
            normalized.setdefault("market_intelligence_confidence", round(max(0.0, min(100.0, signal.catalyst_score * 0.35)), 2))
            return normalized
        return {
            "context_confidence": round((signal.macro_exposure_score * 0.45) + (signal.industry_alignment_score * 0.55), 2),
            "directional_confidence": round(max(signal.ticker_sentiment_score, candidate.confidence_percent), 2),
            "catalyst_confidence": round(signal.catalyst_score, 2),
            "market_intelligence_confidence": round(max(0.0, min(100.0, signal.catalyst_score * 0.35)), 2),
            "technical_clarity": round(signal.technical_setup_score, 2),
            "execution_clarity": round(signal.execution_quality_score if signal.execution_quality_score > 0 else signal.attention_score, 2),
            "transmission_quality": round(signal.diagnostics.get("transmission_alignment_score", 0.0) if self._is_number(signal.diagnostics.get("transmission_alignment_score")) else 0.0, 2),
            "data_quality_cap": round(max(25.0, 100.0 - (len(signal.warnings) * 10.0)), 2),
        }

    def transmission_summary(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: Any,
    ) -> dict[str, object]:
        explicit = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis")
        if isinstance(explicit, dict) and explicit:
            bias = self._transmission_bias(analysis)
            alignment_percent = round(float(explicit.get("alignment_percent", 0.0)), 2) if self._is_number(explicit.get("alignment_percent")) else 0.0
            transmission_tags = explicit.get("transmission_tags", []) if isinstance(explicit.get("transmission_tags"), list) else []
            transmission_tag_details = explicit.get("transmission_tag_details", []) if isinstance(explicit.get("transmission_tag_details"), list) else []
            primary_drivers = explicit.get("primary_drivers", []) if isinstance(explicit.get("primary_drivers"), list) else []
            primary_driver_details = explicit.get("primary_driver_details", []) if isinstance(explicit.get("primary_driver_details"), list) else []
            industry_exposure_channels = explicit.get("industry_exposure_channels", []) if isinstance(explicit.get("industry_exposure_channels"), list) else []
            industry_exposure_channel_details = explicit.get("industry_exposure_channel_details", []) if isinstance(explicit.get("industry_exposure_channel_details"), list) else []
            ticker_exposure_channels = explicit.get("ticker_exposure_channels", []) if isinstance(explicit.get("ticker_exposure_channels"), list) else []
            ticker_exposure_channel_details = explicit.get("ticker_exposure_channel_details", []) if isinstance(explicit.get("ticker_exposure_channel_details"), list) else []
            matched_ticker_relationships = explicit.get("matched_ticker_relationships", []) if isinstance(explicit.get("matched_ticker_relationships"), list) else []
            ontology_context = explicit.get("ontology_context", {}) if isinstance(explicit.get("ontology_context"), dict) else {}
            return {
                "alignment_percent": alignment_percent,
                "pre_ontology_alignment_percent": round(float(explicit.get("pre_ontology_alignment_percent", alignment_percent)), 2) if self._is_number(explicit.get("pre_ontology_alignment_percent")) else alignment_percent,
                "ontology_context": ontology_context,
                "context_bias": bias,
                "transmission_bias": bias,
                "transmission_bias_detail": self._transmission_bias_detail(bias),
                "catalyst_intensity_percent": round(float(explicit.get("catalyst_intensity_percent", 0.0)), 2) if self._is_number(explicit.get("catalyst_intensity_percent")) else signal.catalyst_score,
                "market_intelligence_support_percent": round(float(explicit.get("market_intelligence_support_percent", 0.0)), 2) if self._is_number(explicit.get("market_intelligence_support_percent")) else 0.0,
                "context_strength_percent": round(float(explicit.get("context_strength_percent", 0.0)), 2) if self._is_number(explicit.get("context_strength_percent")) else 0.0,
                "context_event_relevance_percent": round(float(explicit.get("context_event_relevance_percent", 0.0)), 2) if self._is_number(explicit.get("context_event_relevance_percent")) else 0.0,
                "market_intelligence_summary": explicit.get("market_intelligence_summary") if isinstance(explicit.get("market_intelligence_summary"), str) else None,
                "market_intelligence_bias": explicit.get("market_intelligence_bias") if isinstance(explicit.get("market_intelligence_bias"), str) else None,
                "market_intelligence_alignment_percent": round(float(explicit.get("market_intelligence_alignment_percent", 0.0)), 2) if self._is_number(explicit.get("market_intelligence_alignment_percent")) else 0.0,
                "market_intelligence_confidence_contribution": explicit.get("market_intelligence_confidence_contribution", {}) if isinstance(explicit.get("market_intelligence_confidence_contribution"), dict) else {},
                "market_intelligence_conflict_flags": explicit.get("market_intelligence_conflict_flags", []) if isinstance(explicit.get("market_intelligence_conflict_flags"), list) else [],
                "market_intelligence_warnings": explicit.get("market_intelligence_warnings", []) if isinstance(explicit.get("market_intelligence_warnings"), list) else [],
                "market_intelligence": explicit.get("market_intelligence", {}) if isinstance(explicit.get("market_intelligence"), dict) else {},
                "contradiction_count": int(float(explicit.get("contradiction_count", 0.0))) if self._is_number(explicit.get("contradiction_count")) else 0,
                "context_quality_status": str(explicit.get("context_quality_status") or "unknown"),
                "trade_context_quality_status": self.trade_context_quality_status({
                    "context_quality_status": explicit.get("context_quality_status"),
                    "macro_context_quality_status": explicit.get("macro_context_quality_status"),
                    "industry_context_quality_status": explicit.get("industry_context_quality_status"),
                }),
                "macro_context_quality_status": explicit.get("macro_context_quality_status"),
                "industry_context_quality_status": explicit.get("industry_context_quality_status"),
                "macro_context_quality_score": explicit.get("macro_context_quality_score"),
                "industry_context_quality_score": explicit.get("industry_context_quality_score"),
                "transmission_tags": transmission_tags,
                "transmission_tag_details": transmission_tag_details or self._detail_fallback(transmission_tags),
                "primary_drivers": primary_drivers,
                "primary_driver_details": primary_driver_details or self._detail_fallback(primary_drivers),
                "industry_exposure_channels": industry_exposure_channels,
                "industry_exposure_channel_details": industry_exposure_channel_details or self._channel_detail_fallback(industry_exposure_channels),
                "ticker_exposure_channels": ticker_exposure_channels,
                "ticker_exposure_channel_details": ticker_exposure_channel_details or self._channel_detail_fallback(ticker_exposure_channels),
                "ticker_relationship_edges": explicit.get("ticker_relationship_edges", []) if isinstance(explicit.get("ticker_relationship_edges"), list) else [],
                "matched_ticker_relationships": matched_ticker_relationships,
                "matched_ticker_relationship_details": explicit.get("matched_ticker_relationship_details", []) if isinstance(explicit.get("matched_ticker_relationship_details"), list) else self._relationship_detail_fallback(matched_ticker_relationships),
                "expected_transmission_window": self._string_value(explicit.get("expected_transmission_window"), default=self._fallback_transmission_window(signal)),
                "expected_transmission_window_detail": explicit.get("expected_transmission_window_detail") if isinstance(explicit.get("expected_transmission_window_detail"), dict) else self._transmission_window_detail(self._string_value(explicit.get("expected_transmission_window"), default=self._fallback_transmission_window(signal))),
                "conflict_flags": explicit.get("conflict_flags", []) if isinstance(explicit.get("conflict_flags"), list) else [],
                "conflict_flag_details": explicit.get("conflict_flag_details", []) if isinstance(explicit.get("conflict_flag_details"), list) else self._detail_fallback(explicit.get("conflict_flags", [])),
                "decay_state": self._string_value(explicit.get("decay_state"), default=self._fallback_decay_state(signal)),
                "transmission_confidence_adjustment": round(float(signal.diagnostics.get("transmission_confidence_adjustment", 0.0)), 2) if self._is_number(signal.diagnostics.get("transmission_confidence_adjustment")) else 0.0,
                "lane_hint": "event" if bias == "tailwind" and signal.catalyst_score >= 65.0 else "technical",
            }
        context_alignment = round((signal.macro_exposure_score * 0.45) + (signal.industry_alignment_score * 0.55), 2)
        if context_alignment >= 62.0:
            bias = "tailwind"
        elif context_alignment <= 42.0:
            bias = "headwind"
        else:
            bias = "mixed"
        return {
            "alignment_percent": context_alignment,
            "context_bias": bias,
            "transmission_bias": bias,
            "transmission_bias_detail": self._transmission_bias_detail(bias),
            "catalyst_intensity_percent": signal.catalyst_score,
            "market_intelligence_summary": None,
            "market_intelligence_bias": None,
            "market_intelligence_alignment_percent": 0.0,
            "market_intelligence_confidence_contribution": {},
            "market_intelligence_conflict_flags": [],
            "market_intelligence_warnings": [],
            "market_intelligence": {},
            "trade_context_quality_status": self.trade_context_quality_status({
                "context_quality_status": signal.diagnostics.get("context_quality_status"),
                "macro_context_quality_status": signal.diagnostics.get("macro_context_quality_status"),
                "industry_context_quality_status": signal.diagnostics.get("industry_context_quality_status"),
            }),
            "macro_context_quality_status": signal.diagnostics.get("macro_context_quality_status"),
            "industry_context_quality_status": signal.diagnostics.get("industry_context_quality_status"),
            "context_strength_percent": round((signal.macro_exposure_score * 0.45) + (signal.industry_alignment_score * 0.55), 2),
            "context_event_relevance_percent": round((signal.macro_exposure_score * 0.35) + (signal.industry_alignment_score * 0.35) + (signal.catalyst_score * 0.3), 2),
            "contradiction_count": 1 if "context_contradiction" in self._fallback_conflict_flags(signal, candidate, bias) else 0,
            "transmission_tags": [],
            "transmission_tag_details": [],
            "primary_drivers": self._fallback_primary_drivers(signal, candidate, bias),
            "primary_driver_details": self._detail_fallback(self._fallback_primary_drivers(signal, candidate, bias)),
            "industry_exposure_channels": self._fallback_industry_exposure_channels(signal),
            "industry_exposure_channel_details": self._channel_detail_fallback(self._fallback_industry_exposure_channels(signal)),
            "ticker_exposure_channels": self._fallback_ticker_exposure_channels(signal, candidate),
            "ticker_exposure_channel_details": self._channel_detail_fallback(self._fallback_ticker_exposure_channels(signal, candidate)),
            "ticker_relationship_edges": [],
            "matched_ticker_relationships": [],
            "matched_ticker_relationship_details": [],
            "expected_transmission_window": self._fallback_transmission_window(signal),
            "expected_transmission_window_detail": self._transmission_window_detail(self._fallback_transmission_window(signal)),
            "conflict_flags": self._fallback_conflict_flags(signal, candidate, bias),
            "conflict_flag_details": self._detail_fallback(self._fallback_conflict_flags(signal, candidate, bias)),
            "decay_state": self._fallback_decay_state(signal),
            "transmission_confidence_adjustment": round(float(signal.diagnostics.get("transmission_confidence_adjustment", 0.0)), 2) if self._is_number(signal.diagnostics.get("transmission_confidence_adjustment")) else 0.0,
            "lane_hint": "event" if signal.catalyst_score >= 65.0 else "technical",
        }
