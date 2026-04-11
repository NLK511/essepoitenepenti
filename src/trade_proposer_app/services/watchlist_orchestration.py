from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import RecommendationDecisionSample, RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal, CheapScanSignalService
from trade_proposer_app.services.plan_generation_tuning_logic import family_adjusted_trade_levels
from trade_proposer_app.services.plan_generation_tuning_parameters import normalize_plan_generation_tuning_config


@dataclass
class _CheapScanCandidate:
    ticker: str
    direction: str
    confidence_percent: float
    attention_score: float
    warnings: list[str]
    indicator_summary: str
    cheap_scan_signal: CheapScanSignal | None = None
    raw_output: RunOutput | None = None
    error_message: str | None = None


class WatchlistOrchestrationService:
    def __init__(
        self,
        *,
        context_snapshots: ContextSnapshotRepository,
        recommendation_plans: RecommendationPlanRepository,
        cheap_scan_service: CheapScanSignalService,
        decision_samples: RecommendationDecisionSampleRepository | None = None,
        deep_analysis_service,
        confidence_threshold: float = 60.0,
        signal_gating_tuning_config: dict[str, float] | None = None,
        plan_generation_tuning_config: dict[str, float] | None = None,
        calibration_service: RecommendationPlanCalibrationService | None = None,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.context_snapshots = context_snapshots
        self.recommendation_plans = recommendation_plans
        self.decision_samples = decision_samples
        self.cheap_scan_service = cheap_scan_service
        self.deep_analysis_service = deep_analysis_service
        self.confidence_threshold = confidence_threshold
        self.signal_gating_tuning_config = self._normalize_signal_gating_tuning_config(signal_gating_tuning_config)
        self.plan_generation_tuning_config = normalize_plan_generation_tuning_config(plan_generation_tuning_config)
        self.calibration_service = calibration_service
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    @staticmethod
    def _normalize_signal_gating_tuning_config(signal_gating_tuning_config: dict[str, float] | None) -> dict[str, float]:
        defaults = {
            "threshold_offset": 0.0,
            "confidence_adjustment": 0.0,
            "near_miss_gap_cutoff": 0.0,
            "shortlist_aggressiveness": 0.0,
            "degraded_penalty": 0.0,
        }
        if not signal_gating_tuning_config:
            return defaults
        normalized = dict(defaults)
        for key, default in defaults.items():
            raw_value = signal_gating_tuning_config.get(key, default)
            try:
                normalized[key] = float(raw_value)
            except (TypeError, ValueError):
                normalized[key] = default
        return normalized

    def _signal_gating_tuning_value(self, key: str, default: float) -> float:
        try:
            return float(self.signal_gating_tuning_config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _plan_generation_tuning_value(self, key: str, default: float) -> float:
        try:
            return float(self.plan_generation_tuning_config.get(key, default))
        except (TypeError, ValueError):
            return default

    def execute(
        self,
        watchlist: Watchlist,
        tickers: list[str],
        *,
        job_id: int | None = None,
        run_id: int | None = None,
    ) -> dict[str, object]:
        normalized_tickers = [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
        if not normalized_tickers:
            raise ValueError("watchlist job has no effective tickers configured")

        calibration_summary = self._load_calibration_summary()
        candidates = [self._run_cheap_scan(ticker, watchlist.default_horizon) for ticker in normalized_tickers]
        shortlist_evaluation = self._evaluate_shortlist(watchlist, candidates)
        shortlist = shortlist_evaluation["shortlist"]
        shortlist_map = {ticker: rank for rank, ticker in enumerate(shortlist, start=1)}

        stored_signals: list[TickerSignalSnapshot] = []
        stored_plans: list[RecommendationPlan] = []
        ticker_generation: list[dict[str, object]] = []
        warnings_found = False

        for candidate in candidates:
            shortlist_rank = shortlist_map.get(candidate.ticker)
            if shortlist_rank is None:
                decision = self._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
                signal = self._build_signal_snapshot(
                    watchlist,
                    candidate,
                    deep_output=None,
                    job_id=job_id,
                    run_id=run_id,
                    shortlisted=False,
                    shortlist_rank=None,
                    shortlist_decision=decision,
                )
                stored_signal = self.context_snapshots.create_ticker_signal_snapshot(signal)
                stored_signals.append(stored_signal)
                plan = self._build_no_action_plan(
                    watchlist,
                    candidate,
                    stored_signal,
                    calibration_summary=calibration_summary,
                    job_id=job_id,
                    run_id=run_id,
                    reason="Ticker did not make the deep-analysis shortlist.",
                )
                stored_plan = self.recommendation_plans.create_plan(plan)
                self._record_decision_sample(
                    stored_plan,
                    candidate,
                    signal=stored_signal,
                    shortlisted=False,
                    shortlist_rank=None,
                    shortlist_decision=decision,
                )
                stored_plans.append(stored_plan)
                ticker_generation.append(
                    {
                        "ticker": candidate.ticker,
                        "status": "cheap_scan_only",
                        "shortlisted": False,
                        "attention_score": candidate.attention_score,
                        "shortlist_decision": decision,
                    }
                )
                if candidate.warnings or candidate.error_message:
                    warnings_found = True
                continue

            deep_output, deep_error = self._run_deep_analysis(candidate.ticker, watchlist.default_horizon)
            decision = self._shortlist_decision_for_ticker(shortlist_evaluation, candidate.ticker)
            signal = self._build_signal_snapshot(
                watchlist,
                candidate,
                deep_output=deep_output,
                job_id=job_id,
                run_id=run_id,
                shortlisted=True,
                shortlist_rank=shortlist_rank,
                shortlist_decision=decision,
                deep_error=deep_error,
            )
            stored_signal = self.context_snapshots.create_ticker_signal_snapshot(signal)
            stored_signals.append(stored_signal)
            plan = self._build_plan_from_signal(
                watchlist,
                candidate,
                stored_signal,
                deep_output=deep_output,
                deep_error=deep_error,
                calibration_summary=calibration_summary,
                job_id=job_id,
                run_id=run_id,
            )
            stored_plan = self.recommendation_plans.create_plan(plan)
            self._record_decision_sample(
                stored_plan,
                candidate,
                signal=stored_signal,
                shortlisted=True,
                shortlist_rank=shortlist_rank,
                shortlist_decision=decision,
            )
            stored_plans.append(stored_plan)
            ticker_generation.append(
                {
                    "ticker": candidate.ticker,
                    "status": "deep_analysis" if deep_output is not None and deep_error is None else "deep_analysis_failed",
                    "shortlisted": True,
                    "shortlist_rank": shortlist_rank,
                    "attention_score": candidate.attention_score,
                    "plan_action": stored_plan.action,
                    "shortlist_decision": decision,
                }
            )
            if candidate.warnings or deep_error or plan.warnings:
                warnings_found = True

        summary = {
            "mode": "watchlist_orchestration",
            "watchlist_id": watchlist.id,
            "watchlist_name": watchlist.name,
            "horizon": watchlist.default_horizon.value,
            "ticker_count": len(normalized_tickers),
            "cheap_scan_count": len(candidates),
            "shortlist_count": len(shortlist),
            "deep_analysis_count": len(shortlist),
            "ticker_signal_snapshot_count": len(stored_signals),
            "recommendation_plan_count": len(stored_plans),
            "actionable_plan_count": len([plan for plan in stored_plans if plan.action in {"long", "short"}]),
            "no_action_plan_count": len([plan for plan in stored_plans if plan.action == "no_action"]),
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_rejections": shortlist_evaluation["rejection_counts"],
            "shortlist_rejection_details": self._counted_shortlist_reason_details(shortlist_evaluation["rejection_counts"]),
            "calibration_enabled": calibration_summary is not None,
            "warnings_found": warnings_found,
        }
        artifact = {
            "mode": "watchlist_orchestration",
            "watchlist_id": watchlist.id,
            "shortlist": shortlist,
            "shortlist_rules": shortlist_evaluation["rules"],
            "shortlist_decisions": shortlist_evaluation["decisions"],
            "calibration_enabled": calibration_summary is not None,
            "ticker_signal_snapshot_ids": [item.id for item in stored_signals],
            "recommendation_plan_ids": [item.id for item in stored_plans],
        }
        return {
            "summary": summary,
            "artifact": artifact,
            "ticker_generation": ticker_generation,
            "warnings_found": warnings_found,
        }

    def _run_cheap_scan(self, ticker: str, horizon: StrategyHorizon) -> _CheapScanCandidate:
        try:
            signal = self.cheap_scan_service.score(ticker, horizon)
        except Exception as exc:
            return _CheapScanCandidate(
                ticker=ticker,
                direction="neutral",
                confidence_percent=0.0,
                attention_score=0.0,
                warnings=[str(exc)],
                indicator_summary="cheap scan failed",
                cheap_scan_signal=None,
                raw_output=None,
                error_message=str(exc),
            )
        return _CheapScanCandidate(
            ticker=ticker,
            direction=signal.directional_bias,
            confidence_percent=signal.confidence_percent,
            attention_score=signal.attention_score,
            warnings=list(signal.warnings),
            indicator_summary=signal.indicator_summary,
            cheap_scan_signal=signal,
            raw_output=None,
        )

    def _run_deep_analysis(self, ticker: str, horizon: StrategyHorizon) -> tuple[RunOutput | None, str | None]:
        try:
            if hasattr(self.deep_analysis_service, "analyze"):
                return self.deep_analysis_service.analyze(ticker, horizon=horizon), None
            return self.deep_analysis_service.generate(ticker), None
        except Exception as exc:
            return None, str(exc)

    def _select_shortlist(self, watchlist: Watchlist, candidates: list[_CheapScanCandidate]) -> list[str]:
        evaluation = self._evaluate_shortlist(watchlist, candidates)
        return list(evaluation["shortlist"])

    def _evaluate_shortlist(self, watchlist: Watchlist, candidates: list[_CheapScanCandidate]) -> dict[str, object]:
        if not candidates:
            return {
                "shortlist": [],
                "rules": {
                    "horizon": watchlist.default_horizon.value,
                    "watchlist_size": 0,
                    "allow_shorts": watchlist.allow_shorts,
                    "limit": 0,
                    "minimum_confidence_percent": 0.0,
                    "minimum_attention_score": 0.0,
                },
                "decisions": [],
                "rejection_counts": {},
            }
        ticker_count = len(candidates)
        limit = self._shortlist_limit(watchlist.default_horizon, ticker_count)
        minimum_confidence = self._minimum_shortlist_confidence(watchlist.default_horizon, ticker_count)
        minimum_attention = self._minimum_shortlist_attention(watchlist.default_horizon, ticker_count)
        catalyst_lane_limit = 1 if limit >= 2 else 0
        core_limit = max(0, limit - catalyst_lane_limit)
        ranked = sorted(
            candidates,
            key=lambda item: (
                0 if item.error_message else 1,
                0 if (item.direction == "short" and not watchlist.allow_shorts) else 1,
                item.attention_score,
                item.confidence_percent,
            ),
            reverse=True,
        )
        eligibility: dict[str, tuple[bool, list[str]]] = {}
        for candidate in ranked:
            reasons: list[str] = []
            eligible = True
            if candidate.error_message:
                reasons.append("cheap_scan_error")
                eligible = False
            if candidate.direction == "short" and not watchlist.allow_shorts:
                reasons.append("shorts_disabled")
                eligible = False
            if candidate.confidence_percent < minimum_confidence:
                reasons.append("below_confidence_threshold")
                eligible = False
            if candidate.attention_score < minimum_attention:
                reasons.append("below_attention_threshold")
                eligible = False
            eligibility[candidate.ticker] = (eligible, reasons)

        shortlist: list[str] = []
        selection_lane: dict[str, str] = {}
        for candidate in ranked:
            eligible, _ = eligibility[candidate.ticker]
            if eligible and len(shortlist) < core_limit:
                shortlist.append(candidate.ticker)
                selection_lane[candidate.ticker] = "technical"

        catalyst_threshold = self._minimum_catalyst_proxy_score(watchlist.default_horizon, ticker_count)
        catalyst_ranked = sorted(
            [candidate for candidate in ranked if candidate.ticker not in shortlist],
            key=lambda item: self._catalyst_shortlist_score(item),
            reverse=True,
        )
        for candidate in catalyst_ranked:
            if catalyst_lane_limit <= 0 or len(shortlist) >= limit:
                break
            eligible, reasons = eligibility[candidate.ticker]
            catalyst_score = self._catalyst_shortlist_score(candidate)
            relaxed_confidence_floor = max(40.0, minimum_confidence - 8.0)
            relaxed_attention_floor = max(55.0, minimum_attention)
            catalyst_eligible = (
                not candidate.error_message
                and not (candidate.direction == "short" and not watchlist.allow_shorts)
                and candidate.confidence_percent >= relaxed_confidence_floor
                and candidate.attention_score >= relaxed_attention_floor
                and catalyst_score >= catalyst_threshold
            )
            if candidate.ticker in shortlist:
                continue
            if catalyst_eligible and (eligible or "below_confidence_threshold" in reasons or "below_attention_threshold" in reasons):
                shortlist.append(candidate.ticker)
                selection_lane[candidate.ticker] = "catalyst"
                catalyst_lane_limit -= 1

        decisions: list[dict[str, object]] = []
        rejection_counts: dict[str, int] = {}
        for rank, candidate in enumerate(ranked, start=1):
            eligible, reasons = eligibility[candidate.ticker]
            shortlisted = candidate.ticker in shortlist
            if eligible and not shortlisted:
                reasons = [*reasons, "outside_shortlist_limit"]
            if not shortlisted and self._catalyst_shortlist_score(candidate) < catalyst_threshold:
                reasons = [*reasons, "below_catalyst_lane_threshold"]
            deduped_reasons = list(dict.fromkeys(reasons))
            for reason in deduped_reasons:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            lane = selection_lane.get(candidate.ticker)
            decisions.append(
                {
                    "ticker": candidate.ticker,
                    "rank": rank,
                    "direction": candidate.direction,
                    "confidence_percent": candidate.confidence_percent,
                    "attention_score": candidate.attention_score,
                    "catalyst_proxy_score": self._catalyst_shortlist_score(candidate),
                    "shortlisted": shortlisted,
                    "shortlist_rank": shortlist.index(candidate.ticker) + 1 if shortlisted else None,
                    "selection_lane": lane,
                    "selection_lane_label": self._shortlist_selection_lane_label(lane),
                    "reasons": deduped_reasons,
                    "reason_details": self._shortlist_reason_details(deduped_reasons),
                    "eligible": eligible,
                    "error_message": candidate.error_message,
                }
            )
        return {
            "shortlist": shortlist,
            "rules": {
                "horizon": watchlist.default_horizon.value,
                "watchlist_size": ticker_count,
                "allow_shorts": watchlist.allow_shorts,
                "limit": limit,
                "core_limit": core_limit,
                "catalyst_lane_limit": 1 if limit >= 2 else 0,
                "minimum_confidence_percent": minimum_confidence,
                "minimum_attention_score": minimum_attention,
                "minimum_catalyst_proxy_score": catalyst_threshold,
            },
            "decisions": decisions,
            "rejection_counts": rejection_counts,
        }

    @staticmethod
    def _shortlist_decision_for_ticker(evaluation: dict[str, object], ticker: str) -> dict[str, object] | None:
        decisions = evaluation.get("decisions")
        if not isinstance(decisions, list):
            return None
        for decision in decisions:
            if isinstance(decision, dict) and decision.get("ticker") == ticker:
                return decision
        return None

    def _build_signal_snapshot(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        *,
        deep_output: RunOutput | None,
        job_id: int | None,
        run_id: int | None,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None = None,
        deep_error: str | None = None,
    ) -> TickerSignalSnapshot:
        analysis = self._analysis_payload(deep_output or candidate.raw_output)
        deep_recommendation = deep_output.recommendation if deep_output is not None else None
        technical_score = round(
            float(
                deep_recommendation.confidence
                if deep_recommendation is not None
                else (candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else candidate.confidence_percent)
            ),
            2,
        )
        ticker_sentiment_score = self._sentiment_score_to_percent(self._pluck(analysis, "sentiment", "ticker", "score"))
        macro_exposure_score = self._sentiment_score_to_percent(self._pluck(analysis, "sentiment", "macro", "score"))
        industry_alignment_score = self._sentiment_score_to_percent(self._pluck(analysis, "sentiment", "industry", "score"))
        expected_move_score = self._expected_move_score(deep_recommendation)
        execution_quality_score = self._execution_quality_score(deep_recommendation)
        warnings = list(candidate.warnings)
        if deep_output is not None:
            warnings.extend(deep_output.diagnostics.warnings)
        if candidate.direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
        if deep_error:
            warnings.append(deep_error)
        transmission_alignment_score = self._transmission_alignment_score(analysis)
        transmission_bias = self._transmission_bias(analysis)
        if transmission_bias == "unknown":
            transmission_alignment_score = round((macro_exposure_score * 0.45) + (industry_alignment_score * 0.55), 2)
            transmission_bias = self._bias_from_alignment(transmission_alignment_score)
        primary_drivers = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "primary_drivers") or []
        primary_driver_details = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "primary_driver_details") or []
        expected_transmission_window = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "expected_transmission_window") or self._fallback_transmission_window_placeholder(watchlist.default_horizon)
        expected_transmission_window_detail = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "expected_transmission_window_detail") or self._transmission_window_detail(expected_transmission_window)
        conflict_flags = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "conflict_flags") or []
        conflict_flag_details = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "conflict_flag_details") or []
        transmission_tags = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "transmission_tags") or []
        transmission_tag_details = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "transmission_tag_details") or []
        industry_exposure_channels = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "industry_exposure_channels") or []
        industry_exposure_channel_details = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "industry_exposure_channel_details") or []
        ticker_exposure_channels = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "ticker_exposure_channels") or []
        ticker_exposure_channel_details = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "ticker_exposure_channel_details") or []
        transmission_effect = self._transmission_confidence_adjustment(analysis, transmission_bias=transmission_bias, alignment_score=transmission_alignment_score)
        base_confidence = round(float(deep_recommendation.confidence if deep_recommendation is not None else candidate.confidence_percent), 2)
        adjusted_confidence = round(max(0.0, min(95.0, base_confidence + transmission_effect)), 2)
        if not isinstance(primary_drivers, list) or not primary_drivers:
            primary_drivers = [
                item for item in [
                    "industry_context_support" if transmission_bias != "headwind" else "industry_context_headwind",
                    "macro_context_support" if transmission_bias != "headwind" else "macro_context_headwind",
                    "fresh_catalyst_pressure" if self._catalyst_score(analysis) >= 45.0 else None,
                ] if isinstance(item, str)
            ]
        if not isinstance(primary_driver_details, list) or not primary_driver_details:
            primary_driver_details = self._detail_fallback(primary_drivers)
        if not isinstance(conflict_flags, list):
            conflict_flags = []
        if not isinstance(conflict_flag_details, list) or not conflict_flag_details:
            conflict_flag_details = self._detail_fallback(conflict_flags)
        if not isinstance(transmission_tags, list):
            transmission_tags = []
        if not isinstance(transmission_tag_details, list) or not transmission_tag_details:
            transmission_tag_details = self._detail_fallback(transmission_tags)
        if not isinstance(industry_exposure_channels, list):
            industry_exposure_channels = []
        if not isinstance(industry_exposure_channel_details, list) or not industry_exposure_channel_details:
            industry_exposure_channel_details = self._channel_detail_fallback(industry_exposure_channels)
        if not isinstance(ticker_exposure_channels, list):
            ticker_exposure_channels = []
        if not isinstance(ticker_exposure_channel_details, list) or not ticker_exposure_channel_details:
            ticker_exposure_channel_details = self._channel_detail_fallback(ticker_exposure_channels)
        return TickerSignalSnapshot(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            status="degraded" if warnings else "ok",
            direction=(self._normalize_direction(deep_recommendation.direction) if deep_recommendation is not None else candidate.direction),
            swing_probability_percent=adjusted_confidence,
            confidence_percent=adjusted_confidence,
            attention_score=round(candidate.attention_score, 2),
            macro_exposure_score=macro_exposure_score,
            industry_alignment_score=industry_alignment_score,
            ticker_sentiment_score=ticker_sentiment_score,
            technical_setup_score=technical_score,
            catalyst_score=self._catalyst_score(analysis),
            expected_move_score=expected_move_score,
            execution_quality_score=execution_quality_score,
            warnings=list(dict.fromkeys(warnings)),
            missing_inputs=[],
            source_breakdown={
                "cheap_scan_summary": candidate.indicator_summary,
                "cheap_scan_model": candidate.cheap_scan_signal.diagnostics.get("model") if candidate.cheap_scan_signal is not None else None,
                "deep_analysis_available": deep_output is not None,
                "deep_analysis_model": self._pluck(analysis, "ticker_deep_analysis", "model"),
                "summary_method": getattr(deep_output.diagnostics, "summary_method", None) if deep_output is not None else None,
                "transmission_bias": transmission_bias,
                "transmission_bias_detail": self._transmission_bias_detail(transmission_bias),
                "transmission_tags": transmission_tags,
                "transmission_tag_details": transmission_tag_details,
                "primary_drivers": primary_drivers,
                "primary_driver_details": primary_driver_details,
                "industry_exposure_channels": industry_exposure_channels,
                "industry_exposure_channel_details": industry_exposure_channel_details,
                "ticker_exposure_channels": ticker_exposure_channels,
                "ticker_exposure_channel_details": ticker_exposure_channel_details,
                "expected_transmission_window": expected_transmission_window,
                "expected_transmission_window_detail": expected_transmission_window_detail,
                "conflict_flags": conflict_flags,
                "conflict_flag_details": conflict_flag_details,
                "base_confidence_percent": base_confidence,
                "transmission_confidence_adjustment": transmission_effect,
            },
            diagnostics={
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
                "cheap_scan_component_scores": {
                    "trend_score": candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else None,
                    "momentum_score": candidate.cheap_scan_signal.momentum_score if candidate.cheap_scan_signal is not None else None,
                    "breakout_score": candidate.cheap_scan_signal.breakout_score if candidate.cheap_scan_signal is not None else None,
                    "volatility_score": candidate.cheap_scan_signal.volatility_score if candidate.cheap_scan_signal is not None else None,
                    "liquidity_score": candidate.cheap_scan_signal.liquidity_score if candidate.cheap_scan_signal is not None else None,
                },
                "deep_analysis_error": deep_error,
                "base_confidence_percent": base_confidence,
                "transmission_confidence_adjustment": transmission_effect,
                "transmission_alignment_score": transmission_alignment_score,
                "transmission_bias": transmission_bias,
                "transmission_bias_detail": self._transmission_bias_detail(transmission_bias),
                "transmission_tags": transmission_tags,
                "transmission_tag_details": transmission_tag_details,
                "primary_drivers": primary_drivers,
                "primary_driver_details": primary_driver_details,
                "industry_exposure_channels": industry_exposure_channels,
                "industry_exposure_channel_details": industry_exposure_channel_details,
                "ticker_exposure_channels": ticker_exposure_channels,
                "ticker_exposure_channel_details": ticker_exposure_channel_details,
                "expected_transmission_window": expected_transmission_window,
                "expected_transmission_window_detail": expected_transmission_window_detail,
                "conflict_flags": conflict_flags,
                "conflict_flag_details": conflict_flag_details,
            },
            job_id=job_id,
            run_id=run_id,
        )

    def _build_plan_from_signal(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        signal: TickerSignalSnapshot,
        *,
        deep_output: RunOutput | None,
        deep_error: str | None,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
    ) -> RecommendationPlan:
        analysis = self._analysis_payload(deep_output)
        summary_text = self._pluck(analysis, "summary", "text") or signal.source_breakdown.get("cheap_scan_summary") or ""
        setup_family = self._plan_setup_family(signal, analysis, candidate)
        confidence_components = self._plan_confidence_components(signal, analysis, candidate)
        transmission_summary = self._transmission_summary(signal, analysis, candidate)
        calibration_review = self._calibration_review(
            calibration_summary,
            setup_family,
            signal.confidence_percent,
            horizon=watchlist.default_horizon.value,
            transmission_summary=transmission_summary,
        )
        calibrated_confidence = float(calibration_review.get("calibrated_confidence_percent", signal.confidence_percent) or signal.confidence_percent)
        rationale = self._rationale_summary(signal, candidate, setup_family, transmission_summary)
        warnings = list(signal.warnings)
        if deep_output is None or deep_error is not None:
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action="no_action",
                status="degraded",
                confidence_percent=calibrated_confidence,
                thesis_summary="Deep analysis did not complete; no actionable plan emitted.",
                rationale_summary=rationale,
                warnings=warnings,
                evidence_summary=self._evidence_summary(summary_text, setup_family, confidence_components, action_reason="deep_analysis_unavailable", calibration_review=calibration_review, transmission_summary=transmission_summary),
                signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        recommendation = deep_output.recommendation
        direction = self._normalize_direction(recommendation.direction)
        intended_action = direction if direction in {"long", "short"} else None
        action_reason = "actionable_setup"
        effective_threshold = float(calibration_review.get("effective_confidence_threshold", self.confidence_threshold))
        calibrated_confidence = float(calibration_review.get("calibrated_confidence_percent", signal.confidence_percent) or signal.confidence_percent)
        
        entry_price_low, entry_price_high, stop_loss, take_profit, risk_reward_ratio = None, None, None, None, None
        if intended_action:
            entry_price_low, entry_price_high, stop_loss, take_profit = self._family_adjusted_trade_levels(
                recommendation,
                setup_family=setup_family,
                action=intended_action,
                transmission_summary=transmission_summary,
            )
            risk_reward_ratio = self._risk_reward_ratio(recommendation)

        if direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
            action = "no_action"
            action_reason = "shorts_disabled"
        elif calibrated_confidence < effective_threshold:
            action = "no_action"
            action_reason = "below_calibrated_action_threshold" if effective_threshold > self.confidence_threshold or calibrated_confidence != signal.confidence_percent else "below_action_confidence_threshold"
        elif direction not in {"long", "short"}:
            action = "no_action"
            action_reason = "direction_not_actionable"
        elif int(transmission_summary.get("contradiction_count", 0) or 0) > 0 and calibrated_confidence < min(95.0, effective_threshold + 4.0):
            action = "no_action"
            action_reason = "context_transmission_contradiction"
        elif transmission_summary.get("context_bias") == "headwind" and calibrated_confidence < min(95.0, effective_threshold + 5.0):
            action = "no_action"
            action_reason = "context_transmission_headwind"
        else:
            action = direction

        if action == "no_action":
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action=action,
                status="ok" if not warnings else "partial",
                confidence_percent=calibrated_confidence,
                entry_price_low=entry_price_low,
                entry_price_high=entry_price_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                holding_period_days=self._holding_period_days(watchlist.default_horizon) if intended_action else None,
                risk_reward_ratio=risk_reward_ratio,
                thesis_summary=self._no_action_thesis(setup_family, action_reason, transmission_summary=transmission_summary),
                rationale_summary=rationale,
                warnings=list(dict.fromkeys(warnings)),
                evidence_summary=self._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
                signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, intended_action=intended_action),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        return RecommendationPlan(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            action=action,
            status="ok" if not warnings else "partial",
            confidence_percent=calibrated_confidence,
            entry_price_low=entry_price_low,
            entry_price_high=entry_price_high,
            stop_loss=stop_loss,
            take_profit=take_profit,
            holding_period_days=self._holding_period_days(watchlist.default_horizon),
            risk_reward_ratio=risk_reward_ratio,
            thesis_summary=summary_text or self._actionable_thesis(action, setup_family, transmission_summary=transmission_summary),
            rationale_summary=rationale,
            risks=self._plan_risks(warnings, setup_family, action, transmission_summary),
            warnings=list(dict.fromkeys(warnings)),
            evidence_summary=self._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
            signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, intended_action=intended_action),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
        )

    def _build_no_action_plan(
        self,
        watchlist: Watchlist,
        candidate: _CheapScanCandidate,
        signal: TickerSignalSnapshot,
        *,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
        reason: str,
    ) -> RecommendationPlan:
        setup_family = self._cheap_scan_setup_family(candidate)
        confidence_components = self._plan_confidence_components(signal, {}, candidate)
        transmission_summary = self._transmission_summary(signal, {}, candidate)
        calibration_review = self._calibration_review(
            calibration_summary,
            setup_family,
            signal.confidence_percent,
            horizon=watchlist.default_horizon.value,
            transmission_summary=transmission_summary,
        )
        calibrated_confidence = float(calibration_review.get("calibrated_confidence_percent", signal.confidence_percent) or signal.confidence_percent)
        return RecommendationPlan(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            action="no_action",
            status="ok" if not signal.warnings else "partial",
            confidence_percent=calibrated_confidence,
            thesis_summary=reason,
            rationale_summary=self._rationale_summary(signal, candidate, setup_family, transmission_summary),
            warnings=list(signal.warnings),
            evidence_summary=self._evidence_summary(candidate.indicator_summary, setup_family, confidence_components, action_reason="not_shortlisted", calibration_review=calibration_review, transmission_summary=transmission_summary),
            signal_breakdown=self._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
        )

    def _record_decision_sample(
        self,
        plan: RecommendationPlan,
        candidate: _CheapScanCandidate,
        *,
        signal: TickerSignalSnapshot,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None,
    ) -> None:
        if self.decision_samples is None or plan.id is None:
            return
        signal_breakdown = self._mapping(plan.signal_breakdown)
        evidence_summary = self._mapping(plan.evidence_summary)
        calibration_review = self._mapping(signal_breakdown.get("calibration_review"))
        effective_threshold = self._float_from_mapping(calibration_review, "effective_confidence_threshold")
        calibrated_confidence = self._float_from_mapping(calibration_review, "calibrated_confidence_percent")
        confidence_gap = None
        if calibrated_confidence is not None and effective_threshold is not None:
            confidence_gap = round(calibrated_confidence - effective_threshold, 2)
        action_reason = str(
            evidence_summary.get("action_reason")
            or evidence_summary.get("action_reason_label")
            or plan.action
            or "unknown"
        ).strip()
        decision_type = self._decision_type(plan.action, plan.status, action_reason, confidence_gap, shortlisted=shortlisted)
        review_priority = self._review_priority(decision_type, confidence_gap=confidence_gap, shortlisted=shortlisted, status=plan.status)
        shortlist_payload = {
            "shortlisted": shortlisted,
            "shortlist_rank": shortlist_rank,
            "shortlist_decision": shortlist_decision or {},
            "shortlist_reasons": signal.diagnostics.get("shortlist_reasons", []),
            "shortlist_reason_details": signal.diagnostics.get("shortlist_reason_details", []),
        }
        self.decision_samples.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=plan.id,
                ticker=plan.ticker,
                horizon=plan.horizon.value if hasattr(plan.horizon, "value") else str(plan.horizon),
                action=plan.action,
                decision_type=decision_type,
                decision_reason=action_reason,
                shortlisted=shortlisted,
                shortlist_rank=shortlist_rank,
                shortlist_decision=shortlist_payload,
                confidence_percent=plan.confidence_percent,
                calibrated_confidence_percent=calibrated_confidence,
                effective_threshold_percent=effective_threshold,
                confidence_gap_percent=confidence_gap,
                setup_family=str(signal_breakdown.get("setup_family") or "").strip(),
                transmission_bias=str(signal_breakdown.get("transmission_bias") or "").strip() or None,
                context_regime=str(self._pluck(signal_breakdown, "calibration_review", "context_regime", "key") or "").strip() or None,
                review_priority=review_priority,
                decision_context={
                    "status": plan.status,
                    "warnings": list(plan.warnings),
                    "shortlisted": shortlisted,
                    "shortlist_rank": shortlist_rank,
                    "shortlist_decision": shortlist_decision or {},
                    "confidence_percent": plan.confidence_percent,
                    "calibrated_confidence_percent": calibrated_confidence,
                    "effective_threshold_percent": effective_threshold,
                    "confidence_gap_percent": confidence_gap,
                    "action_reason": action_reason,
                    "review_priority": review_priority,
                },
                signal_breakdown=signal_breakdown,
                evidence_summary=evidence_summary,
                run_id=plan.run_id,
                job_id=plan.job_id,
                watchlist_id=plan.watchlist_id,
                ticker_signal_snapshot_id=plan.ticker_signal_snapshot_id,
            )
        )

    @staticmethod
    def _mapping(payload: object | None) -> dict[str, object]:
        if payload is None:
            return {}
        if isinstance(payload, dict):
            return payload
        if hasattr(payload, "items"):
            try:
                return dict(payload.items())
            except TypeError:
                return {}
        if hasattr(payload, "model_dump"):
            dumped = payload.model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {}
        return {}

    @staticmethod
    def _float_from_mapping(payload: object, key: str) -> float | None:
        if not hasattr(payload, "get"):
            return None
        value = payload.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _decision_type(
        action: str,
        status: str,
        action_reason: str,
        confidence_gap: float | None,
        *,
        shortlisted: bool,
    ) -> str:
        normalized_action = str(action or "").strip().lower()
        normalized_status = str(status or "").strip().lower()
        normalized_reason = str(action_reason or "").strip().lower()
        if normalized_action in {"long", "short"}:
            return "actionable"
        if normalized_status == "degraded" or normalized_reason == "deep_analysis_unavailable":
            return "degraded"
        if confidence_gap is not None and confidence_gap >= -5.0:
            return "near_miss"
        if shortlisted:
            return "rejected"
        return "no_action"

    @staticmethod
    def _review_priority(
        decision_type: str,
        *,
        confidence_gap: float | None,
        shortlisted: bool,
        status: str,
    ) -> str:
        if decision_type == "actionable":
            return "medium" if str(status or "").strip().lower() == "partial" else "low"
        if decision_type == "degraded":
            return "high"
        if confidence_gap is not None and confidence_gap >= -2.0:
            return "high"
        if confidence_gap is not None and confidence_gap >= -6.0:
            return "medium"
        return "medium" if shortlisted else "low"

    @staticmethod
    def _analysis_payload(output: RunOutput | None) -> dict[str, Any]:
        if output is None or not output.diagnostics.analysis_json:
            return {}
        try:
            payload = json.loads(output.diagnostics.analysis_json)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _normalize_direction(direction: RecommendationDirection | str | None) -> str:
        if isinstance(direction, RecommendationDirection):
            raw = direction.value
        else:
            raw = str(direction or "neutral")
        normalized = raw.strip().lower()
        if normalized == "long":
            return "long"
        if normalized == "short":
            return "short"
        return "neutral"

    @staticmethod
    def _pluck(payload: dict[str, Any], *path: str) -> Any:
        current: Any = payload
        for key in path:
            if not hasattr(current, "get"):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _sentiment_score_to_percent(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(100.0, (numeric + 1.0) * 50.0)), 2)

    @staticmethod
    def _expected_move_score(recommendation: Recommendation | None) -> float:
        if recommendation is None or recommendation.entry_price == 0:
            return 0.0
        distance = abs(float(recommendation.take_profit) - float(recommendation.entry_price)) / abs(float(recommendation.entry_price))
        return round(max(0.0, min(100.0, distance * 1000.0)), 2)

    @staticmethod
    def _execution_quality_score(recommendation: Recommendation | None) -> float:
        if recommendation is None:
            return 0.0
        reward = abs(float(recommendation.take_profit) - float(recommendation.entry_price))
        risk = abs(float(recommendation.entry_price) - float(recommendation.stop_loss))
        if risk <= 0:
            return 0.0
        return round(max(0.0, min(100.0, (reward / risk) * 40.0)), 2)

    @staticmethod
    def _risk_reward_ratio(recommendation: Recommendation) -> float | None:
        reward = abs(float(recommendation.take_profit) - float(recommendation.entry_price))
        risk = abs(float(recommendation.entry_price) - float(recommendation.stop_loss))
        if risk <= 0:
            return None
        return round(reward / risk, 4)

    @staticmethod
    def _catalyst_score(analysis: dict[str, Any]) -> float:
        explicit = WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "catalyst_intensity_percent")
        if WatchlistOrchestrationService._is_number(explicit):
            return round(float(explicit), 2)
        news_item_count = WatchlistOrchestrationService._pluck(analysis, "news", "item_count")
        try:
            count = float(news_item_count)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(100.0, count * 10.0)), 2)

    @staticmethod
    def _transmission_alignment_score(analysis: dict[str, Any]) -> float:
        value = WatchlistOrchestrationService._pluck(analysis, "ticker_deep_analysis", "transmission_analysis", "alignment_percent")
        if WatchlistOrchestrationService._is_number(value):
            return round(float(value), 2)
        return 0.0

    def _transmission_bias(self, analysis: dict[str, Any]) -> str:
        transmission = self._pluck(analysis, "ticker_deep_analysis", "transmission_analysis")
        if isinstance(transmission, dict):
            return self.taxonomy_service.derive_transmission_bias(transmission)
        return "unknown"

    def _transmission_bias_detail(self, value: object) -> dict[str, str] | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_transmission_bias_definition(value)
        key = str(definition.get("key", value)).strip() or value.strip()
        label = str(definition.get("label", value)).strip() or value.strip()
        return {"key": key, "label": label}

    @staticmethod
    def _bias_from_alignment(alignment_percent: float) -> str:
        if alignment_percent >= 62.0:
            return "tailwind"
        if alignment_percent <= 42.0:
            return "headwind"
        return "mixed"

    def _transmission_confidence_adjustment(
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
        return round(max(-10.0, min(8.0, adjustment)), 2)

    @staticmethod
    def _signal_breakdown(
        signal: TickerSignalSnapshot,
        *,
        setup_family: str,
        confidence_components: dict[str, float],
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
        intended_action: str | None = None,
    ) -> dict[str, object]:
        calibration = calibration_review or {}
        calibrated_confidence = calibration.get("calibrated_confidence_percent") if isinstance(calibration.get("calibrated_confidence_percent"), (int, float)) else signal.confidence_percent
        return {
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
            "raw_confidence_percent": signal.confidence_percent,
            "calibrated_confidence_percent": round(float(calibrated_confidence), 2),
            "confidence_bucket": WatchlistOrchestrationService._confidence_bucket(float(calibrated_confidence)),
            "calibration_review": calibration,
            "transmission_summary": transmission_summary or {},
            "mode": signal.diagnostics.get("mode"),
        }

    def _plan_setup_family(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
    ) -> str:
        explicit = self._pluck(analysis, "ticker_deep_analysis", "setup_family")
        if isinstance(explicit, str) and explicit.strip() and explicit.strip() not in {"uncategorized", "no_action"}:
            return explicit.strip()
        return self._cheap_scan_setup_family(candidate, signal=signal)

    def _plan_confidence_components(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
    ) -> dict[str, float]:
        explicit = self._pluck(analysis, "ticker_deep_analysis", "confidence_components")
        if isinstance(explicit, dict) and explicit:
            normalized = {str(key): round(float(value), 2) for key, value in explicit.items() if self._is_number(value)}
            normalized.setdefault("transmission_quality", round(signal.diagnostics.get("transmission_alignment_score", 0.0) if self._is_number(signal.diagnostics.get("transmission_alignment_score")) else 0.0, 2))
            return normalized
        return {
            "context_confidence": round((signal.macro_exposure_score * 0.45) + (signal.industry_alignment_score * 0.55), 2),
            "directional_confidence": round(max(signal.ticker_sentiment_score, candidate.confidence_percent), 2),
            "catalyst_confidence": round(signal.catalyst_score, 2),
            "technical_clarity": round(signal.technical_setup_score, 2),
            "execution_clarity": round(signal.execution_quality_score if signal.execution_quality_score > 0 else signal.attention_score, 2),
            "transmission_quality": round(signal.diagnostics.get("transmission_alignment_score", 0.0) if self._is_number(signal.diagnostics.get("transmission_alignment_score")) else 0.0, 2),
            "data_quality_cap": round(max(25.0, 100.0 - (len(signal.warnings) * 10.0)), 2),
        }

    def _transmission_summary(
        self,
        signal: TickerSignalSnapshot,
        analysis: dict[str, Any],
        candidate: _CheapScanCandidate,
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
            return {
                "alignment_percent": alignment_percent,
                "context_bias": bias,
                "transmission_bias": bias,
                "transmission_bias_detail": self._transmission_bias_detail(bias),
                "catalyst_intensity_percent": round(float(explicit.get("catalyst_intensity_percent", 0.0)), 2) if self._is_number(explicit.get("catalyst_intensity_percent")) else signal.catalyst_score,
                "context_strength_percent": round(float(explicit.get("context_strength_percent", 0.0)), 2) if self._is_number(explicit.get("context_strength_percent")) else 0.0,
                "context_event_relevance_percent": round(float(explicit.get("context_event_relevance_percent", 0.0)), 2) if self._is_number(explicit.get("context_event_relevance_percent")) else 0.0,
                "contradiction_count": int(float(explicit.get("contradiction_count", 0.0))) if self._is_number(explicit.get("contradiction_count")) else 0,
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

    def _fallback_primary_drivers(
        self,
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        bias: str,
    ) -> list[str]:
        drivers: list[tuple[str, float]] = [
            ("industry_context_support" if bias != "headwind" else "industry_context_headwind", signal.industry_alignment_score),
            ("macro_context_support" if bias != "headwind" else "macro_context_headwind", signal.macro_exposure_score),
            ("ticker_sentiment_confirmation" if bias != "headwind" else "ticker_sentiment_conflict", signal.ticker_sentiment_score),
            ("fresh_catalyst_pressure", signal.catalyst_score),
            ("attention_leader", candidate.attention_score),
        ]
        ranked = [key for key, score in sorted(drivers, key=lambda item: item[1], reverse=True) if score >= 45.0]
        return ranked[:3]

    @staticmethod
    def _string_value(value: object, *, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @staticmethod
    def _fallback_industry_exposure_channels(signal: TickerSignalSnapshot) -> list[str]:
        channels: list[str] = []
        if signal.macro_exposure_score >= 55.0:
            channels.append("macro_regime")
        if signal.industry_alignment_score >= 55.0:
            channels.append("industry_demand")
        if signal.industry_alignment_score >= 65.0:
            channels.append("industry_read_through")
        return channels

    @staticmethod
    def _fallback_ticker_exposure_channels(signal: TickerSignalSnapshot, candidate: _CheapScanCandidate) -> list[str]:
        channels: list[str] = []
        if signal.ticker_sentiment_score >= 55.0:
            channels.append("ticker_sentiment")
        if signal.catalyst_score >= 45.0:
            channels.append("news_catalyst")
        if signal.catalyst_score >= 70.0:
            channels.append("event_follow_through")
        if candidate.attention_score >= 70.0:
            channels.append("attention_leader")
        return channels

    @staticmethod
    def _channel_detail_fallback(channels: list[str]) -> list[dict[str, str]]:
        return [
            {"key": str(channel), "label": str(channel).replace("_", " ")}
            for channel in list(dict.fromkeys(channels))
            if isinstance(channel, str) and channel.strip()
        ]

    def _relationship_detail_fallback(self, relationships: list[dict[str, object]]) -> list[dict[str, object]]:
        details: list[dict[str, object]] = []
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            enriched = {**rel}
            rel_type = str(rel.get("type", "")).strip()
            if rel_type:
                type_def = self.taxonomy_service.get_relationship_type_definition(rel_type)
                enriched["type_label"] = type_def.get("label", rel_type.replace("_", " "))
            channel = str(rel.get("channel", "")).strip()
            if channel:
                channel_def = self.taxonomy_service.get_transmission_channel_definition(channel)
                enriched["channel_label"] = channel_def.get("label", channel.replace("_", " "))
            details.append(enriched)
        return details

    def _transmission_window_detail(self, value: str | None) -> dict[str, str] | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_transmission_window_definition(value)
        key = str(definition.get("key", value)).strip()
        label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
        if not key:
            return None
        return {"key": key, "label": label}

    @staticmethod
    def _detail_fallback(values: list[str]) -> list[dict[str, str]]:
        return [
            {"key": str(value), "label": str(value).replace("_", " ")}
            for value in list(dict.fromkeys(values))
            if isinstance(value, str) and value.strip()
        ]

    def _shortlist_reason_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            definition = self.taxonomy_service.get_shortlist_reason_definition(value)
            key = str(definition.get("key", value)).strip()
            label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
            if not key or key in seen:
                continue
            seen.add(key)
            details.append({"key": key, "label": label})
        return details

    def _shortlist_selection_lane_label(self, value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        definition = self.taxonomy_service.get_shortlist_selection_lane_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")

    def _counted_shortlist_reason_details(self, counts: dict[str, int]) -> list[dict[str, object]]:
        details: list[dict[str, object]] = []
        for key, count in counts.items():
            definition = self.taxonomy_service.get_shortlist_reason_definition(key)
            details.append({
                "key": str(definition.get("key", key)).strip() or key,
                "label": str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " "),
                "count": int(count or 0),
            })
        return details

    def _calibration_reason_details(self, values: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            definition = self.taxonomy_service.get_calibration_reason_definition(value)
            key = str(definition.get("key", value)).strip()
            label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
            if not key or key in seen:
                continue
            seen.add(key)
            details.append({"key": key, "label": label})
        return details

    def _calibration_review_status_label(self, value: str) -> str:
        definition = self.taxonomy_service.get_calibration_review_status_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")

    def _action_reason_label(self, value: str) -> str:
        definition = self.taxonomy_service.get_action_reason_definition(value)
        return str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")

    @staticmethod
    def _fallback_transmission_window(signal: TickerSignalSnapshot) -> str:
        if signal.catalyst_score >= 70.0:
            return "1d"
        if signal.catalyst_score >= 45.0:
            return "2d_5d"
        if signal.macro_exposure_score >= 60.0 or signal.industry_alignment_score >= 60.0:
            return "1w_plus"
        return "unknown"

    @staticmethod
    def _fallback_transmission_window_placeholder(horizon: StrategyHorizon) -> str:
        if horizon == StrategyHorizon.ONE_DAY:
            return "1d"
        if horizon == StrategyHorizon.ONE_WEEK:
            return "2d_5d"
        if horizon == StrategyHorizon.ONE_MONTH:
            return "1w_plus"
        return "unknown"

    @staticmethod
    def _fallback_decay_state(signal: TickerSignalSnapshot) -> str:
        if signal.catalyst_score >= 75.0:
            return "fresh"
        if signal.catalyst_score >= 45.0:
            return "active"
        if signal.catalyst_score > 0.0:
            return "fading"
        return "unknown"

    @staticmethod
    def _fallback_conflict_flags(
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        bias: str,
    ) -> list[str]:
        flags: list[str] = []
        if bias == "headwind" and candidate.direction in {"long", "short"} and signal.technical_setup_score >= 60.0:
            flags.append("technical_context_conflict")
        if signal.macro_exposure_score >= 55.0 and signal.industry_alignment_score <= 45.0:
            flags.append("macro_industry_conflict")
            flags.append("context_contradiction")
        if signal.ticker_sentiment_score <= 40.0 and candidate.direction == "long":
            flags.append("directional_conflict")
        if signal.ticker_sentiment_score >= 60.0 and candidate.direction == "short":
            flags.append("directional_conflict")
        if signal.catalyst_score >= 65.0 and 45.0 <= signal.industry_alignment_score <= 60.0:
            flags.append("timing_conflict")
        return list(dict.fromkeys(flags))

    def _cheap_scan_setup_family(
        self,
        candidate: _CheapScanCandidate,
        *,
        signal: TickerSignalSnapshot | None = None,
    ) -> str:
        technical = signal.technical_setup_score if signal is not None else (candidate.cheap_scan_signal.trend_score if candidate.cheap_scan_signal is not None else candidate.confidence_percent)
        breakout = candidate.cheap_scan_signal.breakout_score if candidate.cheap_scan_signal is not None else 0.0
        momentum = candidate.cheap_scan_signal.momentum_score if candidate.cheap_scan_signal is not None else 0.0
        catalyst = signal.catalyst_score if signal is not None else 0.0
        macro = signal.macro_exposure_score if signal is not None else 0.0
        industry = signal.industry_alignment_score if signal is not None else 0.0
        direction = candidate.direction
        if candidate.error_message:
            return "no_action"
        if catalyst >= 55.0:
            return "catalyst_follow_through"
        if breakout >= 70.0 and momentum >= 60.0:
            return "breakout" if direction != "short" else "breakdown"
        if technical >= 70.0 and momentum >= 55.0:
            return "continuation"
        if direction == "short" and technical >= 55.0:
            return "macro_beneficiary_loser" if macro >= 55.0 or industry >= 55.0 else "mean_reversion"
        if direction == "long" and technical >= 55.0 and (macro >= 55.0 or industry >= 55.0):
            return "macro_beneficiary_loser"
        if technical >= 50.0:
            return "mean_reversion"
        return "no_action"

    @staticmethod
    def _rationale_summary(
        signal: TickerSignalSnapshot,
        candidate: _CheapScanCandidate,
        setup_family: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        components = [candidate.indicator_summary]
        if setup_family and setup_family != "uncategorized":
            components.append(f"setup family {setup_family.replace('_', ' ')}")
        if isinstance(transmission_summary, dict):
            bias = transmission_summary.get("context_bias")
            if isinstance(bias, str) and bias:
                components.append(f"context {bias}")
            window = transmission_summary.get("expected_transmission_window")
            if isinstance(window, str) and window and window != "unknown":
                components.append(f"window {window}")
            driver_label = WatchlistOrchestrationService._primary_driver_label(transmission_summary)
            if driver_label:
                components.append(f"driver {driver_label}")
            relationship_summary = WatchlistOrchestrationService._relationship_summary(transmission_summary)
            if relationship_summary:
                components.append(f"relationship {relationship_summary}")
        components.append(f"attention {signal.attention_score:.1f}")
        components.append(f"confidence {signal.confidence_percent:.1f}")
        return " · ".join(component for component in components if component)

    @staticmethod
    def _relationship_summary(transmission_summary: dict[str, object] | None) -> str:
        if not isinstance(transmission_summary, dict):
            return ""
        matched = transmission_summary.get("matched_ticker_relationships")
        if not isinstance(matched, list) or not matched:
            return ""
        labels: list[str] = []
        for item in matched[:2]:
            if not isinstance(item, dict):
                continue
            relation = str(item.get("type", "")).strip().replace("_", " ")
            target = str(item.get("target_label") or item.get("target") or "").strip()
            if relation and target:
                labels.append(f"{relation} {target}")
            elif target:
                labels.append(target)
        return ", ".join(labels)

    def _evidence_summary(
        self,
        summary_text: str,
        setup_family: str,
        confidence_components: dict[str, float],
        *,
        action_reason: str,
        calibration_review: dict[str, object] | None = None,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calibration = calibration_review or {}
        return {
            "summary": summary_text,
            "setup_family": setup_family,
            "action_reason": action_reason,
            "action_reason_label": self._action_reason_label(action_reason),
            "action_reason_detail": self._action_reason_detail(setup_family, action_reason, transmission_summary=transmission_summary),
            "confidence_components": confidence_components,
            "raw_confidence_percent": calibration.get("raw_confidence_percent"),
            "calibrated_confidence_percent": calibration.get("calibrated_confidence_percent"),
            "confidence_adjustment": calibration.get("confidence_adjustment"),
            "calibration_review": calibration,
            "transmission_summary": transmission_summary or {},
            "entry_style": self._entry_style(setup_family),
            "stop_style": self._stop_style(setup_family),
            "target_style": self._target_style(setup_family),
            "timing_expectation": self._timing_expectation(setup_family, transmission_summary=transmission_summary),
            "evaluation_focus": self._evaluation_focus(setup_family),
            "invalidation_summary": self._invalidation_summary(setup_family, transmission_summary=transmission_summary),
        }

    def _no_action_thesis(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        relationship_summary = self._relationship_summary(transmission_summary)
        relationship_suffix = f" Read-through to watch: {relationship_summary}." if relationship_summary else ""
        if action_reason in {"below_action_confidence_threshold", "below_calibrated_action_threshold"}:
            family_text = {
                "breakout": "the breakout lacked enough confirmed follow-through",
                "breakdown": "the breakdown lacked enough confirmed follow-through",
                "continuation": "trend continuation evidence was too soft",
                "mean_reversion": "the reversion case was too weak against the prevailing move",
                "catalyst_follow_through": "the catalyst impulse was not strong enough to trust",
                "macro_beneficiary_loser": "the macro transmission case was not strong enough to express",
            }.get(setup_family, "conviction was too weak")
            return f"Detected a {setup_label} candidate, but {family_text} for an actionable trade plan.{relationship_suffix}"
        if action_reason == "shorts_disabled":
            return f"Detected a {setup_label} candidate, but the watchlist policy does not permit the required short expression.{relationship_suffix}"
        if action_reason == "direction_not_actionable":
            return f"Detected a {setup_label} structure, but direction remained too ambiguous for a trade plan.{relationship_suffix}"
        if action_reason == "not_shortlisted":
            family_text = {
                "breakout": "the breakout was not clean enough relative to stronger shortlist candidates",
                "breakdown": "the breakdown pressure was weaker than the selected names",
                "continuation": "trend continuation quality lagged stronger shortlist names",
                "mean_reversion": "the reversal setup lacked enough exhaustion confirmation",
                "catalyst_follow_through": "the catalyst lane found stronger event continuation candidates",
                "macro_beneficiary_loser": "macro transmission existed but did not rank highly enough for escalation",
            }.get(setup_family, "it did not rank highly enough for escalation")
            return f"Detected a {setup_label} structure, but {family_text}.{relationship_suffix}"
        if action_reason == "context_transmission_headwind":
            driver = self._primary_driver_label(transmission_summary)
            return f"Detected a {setup_label} structure, but macro and industry transmission remained a headwind to the proposed trade direction{f' ({driver})' if driver else ''}.{relationship_suffix}"
        if action_reason == "context_transmission_contradiction":
            driver = self._primary_driver_label(transmission_summary)
            return f"Detected a {setup_label} structure, but active context evidence was internally contradictory{f' around {driver}' if driver else ''}, so the trade case was not clean enough to promote.{relationship_suffix}"
        return f"Signal quality was insufficient for an actionable trade plan.{relationship_suffix}".strip()

    def _actionable_thesis(
        self,
        action: str,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        direction = "bullish" if action == "long" else "bearish"
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        driver = self._primary_driver_label(transmission_summary)
        relationship_summary = self._relationship_summary(transmission_summary)
        entry_style = self._entry_style(setup_family).replace("_", " ")
        timing = self._timing_expectation(setup_family, transmission_summary=transmission_summary)
        family_text = {
            "continuation": f"Actionable {direction} continuation setup with trend structure still intact and a pullback-or-reclaim style trigger",
            "breakout": f"Actionable {direction} breakout setup with follow-through conditions in place and a break-or-retest trigger",
            "breakdown": f"Actionable {direction} breakdown setup with support failure or failed retest pressure visible",
            "mean_reversion": f"Actionable {direction} mean reversion setup with a defined reversal window and exhaustion-sensitive timing",
            "catalyst_follow_through": f"Actionable {direction} catalyst follow-through setup while event pressure remains active",
            "macro_beneficiary_loser": f"Actionable {direction} macro beneficiary / loser setup tied to broader context transmission",
        }.get(setup_family, f"Actionable {direction} {setup_label} setup identified")
        if driver and relationship_summary:
            return f"{family_text}; entry style is {entry_style}, expected window is {timing}, the primary driver is {driver}, and ticker read-through is supported by {relationship_summary}."
        if driver:
            return f"{family_text}; entry style is {entry_style}, expected window is {timing}, and the primary driver is {driver}."
        if relationship_summary:
            return f"{family_text}; entry style is {entry_style}, expected window is {timing}, and ticker read-through is supported by {relationship_summary}."
        return f"{family_text}; entry style is {entry_style} and expected window is {timing}."

    @staticmethod
    def _entry_style(setup_family: str) -> str:
        return {
            "continuation": "pullback_or_reclaim",
            "breakout": "break_or_retest",
            "breakdown": "break_or_failed_retest",
            "mean_reversion": "reversal_confirmation",
            "catalyst_follow_through": "post_catalyst_continuation",
            "macro_beneficiary_loser": "context_aligned_pullback",
        }.get(setup_family, "standard_entry")

    @staticmethod
    def _stop_style(setup_family: str) -> str:
        return {
            "continuation": "below_pullback_structure",
            "breakout": "below_break_level_with_buffer",
            "breakdown": "above_failed_retest_level",
            "mean_reversion": "beyond_exhaustion_extreme",
            "catalyst_follow_through": "beyond_catalyst_impulse_level",
            "macro_beneficiary_loser": "below_or_above_exposure_invalidation",
        }.get(setup_family, "generic_structure_stop")

    @staticmethod
    def _target_style(setup_family: str) -> str:
        return {
            "continuation": "trend_extension_or_next_level",
            "breakout": "measured_move_or_next_resistance",
            "breakdown": "measured_move_or_next_support",
            "mean_reversion": "range_midpoint_or_moving_average_retest",
            "catalyst_follow_through": "event_follow_through_extension",
            "macro_beneficiary_loser": "context_continuation_extension",
        }.get(setup_family, "generic_target")

    def _timing_expectation(
        self,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        explicit_window = None
        if isinstance(transmission_summary, dict):
            raw_window = transmission_summary.get("expected_transmission_window")
            if isinstance(raw_window, str) and raw_window and raw_window != "unknown":
                explicit_window = raw_window
        family_default = {
            "continuation": "2d_5d",
            "breakout": "1d_3d",
            "breakdown": "1d_3d",
            "mean_reversion": "2d_5d",
            "catalyst_follow_through": "1d_2d",
            "macro_beneficiary_loser": "1w_plus",
        }.get(setup_family, "unknown")
        return explicit_window or family_default

    @staticmethod
    def _evaluation_focus(setup_family: str) -> list[str]:
        return {
            "continuation": ["trend_persistence", "pullback_hold_quality", "stall_rate"],
            "breakout": ["follow_through_speed", "false_break_frequency", "retest_hold_quality"],
            "breakdown": ["support_failure_persistence", "reclaim_risk", "downside_extension_quality"],
            "mean_reversion": ["reversal_confirmation", "reversion_completion_rate", "trend_resumption_risk"],
            "catalyst_follow_through": ["catalyst_decay_speed", "day1_vs_day5_follow_through", "confirmation_quality"],
            "macro_beneficiary_loser": ["transmission_persistence", "context_regime_sensitivity", "sector_sympathy_quality"],
        }.get(setup_family, ["execution_quality", "follow_through", "risk_control"])

    def _action_reason_detail(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        driver = self._primary_driver_label(transmission_summary)
        relationship_summary = self._relationship_summary(transmission_summary)
        relationship_suffix = f" Relationship read-through: {relationship_summary}." if relationship_summary else ""
        family_label = setup_family.replace("_", " ") if setup_family else "setup"
        if action_reason == "actionable_setup":
            return f"Promoted because the {family_label} structure met the current execution and confidence requirements.{relationship_suffix}"
        if action_reason == "not_shortlisted":
            return f"Observed a potential {family_label} structure, but it did not clear shortlist competition for deep analysis.{relationship_suffix}"
        if action_reason in {"below_action_confidence_threshold", "below_calibrated_action_threshold"}:
            return f"The {family_label} structure remained visible, but conviction and execution clarity were not strong enough to justify promotion.{relationship_suffix}"
        if action_reason == "shorts_disabled":
            return f"The required short expression was blocked by watchlist policy.{relationship_suffix}".strip()
        if action_reason == "direction_not_actionable":
            return f"The {family_label} structure did not resolve into a tradeable direction.{relationship_suffix}"
        if action_reason == "deep_analysis_unavailable":
            return f"Cheap scan detected a possible {family_label} case, but deep analysis did not complete cleanly enough to frame a trade plan.{relationship_suffix}"
        if action_reason == "context_transmission_headwind":
            return f"Broader context remained a headwind to the setup{f' via {driver}' if driver else ''}.{relationship_suffix}"
        if action_reason == "context_transmission_contradiction":
            return f"Broader context evidence remained too contradictory to trust the setup cleanly{f' around {driver}' if driver else ''}.{relationship_suffix}"
        return f"The {family_label} setup was reviewed but did not earn promotion.{relationship_suffix}"

    def _invalidation_summary(
        self,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        driver = self._primary_driver_label(transmission_summary)
        relationship_summary = self._relationship_summary(transmission_summary)
        base = {
            "continuation": "invalidate if the trend pullback breaks and continuation structure fails",
            "breakout": "invalidate if the breakout loses the breakout level or fails its retest",
            "breakdown": "invalidate if the breakdown reclaims lost support or the failed retest resolves higher",
            "mean_reversion": "invalidate if the stretched move keeps extending and reversal confirmation fails",
            "catalyst_follow_through": "invalidate if the catalyst impulse loses confirmation or post-event continuation stalls",
            "macro_beneficiary_loser": "invalidate if the broader context transmission weakens or sector sympathy breaks",
        }.get(setup_family, "invalidate if the setup loses its defining structure")
        if driver and relationship_summary:
            return f"{base}; primary driver to monitor is {driver}; ticker read-through to monitor is {relationship_summary}"
        if driver:
            return f"{base}; primary driver to monitor is {driver}"
        if relationship_summary:
            return f"{base}; ticker read-through to monitor is {relationship_summary}"
        return base

    @staticmethod
    def _primary_driver_label(transmission_summary: dict[str, object] | None) -> str | None:
        if not isinstance(transmission_summary, dict):
            return None
        details = transmission_summary.get("primary_driver_details")
        if isinstance(details, list) and details:
            first = details[0]
            if isinstance(first, dict):
                label = first.get("label")
                if isinstance(label, str) and label.strip():
                    return label.strip()
        drivers = transmission_summary.get("primary_drivers")
        if not isinstance(drivers, list) or not drivers:
            return None
        first = drivers[0]
        return str(first).replace("_", " ") if isinstance(first, str) and first else None

    @staticmethod
    def _matched_ticker_relationships(transmission_summary: dict[str, object] | None) -> list[dict[str, object]]:
        if not isinstance(transmission_summary, dict):
            return []
        raw = transmission_summary.get("matched_ticker_relationships")
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def _relationship_label(relationship: dict[str, object]) -> str | None:
        relation_type = str(relationship.get("type_label", relationship.get("type", "")) or "").strip().replace("_", " ")
        target = str(relationship.get("target_label", relationship.get("target", "")) or "").strip()
        channel = str(relationship.get("channel_label", relationship.get("channel", "")) or "").strip().replace("_", " ")
        if relation_type and target and channel:
            return f"{relation_type} {target} via {channel}"
        if relation_type and target:
            return f"{relation_type} {target}"
        if target:
            return target
        return None

    @classmethod
    def _relationship_summary(cls, transmission_summary: dict[str, object] | None) -> str | None:
        labels = [
            cls._relationship_label(item)
            for item in cls._matched_ticker_relationships(transmission_summary)[:2]
        ]
        labels = [label for label in labels if label]
        if not labels:
            return None
        return " and ".join(labels)

    def _family_adjusted_trade_levels(
        self,
        recommendation: Recommendation,
        *,
        setup_family: str,
        action: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> tuple[float, float, float, float]:
        bias = transmission_summary.get("context_bias") if isinstance(transmission_summary, dict) else None
        return family_adjusted_trade_levels(
            entry_price=float(recommendation.entry_price),
            stop_loss=float(recommendation.stop_loss),
            take_profit=float(recommendation.take_profit),
            setup_family=setup_family,
            action=action,
            transmission_context_bias=str(bias) if bias is not None else None,
            tuning_config=self.plan_generation_tuning_config,
        )

    @staticmethod
    def _plan_risks(
        warnings: list[str],
        setup_family: str,
        action: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> list[str]:
        risks = list(dict.fromkeys(warnings))
        if setup_family in {"breakout", "breakdown"}:
            risks.append("failed follow-through can reverse quickly after entry")
        if setup_family == "mean_reversion":
            risks.append("countertrend timing can fail if momentum persists")
        if setup_family == "catalyst_follow_through":
            risks.append("catalyst impulse may fade quickly if confirmation weakens")
        if setup_family == "macro_beneficiary_loser":
            risks.append("macro transmission can weaken if the broader regime shifts")
        if isinstance(transmission_summary, dict):
            conflict_flags = transmission_summary.get("conflict_flags")
            if isinstance(conflict_flags, list):
                if "technical_context_conflict" in conflict_flags:
                    risks.append("price structure and broader context are not fully aligned")
                if "macro_industry_conflict" in conflict_flags or "industry_ticker_conflict" in conflict_flags:
                    risks.append("cross-layer context conflicts can weaken follow-through")
            decay_state = transmission_summary.get("decay_state")
            if decay_state == "fading":
                risks.append("context support may already be fading for this horizon")
            if WatchlistOrchestrationService._relationship_summary(transmission_summary):
                risks.append("ticker relationship read-through can break if peer, supplier, or customer confirmation fades")
        if action in {"long", "short"} and warnings == []:
            risks.append("macro/industry transmission should keep confirming the trade after entry")
        if action == "short":
            risks.append("short squeeze risk remains elevated if sentiment reverses")
        return list(dict.fromkeys(risks))

    @staticmethod
    def _confidence_bucket(confidence_percent: float) -> str:
        if confidence_percent >= 80.0:
            return "80_plus"
        if confidence_percent >= 65.0:
            return "65_to_79"
        if confidence_percent >= 50.0:
            return "50_to_64"
        return "below_50"

    @staticmethod
    def _is_number(value: Any) -> bool:
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True

    def _load_calibration_summary(self) -> object | None:
        if self.calibration_service is None:
            return None
        try:
            return self.calibration_service.summarize(limit=500)
        except Exception:
            return None

    def _calibration_review(
        self,
        calibration_summary: object | None,
        setup_family: str,
        confidence_percent: float,
        *,
        horizon: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if calibration_summary is None:
            threshold_offset = self._signal_gating_tuning_value("threshold_offset", 0.0)
            confidence_adjustment = self._signal_gating_tuning_value("confidence_adjustment", 0.0)
            return {
                "enabled": False,
                "review_status": "disabled",
                "review_status_label": self._calibration_review_status_label("disabled"),
                "raw_confidence_percent": round(confidence_percent, 2),
                "calibrated_confidence_percent": round(confidence_percent + confidence_adjustment, 2),
                "confidence_adjustment": round(confidence_adjustment, 2),
                "base_confidence_threshold": round(self.confidence_threshold, 2),
                "effective_confidence_threshold": round(self.confidence_threshold + threshold_offset, 2),
                "threshold_adjustment": round(threshold_offset, 2),
                "reasons": [],
                "reason_details": [],
            }
        bucket_key = self._confidence_bucket(confidence_percent)
        base_threshold = float(self.confidence_threshold)
        overall_win_rate = self._safe_rate(getattr(calibration_summary, "overall_win_rate_percent", None))
        transmission_bias = self._calibration_transmission_bias(transmission_summary)
        context_regime = self._calibration_context_regime(transmission_summary)
        horizon_setup_key = f"{horizon}__{setup_family}"

        setup_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_setup_family", []), setup_family)
        confidence_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_confidence_bucket", []), bucket_key)
        horizon_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_horizon", []), horizon)
        transmission_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_transmission_bias", []), transmission_bias)
        context_regime_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_context_regime", []), context_regime)
        horizon_setup_bucket = self._find_calibration_bucket(getattr(calibration_summary, "by_horizon_setup_family", []), horizon_setup_key)

        threshold_adjustment = 0.0
        confidence_adjustment = 0.0
        reasons: list[str] = []
        reviewed_buckets = (
            ("setup_family", setup_bucket, 10.0, 5.0, -2.0, 1.6, 0.9, -0.6),
            ("confidence_bucket", confidence_bucket, 10.0, 5.0, -2.0, 1.2, 0.75, -0.5),
            ("horizon", horizon_bucket, 4.0, 2.0, -1.0, 0.85, 0.5, -0.3),
            ("transmission_bias", transmission_bucket, 3.0, 1.5, -0.75, 0.6, 0.35, -0.2),
            ("context_regime", context_regime_bucket, 3.0, 1.5, -0.75, 0.6, 0.35, -0.2),
            ("horizon_setup_family", horizon_setup_bucket, 4.0, 2.0, -1.0, 0.75, 0.4, -0.2),
        )
        usable_bucket_count = 0
        strong_bucket_count = 0
        for label, bucket, hard_penalty, soft_penalty, reward, hard_conf_penalty, soft_conf_penalty, conf_reward in reviewed_buckets:
            adjustment, bucket_reasons, sample_status = self._bucket_threshold_adjustment(
                label,
                bucket,
                overall_win_rate=overall_win_rate,
                hard_penalty=hard_penalty,
                soft_penalty=soft_penalty,
                reward=reward,
            )
            conf_adjustment = self._bucket_confidence_adjustment(
                label,
                bucket,
                overall_win_rate=overall_win_rate,
                hard_penalty=hard_conf_penalty,
                soft_penalty=soft_conf_penalty,
                reward=conf_reward,
            )
            if sample_status in {"usable", "strong"}:
                usable_bucket_count += 1
            if sample_status == "strong":
                strong_bucket_count += 1
            threshold_adjustment += adjustment
            confidence_adjustment += conf_adjustment
            reasons.extend(bucket_reasons)
        threshold_adjustment += self._signal_gating_tuning_value("threshold_offset", 0.0)
        confidence_adjustment += self._signal_gating_tuning_value("confidence_adjustment", 0.0)
        review_scale = 1.0
        if strong_bucket_count >= 3 and usable_bucket_count >= 5:
            review_scale = 1.0
        elif strong_bucket_count >= 2 or usable_bucket_count >= 4:
            review_scale = 0.8
        elif usable_bucket_count >= 2:
            review_scale = 0.6
        else:
            review_scale = 0.4
        threshold_adjustment *= review_scale
        confidence_adjustment *= review_scale
        threshold_adjustment = max(-6.0, min(15.0, threshold_adjustment))
        confidence_adjustment = max(-4.0, min(2.5, confidence_adjustment))
        effective_threshold = max(45.0, min(90.0, base_threshold + threshold_adjustment))
        calibrated_confidence = max(5.0, min(95.0, confidence_percent + confidence_adjustment))
        review_status = self._calibration_review_status(usable_bucket_count, strong_bucket_count)
        return {
            "enabled": True,
            "review_status": review_status,
            "raw_confidence_percent": round(confidence_percent, 2),
            "calibrated_confidence_percent": round(calibrated_confidence, 2),
            "confidence_adjustment": round(confidence_adjustment, 2),
            "base_confidence_threshold": round(base_threshold, 2),
            "effective_confidence_threshold": round(effective_threshold, 2),
            "threshold_adjustment": round(threshold_adjustment, 2),
            "overall_win_rate_percent": overall_win_rate,
            "review_scale": round(review_scale, 2),
            "setup_family": self._bucket_snapshot(setup_family, setup_bucket),
            "confidence_bucket": self._bucket_snapshot(bucket_key, confidence_bucket),
            "horizon": self._bucket_snapshot(horizon, horizon_bucket),
            "transmission_bias": self._bucket_snapshot(transmission_bias, transmission_bucket),
            "context_regime": self._bucket_snapshot(context_regime, context_regime_bucket),
            "horizon_setup_family": self._bucket_snapshot(horizon_setup_key, horizon_setup_bucket),
            "reasons": list(dict.fromkeys(reasons)),
            "reason_details": self._calibration_reason_details(reasons),
            "review_status_label": self._calibration_review_status_label(review_status),
        }

    @staticmethod
    def _find_calibration_bucket(buckets: object, key: str) -> object | None:
        if not isinstance(buckets, list):
            return None
        for bucket in buckets:
            if getattr(bucket, "key", None) == key:
                return bucket
        return None

    def _bucket_threshold_adjustment(
        self,
        label: str,
        bucket: object | None,
        *,
        overall_win_rate: float | None,
        hard_penalty: float,
        soft_penalty: float,
        reward: float,
    ) -> tuple[float, list[str], str]:
        if bucket is None:
            return 0.0, [], "insufficient"
        resolved_count = int(getattr(bucket, "resolved_count", 0) or 0)
        win_rate = self._safe_rate(getattr(bucket, "win_rate_percent", None))
        sample_status = str(getattr(bucket, "sample_status", "insufficient") or "insufficient")
        if win_rate is None or overall_win_rate is None:
            return 0.0, [f"{label}_insufficient_data"], sample_status
        if sample_status in {"insufficient", "limited"}:
            return 0.0, [f"{label}_insufficient_data"], sample_status
        penalty_multiplier = 1.0 if sample_status == "strong" else 0.75
        reward_multiplier = 1.0 if sample_status == "strong" else 0.5
        if win_rate <= max(35.0, overall_win_rate - 15.0):
            return round(hard_penalty * penalty_multiplier, 2), [f"{label}_underperforming"], sample_status
        if win_rate <= max(45.0, overall_win_rate - 8.0):
            return round(soft_penalty * penalty_multiplier, 2), [f"{label}_soft_underperformance"], sample_status
        if win_rate >= min(80.0, overall_win_rate + 12.0):
            return round(reward * reward_multiplier, 2), [f"{label}_outperforming"], sample_status
        return 0.0, [], sample_status

    def _bucket_confidence_adjustment(
        self,
        label: str,
        bucket: object | None,
        *,
        overall_win_rate: float | None,
        hard_penalty: float,
        soft_penalty: float,
        reward: float,
    ) -> float:
        if bucket is None:
            return 0.0
        win_rate = self._safe_rate(getattr(bucket, "win_rate_percent", None))
        sample_status = str(getattr(bucket, "sample_status", "insufficient") or "insufficient")
        if win_rate is None or overall_win_rate is None or sample_status in {"insufficient", "limited"}:
            return 0.0
        sample_multiplier = 1.0 if sample_status == "strong" else 0.65
        if win_rate <= max(35.0, overall_win_rate - 15.0):
            return round(-hard_penalty * sample_multiplier, 2)
        if win_rate <= max(45.0, overall_win_rate - 8.0):
            return round(-soft_penalty * sample_multiplier, 2)
        if win_rate >= min(80.0, overall_win_rate + 12.0):
            return round(abs(reward) * sample_multiplier, 2)
        return 0.0

    def _bucket_snapshot(self, key: str, bucket: object | None) -> dict[str, object]:
        return {
            "key": key,
            "label": str(getattr(bucket, "label", key.replace("_", " ")) or key.replace("_", " ")) if bucket is not None else key.replace("_", " "),
            "slice_name": str(getattr(bucket, "slice_name", "") or "") if bucket is not None else "",
            "slice_label": str(getattr(bucket, "slice_label", "") or "") if bucket is not None else "",
            "resolved_count": int(getattr(bucket, "resolved_count", 0) or 0) if bucket is not None else 0,
            "win_rate_percent": self._safe_rate(getattr(bucket, "win_rate_percent", None)) if bucket is not None else None,
            "sample_status": str(getattr(bucket, "sample_status", "insufficient") or "insufficient") if bucket is not None else "insufficient",
            "min_required_resolved_count": int(getattr(bucket, "min_required_resolved_count", 0) or 0) if bucket is not None else 0,
            "average_return_5d": round(float(getattr(bucket, "average_return_5d", 0.0) or 0.0), 3) if bucket is not None and getattr(bucket, "average_return_5d", None) is not None else None,
        }

    @staticmethod
    def _calibration_review_status(usable_bucket_count: int, strong_bucket_count: int) -> str:
        if usable_bucket_count == 0:
            return "insufficient_data"
        if strong_bucket_count >= 2 and usable_bucket_count >= 4:
            return "strong_for_gating"
        if usable_bucket_count >= 3:
            return "usable_for_gating"
        return "heuristic_limited"

    def _calibration_transmission_bias(self, transmission_summary: dict[str, object] | None) -> str:
        return self.taxonomy_service.derive_transmission_bias(transmission_summary)

    def _calibration_context_regime(self, transmission_summary: dict[str, object] | None) -> str:
        return self.taxonomy_service.derive_transmission_context_regime(transmission_summary)

    @staticmethod
    def _safe_rate(value: object) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _catalyst_shortlist_score(candidate: _CheapScanCandidate) -> float:
        if candidate.cheap_scan_signal is None:
            return 0.0
        directional_component = abs(float(candidate.cheap_scan_signal.directional_score)) * 100.0
        return round(
            (candidate.attention_score * 0.45)
            + (float(candidate.cheap_scan_signal.breakout_score) * 0.35)
            + (directional_component * 0.2),
            2,
        )

    @staticmethod
    def _minimum_catalyst_proxy_score(horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: 72.0,
            StrategyHorizon.ONE_WEEK: 68.0,
            StrategyHorizon.ONE_MONTH: 64.0,
        }[horizon]
        if ticker_count >= 20:
            return min(90.0, base + 6.0)
        if ticker_count >= 10:
            return min(90.0, base + 3.0)
        return base

    @staticmethod
    def _holding_period_days(horizon: StrategyHorizon) -> int:
        if horizon == StrategyHorizon.ONE_DAY:
            return 1
        if horizon == StrategyHorizon.ONE_MONTH:
            return 20
        return 5

    def _shortlist_limit(self, horizon: StrategyHorizon, ticker_count: int) -> int:
        if ticker_count <= 0:
            return 0
        if horizon == StrategyHorizon.ONE_DAY:
            if ticker_count <= 5:
                return min(ticker_count, 3)
            if ticker_count <= 12:
                return min(ticker_count, 4)
            return min(ticker_count, 5)
        if horizon == StrategyHorizon.ONE_MONTH:
            if ticker_count <= 8:
                return min(ticker_count, 2)
            if ticker_count <= 20:
                return min(ticker_count, 3)
            return min(ticker_count, 4)
        if ticker_count <= 6:
            return min(ticker_count, 2)
        if ticker_count <= 15:
            return min(ticker_count, 3)
        return min(ticker_count, 4)

    def _minimum_shortlist_confidence(self, horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: max(48.0, self.confidence_threshold - 8.0),
            StrategyHorizon.ONE_WEEK: max(45.0, self.confidence_threshold - 12.0),
            StrategyHorizon.ONE_MONTH: max(42.0, self.confidence_threshold - 15.0),
        }[horizon]
        size_bump = 0.0
        if ticker_count >= 20:
            size_bump = 10.0
        elif ticker_count >= 10:
            size_bump = 5.0
        tuning_relief = (
            self._signal_gating_tuning_value("threshold_offset", 0.0) * 0.35
            + self._signal_gating_tuning_value("confidence_adjustment", 0.0) * 0.25
            + self._signal_gating_tuning_value("shortlist_aggressiveness", 1.0) * 1.2
            + self._signal_gating_tuning_value("near_miss_gap_cutoff", 1.5) * 0.5
        )
        return min(95.0, max(35.0, base + size_bump - tuning_relief))

    def _minimum_shortlist_attention(self, horizon: StrategyHorizon, ticker_count: int) -> float:
        base = {
            StrategyHorizon.ONE_DAY: 52.0,
            StrategyHorizon.ONE_WEEK: 45.0,
            StrategyHorizon.ONE_MONTH: 40.0,
        }[horizon]
        size_bump = 0.0
        if ticker_count >= 20:
            size_bump = 12.0
        elif ticker_count >= 10:
            size_bump = 6.0
        tuning_relief = self._signal_gating_tuning_value("shortlist_aggressiveness", 1.0) * 1.0
        return min(95.0, max(35.0, base + size_bump - tuning_relief))
