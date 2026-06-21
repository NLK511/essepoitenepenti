from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.models import RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist


@dataclass(frozen=True)
class _PlanFramingContext:
    analysis: dict[str, Any]
    summary_text: str
    setup_family: str
    confidence_components: dict[str, float]
    transmission_summary: dict[str, object]
    raw_plan_confidence: float
    deep_analysis_confidence: float | None
    calibration_review: dict[str, object]
    calibrated_confidence: float
    rationale: str
    warnings: list[str]
    shortlisted: bool
    shortlist_rank: int | None


class WatchlistPlanFramingService:
    """Build persisted recommendation-plan payloads for watchlist orchestration.

    This is intentionally a thin extraction around the existing orchestration
    helpers. The first refactor goal is to isolate the payload-building seam
    without changing the operator-facing plan contract frozen by parity tests.
    """

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def build_plan_from_signal(
        self,
        watchlist: Watchlist,
        candidate: Any,
        signal: TickerSignalSnapshot,
        *,
        deep_output: RunOutput | None,
        deep_error: str | None,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
    ) -> RecommendationPlan:
        o = self._orchestration
        context = self._framing_context(
            watchlist,
            candidate,
            signal,
            deep_output=deep_output,
            deep_error=deep_error,
            calibration_summary=calibration_summary,
        )
        summary_text = context.summary_text
        setup_family = context.setup_family
        confidence_components = context.confidence_components
        transmission_summary = context.transmission_summary
        raw_plan_confidence = context.raw_plan_confidence
        deep_analysis_confidence = context.deep_analysis_confidence
        calibration_review = context.calibration_review
        calibrated_confidence = context.calibrated_confidence
        rationale = context.rationale
        warnings = context.warnings
        shortlisted = context.shortlisted
        shortlist_rank = context.shortlist_rank
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
                evidence_summary=o._evidence_summary(summary_text, setup_family, confidence_components, action_reason="deep_analysis_unavailable", calibration_review=calibration_review, transmission_summary=transmission_summary),
                signal_breakdown=o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, shortlisted=shortlisted, shortlist_rank=shortlist_rank, deep_analysis_confidence_percent=deep_analysis_confidence),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        recommendation = deep_output.recommendation
        direction = o._normalize_direction(recommendation.direction)
        intended_action = direction if direction in {"long", "short"} else None
        action_reason = "actionable_setup"
        effective_threshold = self._effective_action_threshold(calibration_review)

        entry_price_low, entry_price_high, stop_loss, take_profit, risk_reward_ratio = self._trade_levels(
            recommendation,
            signal,
            setup_family=setup_family,
            intended_action=intended_action,
            transmission_summary=transmission_summary,
        )

        action, action_reason = self._resolve_action(
            watchlist,
            direction=direction,
            intended_action=intended_action,
            setup_family=setup_family,
            transmission_summary=transmission_summary,
            calibrated_confidence=calibrated_confidence,
            raw_plan_confidence=raw_plan_confidence,
            effective_threshold=effective_threshold,
            warnings=warnings,
        )

        if action == "no_action":
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action=action,
                status="degraded" if action_reason == "context_quality_blocked" else ("ok" if not warnings else "partial"),
                confidence_percent=calibrated_confidence,
                entry_price_low=entry_price_low,
                entry_price_high=entry_price_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                holding_period_days=o._holding_period_days(watchlist.default_horizon) if intended_action else None,
                risk_reward_ratio=risk_reward_ratio,
                thesis_summary=o._no_action_thesis(setup_family, action_reason, transmission_summary=transmission_summary),
                rationale_summary=rationale,
                warnings=list(dict.fromkeys(warnings)),
                evidence_summary=o._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
                signal_breakdown=o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, intended_action=intended_action, shortlisted=True, shortlist_rank=shortlist_rank, deep_analysis_confidence_percent=deep_analysis_confidence),
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
            holding_period_days=o._holding_period_days(watchlist.default_horizon),
            risk_reward_ratio=risk_reward_ratio,
            thesis_summary=summary_text or o._actionable_thesis(action, setup_family, transmission_summary=transmission_summary),
            rationale_summary=rationale,
            risks=o._plan_risks(warnings, setup_family, action, transmission_summary),
            warnings=list(dict.fromkeys(warnings)),
            evidence_summary=o._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
            signal_breakdown=o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, intended_action=intended_action, shortlisted=True, shortlist_rank=shortlist_rank, deep_analysis_confidence_percent=deep_analysis_confidence),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
        )

    def _framing_context(
        self,
        watchlist: Watchlist,
        candidate: Any,
        signal: TickerSignalSnapshot,
        *,
        deep_output: RunOutput | None,
        deep_error: str | None,
        calibration_summary: object | None,
    ) -> _PlanFramingContext:
        o = self._orchestration
        analysis = o._analysis_payload(deep_output)
        setup_family = o._plan_setup_family(signal, analysis, candidate)
        confidence_components = o._plan_confidence_components(signal, analysis, candidate)
        transmission_summary = o._transmission_summary(signal, analysis, candidate)
        raw_plan_confidence = o._plan_gate_confidence(signal, deep_output=deep_output, deep_error=deep_error)
        calibration_review = o._calibration_review(
            calibration_summary,
            setup_family,
            raw_plan_confidence,
            horizon=watchlist.default_horizon.value,
            transmission_summary=transmission_summary,
        )
        return _PlanFramingContext(
            analysis=analysis,
            summary_text=o._pluck(analysis, "summary", "text") or signal.source_breakdown.get("cheap_scan_summary") or "",
            setup_family=setup_family,
            confidence_components=confidence_components,
            transmission_summary=transmission_summary,
            raw_plan_confidence=raw_plan_confidence,
            deep_analysis_confidence=o._deep_analysis_confidence(deep_output, deep_error=deep_error),
            calibration_review=calibration_review,
            calibrated_confidence=float(calibration_review.get("calibrated_confidence_percent", raw_plan_confidence) or raw_plan_confidence),
            rationale=o._rationale_summary(signal, candidate, setup_family, transmission_summary),
            warnings=list(signal.warnings),
            shortlisted=bool(signal.diagnostics.get("shortlisted")),
            shortlist_rank=signal.diagnostics.get("shortlist_rank") if isinstance(signal.diagnostics.get("shortlist_rank"), int) else None,
        )

    def _resolve_action(
        self,
        watchlist: Watchlist,
        *,
        direction: str,
        intended_action: str | None,
        setup_family: str,
        transmission_summary: dict[str, object],
        calibrated_confidence: float,
        raw_plan_confidence: float,
        effective_threshold: float,
        warnings: list[str],
    ) -> tuple[str, str]:
        o = self._orchestration
        context_quality_status = o._trade_context_quality_status(transmission_summary)
        if context_quality_status == "blocked":
            warnings.append("context quality is blocked; the setup is not tradeable")
            return "no_action", "context_quality_blocked"
        if context_quality_status == "degraded":
            warnings.append("context quality is degraded; trade with caution")
        if direction == "short" and not watchlist.allow_shorts:
            warnings.append("watchlist does not allow shorts")
            return "no_action", "shorts_disabled"
        if o.trade_decision_policy is not None and intended_action and not o.trade_decision_policy.action_allowed(intended_action):
            warnings.append("active trade decision policy blocks this action")
            return "no_action", "trade_policy_action_blocked"
        if o.trade_decision_policy is not None and not o.trade_decision_policy.setup_family_allowed(setup_family):
            warnings.append("active trade decision policy blocks this setup family")
            return "no_action", "trade_policy_setup_family_blocked"
        if calibrated_confidence < effective_threshold:
            reason = "below_calibrated_action_threshold" if effective_threshold > o.confidence_threshold or calibrated_confidence != raw_plan_confidence else "below_action_confidence_threshold"
            return "no_action", reason
        if direction not in {"long", "short"}:
            return "no_action", "direction_not_actionable"
        if o._should_block_for_transmission_contradiction(transmission_summary, calibrated_confidence, effective_threshold):
            return "no_action", "context_transmission_contradiction"
        if transmission_summary.get("context_bias") == "headwind" and calibrated_confidence < min(95.0, effective_threshold + 5.0):
            return "no_action", "context_transmission_headwind"
        return direction, "actionable_setup"

    def _effective_action_threshold(self, calibration_review: dict[str, object]) -> float:
        o = self._orchestration
        confidence_floor = o._plan_generation_tuning_value("global.actionable_confidence_floor_percent", 60.0)
        effective_threshold = float(calibration_review.get("effective_confidence_threshold", o.confidence_threshold))
        effective_threshold = min(effective_threshold, float(o.action_confidence_threshold))
        return max(effective_threshold, confidence_floor)

    def _trade_levels(
        self,
        recommendation: Any,
        signal: TickerSignalSnapshot,
        *,
        setup_family: str,
        intended_action: str | None,
        transmission_summary: dict[str, object],
    ) -> tuple[object, object, object, object, object]:
        if not intended_action:
            return None, None, None, None, None
        o = self._orchestration
        cheap_scan_component_scores = signal.diagnostics.get("cheap_scan_component_scores") if isinstance(signal.diagnostics.get("cheap_scan_component_scores"), dict) else {}
        entry_price_low, entry_price_high, stop_loss, take_profit = o._family_adjusted_trade_levels(
            recommendation,
            setup_family=setup_family,
            action=intended_action,
            transmission_summary=transmission_summary,
            volatility_score=cheap_scan_component_scores.get("volatility_score") if isinstance(cheap_scan_component_scores.get("volatility_score"), (int, float)) else None,
        )
        return entry_price_low, entry_price_high, stop_loss, take_profit, o._risk_reward_ratio(recommendation)

    def build_no_action_plan(
        self,
        watchlist: Watchlist,
        candidate: Any,
        signal: TickerSignalSnapshot,
        *,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
        reason: str,
    ) -> RecommendationPlan:
        o = self._orchestration
        setup_family = o._cheap_scan_setup_family(candidate)
        confidence_components = o._plan_confidence_components(signal, {}, candidate)
        transmission_summary = o._transmission_summary(signal, {}, candidate)
        calibration_review = o._calibration_review(
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
            rationale_summary=o._rationale_summary(signal, candidate, setup_family, transmission_summary),
            warnings=list(signal.warnings),
            evidence_summary=o._evidence_summary(candidate.indicator_summary, setup_family, confidence_components, action_reason="not_shortlisted", calibration_review=calibration_review, transmission_summary=transmission_summary),
            signal_breakdown=o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, shortlisted=False, shortlist_rank=None),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
        )
