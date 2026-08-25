from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.models import RecommendationPlan, RunOutput, TickerSignalSnapshot, Watchlist
from trade_proposer_app.services.finite_numbers import finite_float


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


@dataclass(frozen=True)
class _StopLossDistancePolicyResult:
    stop_loss: float | None
    risk_reward_ratio: float | None
    metadata: dict[str, object]


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
            decision_tier = self._claim_decision_tier("discarded")
            decision_metadata = self._decision_tier_metadata(
                decision_tier,
                intended_action=None,
                setup_family=setup_family,
                calibration_review=calibration_review,
                calibrated_confidence=calibrated_confidence,
                risk_reward_ratio=None,
                rejection_reason="deep_analysis_unavailable",
            )
            return RecommendationPlan(
                ticker=candidate.ticker,
                horizon=watchlist.default_horizon,
                action="no_action",
                status="degraded",
                confidence_percent=calibrated_confidence,
                thesis_summary="Deep analysis did not complete; no actionable plan emitted.",
                rationale_summary=rationale,
                warnings=warnings,
                evidence_summary=self._with_decision_tier(
                    o._evidence_summary(summary_text, setup_family, confidence_components, action_reason="deep_analysis_unavailable", calibration_review=calibration_review, transmission_summary=transmission_summary),
                    decision_metadata,
                ),
                signal_breakdown=self._with_decision_tier(
                    o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, shortlisted=shortlisted, shortlist_rank=shortlist_rank, deep_analysis_confidence_percent=deep_analysis_confidence),
                    decision_metadata,
                ),
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
        trade_level_rejection_reason = self._trade_level_rejection_reason(
            intended_action,
            entry_price_low,
            entry_price_high,
            stop_loss,
            take_profit,
        )
        entry_price_low = finite_float(entry_price_low)
        entry_price_high = finite_float(entry_price_high)
        stop_loss = finite_float(stop_loss)
        take_profit = finite_float(take_profit)
        risk_reward_ratio = finite_float(risk_reward_ratio)
        stop_distance_policy = self._apply_minimum_stop_loss_distance(
            intended_action,
            entry_price_low,
            entry_price_high,
            stop_loss,
            take_profit,
            risk_reward_ratio,
        )
        stop_loss = stop_distance_policy.stop_loss
        risk_reward_ratio = stop_distance_policy.risk_reward_ratio
        stop_policy_metadata = stop_distance_policy.metadata.get("stop_loss_distance_policy")
        if isinstance(stop_policy_metadata, dict) and stop_policy_metadata.get("stop_loss_widened"):
            warnings.append("stop_loss_widened_for_minimum_distance")

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
        if action != "no_action" and trade_level_rejection_reason is not None:
            action = "no_action"
            action_reason = trade_level_rejection_reason
            warnings.append(trade_level_rejection_reason)

        if action == "no_action":
            preferred_tier = self._preferred_non_execution_tier(
                action_reason=action_reason,
                intended_action=intended_action,
                setup_family=setup_family,
                calibrated_confidence=calibrated_confidence,
            )
            decision_tier = self._claim_decision_tier(preferred_tier)
            decision_metadata = self._decision_tier_metadata(
                decision_tier,
                intended_action=intended_action,
                setup_family=setup_family,
                calibration_review=calibration_review,
                calibrated_confidence=calibrated_confidence,
                risk_reward_ratio=risk_reward_ratio,
                rejection_reason=action_reason,
            )
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
                evidence_summary=self._with_decision_tier(
                    self._with_stop_loss_policy(
                        o._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
                        stop_distance_policy.metadata,
                    ),
                    decision_metadata,
                ),
                signal_breakdown=self._with_decision_tier(
                    self._with_stop_loss_policy(
                        o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, intended_action=intended_action, shortlisted=True, shortlist_rank=shortlist_rank, deep_analysis_confidence_percent=deep_analysis_confidence),
                        stop_distance_policy.metadata,
                    ),
                    decision_metadata,
                ),
                computed_at=signal.computed_at,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )

        decision_tier = self._claim_decision_tier("execution_candidate")
        decision_metadata = self._decision_tier_metadata(
            decision_tier,
            intended_action=intended_action,
            setup_family=setup_family,
            calibration_review=calibration_review,
            calibrated_confidence=calibrated_confidence,
            risk_reward_ratio=risk_reward_ratio,
            rejection_reason=None,
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
            evidence_summary=self._with_decision_tier(
                self._with_stop_loss_policy(
                    o._evidence_summary(summary_text, setup_family, confidence_components, action_reason=action_reason, calibration_review=calibration_review, transmission_summary=transmission_summary),
                    stop_distance_policy.metadata,
                ),
                decision_metadata,
            ),
            signal_breakdown=self._with_decision_tier(
                self._with_stop_loss_policy(
                    o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, intended_action=intended_action, shortlisted=True, shortlist_rank=shortlist_rank, deep_analysis_confidence_percent=deep_analysis_confidence),
                    stop_distance_policy.metadata,
                ),
                decision_metadata,
            ),
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

    @staticmethod
    def _trade_level_rejection_reason(
        intended_action: str | None,
        entry_price_low: object,
        entry_price_high: object,
        stop_loss: object,
        take_profit: object,
    ) -> str | None:
        if intended_action not in {"long", "short"}:
            return None
        raw_values = (entry_price_low, entry_price_high, stop_loss, take_profit)
        finite_values = tuple(finite_float(value) for value in raw_values)
        if any(raw is not None and finite is None for raw, finite in zip(raw_values, finite_values)):
            return "non_finite_trade_levels"
        low, high, stop, target = finite_values
        if low is None and high is None:
            return "missing_trade_levels"
        if stop is None or target is None:
            return "missing_trade_levels"
        entry = (low + high) / 2.0 if low is not None and high is not None else low if low is not None else high
        if entry is None or entry <= 0:
            return "missing_trade_levels"
        if intended_action == "long" and not (stop < entry < target):
            return "invalid_trade_levels"
        if intended_action == "short" and not (target < entry < stop):
            return "invalid_trade_levels"
        return None

    def _apply_minimum_stop_loss_distance(
        self,
        intended_action: str | None,
        entry_price_low: float | None,
        entry_price_high: float | None,
        stop_loss: float | None,
        take_profit: float | None,
        risk_reward_ratio: float | None,
    ) -> _StopLossDistancePolicyResult:
        if intended_action not in {"long", "short"} or stop_loss is None:
            return _StopLossDistancePolicyResult(stop_loss, risk_reward_ratio, {})
        entry = self._entry_reference(entry_price_low, entry_price_high)
        if entry is None or entry <= 0:
            return _StopLossDistancePolicyResult(stop_loss, risk_reward_ratio, {})
        min_distance_pct = max(
            0.0,
            self._orchestration._plan_generation_tuning_value(
                "global.minimum_stop_loss_distance_percent", 2.0
            ),
        )
        if min_distance_pct <= 0:
            return _StopLossDistancePolicyResult(stop_loss, risk_reward_ratio, {})
        original_risk_distance = abs(entry - stop_loss)
        minimum_risk_distance = entry * (min_distance_pct / 100.0)
        if original_risk_distance >= minimum_risk_distance:
            return _StopLossDistancePolicyResult(
                stop_loss,
                risk_reward_ratio,
                {
                    "stop_loss_distance_policy": {
                        "minimum_stop_loss_distance_percent": round(min_distance_pct, 4),
                        "stop_loss_widened": False,
                        "entry_reference": round(entry, 4),
                        "risk_distance": round(original_risk_distance, 4),
                    }
                },
            )

        adjusted_stop = round(
            entry - minimum_risk_distance
            if intended_action == "long"
            else entry + minimum_risk_distance,
            4,
        )
        adjusted_risk_distance = abs(entry - adjusted_stop)
        position_size_multiplier = (
            original_risk_distance / adjusted_risk_distance
            if adjusted_risk_distance > 0
            else 1.0
        )
        position_size_multiplier = max(0.0, min(1.0, position_size_multiplier))
        metadata = {
            "stop_loss_distance_policy": {
                "minimum_stop_loss_distance_percent": round(min_distance_pct, 4),
                "stop_loss_widened": True,
                "entry_reference": round(entry, 4),
                "original_stop_loss": round(stop_loss, 4),
                "adjusted_stop_loss": adjusted_stop,
                "original_risk_distance": round(original_risk_distance, 4),
                "adjusted_risk_distance": round(adjusted_risk_distance, 4),
                "position_size_multiplier": round(position_size_multiplier, 6),
            },
            "position_size_multiplier": round(position_size_multiplier, 6),
        }
        return _StopLossDistancePolicyResult(
            adjusted_stop,
            self._recompute_risk_reward_ratio(entry, adjusted_stop, take_profit),
            metadata,
        )

    @staticmethod
    def _entry_reference(
        entry_price_low: float | None, entry_price_high: float | None
    ) -> float | None:
        if entry_price_low is not None and entry_price_high is not None:
            return (entry_price_low + entry_price_high) / 2.0
        return entry_price_low if entry_price_low is not None else entry_price_high

    @staticmethod
    def _recompute_risk_reward_ratio(
        entry: float, stop_loss: float | None, take_profit: float | None
    ) -> float | None:
        if stop_loss is None or take_profit is None:
            return None
        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None
        return round(abs(take_profit - entry) / risk, 4)

    def _preferred_non_execution_tier(
        self,
        *,
        action_reason: str,
        intended_action: str | None,
        setup_family: str,
        calibrated_confidence: float,
    ) -> str:
        if intended_action not in {"long", "short"}:
            return "discarded"
        threshold_reasons = {
            "below_action_confidence_threshold",
            "below_calibrated_action_threshold",
            "context_transmission_headwind",
        }
        if action_reason not in threshold_reasons:
            return "discarded"
        o = self._orchestration
        if calibrated_confidence >= o._research_plan_floor_percent(setup_family):
            return "research_plan"
        if calibrated_confidence >= o._shadow_tracking_floor_percent():
            return "shadow_observation"
        return "discarded"

    def _claim_decision_tier(self, preferred_tier: str) -> str:
        claim = getattr(self._orchestration, "_claim_plan_decision_tier", None)
        if callable(claim):
            return str(claim(preferred_tier))
        return preferred_tier

    def _decision_tier_metadata(
        self,
        decision_tier: str,
        *,
        intended_action: str | None,
        setup_family: str,
        calibration_review: dict[str, object],
        calibrated_confidence: float,
        risk_reward_ratio: float | None,
        rejection_reason: str | None,
    ) -> dict[str, object]:
        o = self._orchestration
        execution_floor = o._execution_confidence_floor_percent()
        research_floor = o._research_plan_floor_percent(setup_family)
        shadow_floor = o._shadow_tracking_floor_percent()
        calibration_source = str(calibration_review.get("calibration_source") or "broker_only").strip() or "broker_only"
        execution_eligible = decision_tier == "execution_candidate"
        return {
            "decision_tier": decision_tier,
            "intended_action": intended_action,
            "execution_eligible": execution_eligible,
            "research_eligible": decision_tier == "research_plan",
            "shadow_eligible": decision_tier == "shadow_observation",
            "floor_source": "broker_only_calibrated_probability",
            "execution_floor_percent": round(float(execution_floor), 2),
            "research_floor_percent": round(float(research_floor), 2),
            "shadow_tracking_floor_percent": round(float(shadow_floor), 2),
            "calibration_source": calibration_source,
            "calibrated_probability_percent": round(float(calibrated_confidence), 2),
            "expected_value_estimate": None,
            "risk_reward_ratio": risk_reward_ratio,
            "rejection_reason": rejection_reason,
            "would_have_executed_under_policy_version": bool(execution_eligible),
            "policy_version": "research_actionability_floor_v1",
        }

    @staticmethod
    def _with_decision_tier(payload: dict[str, object], decision_metadata: dict[str, object]) -> dict[str, object]:
        enriched = dict(payload)
        enriched.update(decision_metadata)
        thresholds = enriched.get("decision_thresholds")
        if isinstance(thresholds, dict):
            thresholds = dict(thresholds)
            thresholds["execution_floor_percent"] = decision_metadata["execution_floor_percent"]
            thresholds["research_floor_percent"] = decision_metadata["research_floor_percent"]
            thresholds["shadow_tracking_floor_percent"] = decision_metadata["shadow_tracking_floor_percent"]
            enriched["decision_thresholds"] = thresholds
        return enriched

    @staticmethod
    def _with_stop_loss_policy(
        payload: dict[str, object], metadata: dict[str, object]
    ) -> dict[str, object]:
        if not metadata:
            return payload
        enriched = dict(payload)
        enriched.update(metadata)
        return enriched

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
        preferred_tier = "shadow_observation" if calibrated_confidence >= o._shadow_tracking_floor_percent() else "discarded"
        decision_tier = self._claim_decision_tier(preferred_tier)
        decision_metadata = self._decision_tier_metadata(
            decision_tier,
            intended_action=None,
            setup_family=setup_family,
            calibration_review=calibration_review,
            calibrated_confidence=calibrated_confidence,
            risk_reward_ratio=None,
            rejection_reason="not_shortlisted",
        )
        return RecommendationPlan(
            ticker=candidate.ticker,
            horizon=watchlist.default_horizon,
            action="no_action",
            status="ok" if not signal.warnings else "partial",
            confidence_percent=calibrated_confidence,
            thesis_summary=reason,
            rationale_summary=o._rationale_summary(signal, candidate, setup_family, transmission_summary),
            warnings=list(signal.warnings),
            evidence_summary=self._with_decision_tier(
                o._evidence_summary(candidate.indicator_summary, setup_family, confidence_components, action_reason="not_shortlisted", calibration_review=calibration_review, transmission_summary=transmission_summary),
                decision_metadata,
            ),
            signal_breakdown=self._with_decision_tier(
                o._signal_breakdown(signal, setup_family=setup_family, confidence_components=confidence_components, calibration_review=calibration_review, transmission_summary=transmission_summary, shortlisted=False, shortlist_rank=None),
                decision_metadata,
            ),
            computed_at=signal.computed_at,
            run_id=run_id,
            job_id=job_id,
            watchlist_id=watchlist.id,
            ticker_signal_snapshot_id=signal.id,
        )
