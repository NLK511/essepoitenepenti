from __future__ import annotations

from typing import Any

from trade_proposer_app.domain.models import RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist


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
        analysis = o._analysis_payload(deep_output)
        summary_text = o._pluck(analysis, "summary", "text") or signal.source_breakdown.get("cheap_scan_summary") or ""
        setup_family = o._plan_setup_family(signal, analysis, candidate)
        confidence_components = o._plan_confidence_components(signal, analysis, candidate)
        transmission_summary = o._transmission_summary(signal, analysis, candidate)
        raw_plan_confidence = o._plan_gate_confidence(signal, deep_output=deep_output, deep_error=deep_error)
        deep_analysis_confidence = o._deep_analysis_confidence(deep_output, deep_error=deep_error)
        calibration_review = o._calibration_review(
            calibration_summary,
            setup_family,
            raw_plan_confidence,
            horizon=watchlist.default_horizon.value,
            transmission_summary=transmission_summary,
        )
        calibrated_confidence = float(calibration_review.get("calibrated_confidence_percent", raw_plan_confidence) or raw_plan_confidence)
        rationale = o._rationale_summary(signal, candidate, setup_family, transmission_summary)
        warnings = list(signal.warnings)
        shortlisted = bool(signal.diagnostics.get("shortlisted"))
        shortlist_rank = signal.diagnostics.get("shortlist_rank") if isinstance(signal.diagnostics.get("shortlist_rank"), int) else None
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
        effective_threshold = float(calibration_review.get("effective_confidence_threshold", o.confidence_threshold))
        effective_threshold = min(effective_threshold, float(o.action_confidence_threshold))
        calibrated_confidence = float(calibration_review.get("calibrated_confidence_percent", raw_plan_confidence) or raw_plan_confidence)

        entry_price_low, entry_price_high, stop_loss, take_profit, risk_reward_ratio = None, None, None, None, None
        if intended_action:
            entry_price_low, entry_price_high, stop_loss, take_profit = o._family_adjusted_trade_levels(
                recommendation,
                setup_family=setup_family,
                action=intended_action,
                transmission_summary=transmission_summary,
            )
            risk_reward_ratio = o._risk_reward_ratio(recommendation)

        context_quality_status = o._trade_context_quality_status(transmission_summary)
        if context_quality_status == "blocked":
            warnings.append("context quality is blocked; the setup is not tradeable")
            action = "no_action"
            action_reason = "context_quality_blocked"
        else:
            if context_quality_status == "degraded":
                warnings.append("context quality is degraded; trade with caution")
            if direction == "short" and not watchlist.allow_shorts:
                warnings.append("watchlist does not allow shorts")
                action = "no_action"
                action_reason = "shorts_disabled"
            elif o.trade_decision_policy is not None and intended_action and not o.trade_decision_policy.action_allowed(intended_action):
                warnings.append("active trade decision policy blocks this action")
                action = "no_action"
                action_reason = "trade_policy_action_blocked"
            elif o.trade_decision_policy is not None and not o.trade_decision_policy.setup_family_allowed(setup_family):
                warnings.append("active trade decision policy blocks this setup family")
                action = "no_action"
                action_reason = "trade_policy_setup_family_blocked"
            elif calibrated_confidence < effective_threshold:
                action = "no_action"
                action_reason = "below_calibrated_action_threshold" if effective_threshold > o.confidence_threshold or calibrated_confidence != raw_plan_confidence else "below_action_confidence_threshold"
            elif direction not in {"long", "short"}:
                action = "no_action"
                action_reason = "direction_not_actionable"
            elif o._should_block_for_transmission_contradiction(transmission_summary, calibrated_confidence, effective_threshold):
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
