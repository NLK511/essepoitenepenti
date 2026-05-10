from __future__ import annotations

from typing import Any

from trade_proposer_app.domain.models import TickerSignalSnapshot


class WatchlistPlanNarrativeService:
    """Build plan narrative, evidence, and risk payloads."""

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def __getattr__(self, name: str) -> Any:
        return getattr(self._orchestration, name)

    def rationale_summary(
        self,
        signal: TickerSignalSnapshot,
        candidate: Any,
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
            driver_label = self.primary_driver_label(transmission_summary)
            if driver_label:
                components.append(f"driver {driver_label}")
            relationship_summary = self.relationship_summary(transmission_summary)
            if relationship_summary:
                components.append(f"relationship {relationship_summary}")
        components.append(f"attention {signal.attention_score:.1f}")
        components.append(f"confidence {signal.confidence_percent:.1f}")
        return " · ".join(component for component in components if component)

    def evidence_summary(
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
            "action_reason_detail": self.action_reason_detail(setup_family, action_reason, transmission_summary=transmission_summary),
            "confidence_components": confidence_components,
            "raw_confidence_percent": calibration.get("raw_confidence_percent"),
            "calibrated_confidence_percent": calibration.get("calibrated_confidence_percent"),
            "confidence_adjustment": calibration.get("confidence_adjustment"),
            "calibration_review": calibration,
            "transmission_summary": transmission_summary or {},
            "entry_style": self.entry_style(setup_family),
            "stop_style": self.stop_style(setup_family),
            "target_style": self.target_style(setup_family),
            "timing_expectation": self.timing_expectation(setup_family, transmission_summary=transmission_summary),
            "evaluation_focus": self.evaluation_focus(setup_family),
            "invalidation_summary": self.invalidation_summary(setup_family, transmission_summary=transmission_summary),
        }

    def no_action_thesis(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        relationship_summary = self.relationship_summary(transmission_summary)
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
            driver = self.primary_driver_label(transmission_summary)
            return f"Detected a {setup_label} structure, but macro and industry transmission remained a headwind to the proposed trade direction{f' ({driver})' if driver else ''}.{relationship_suffix}"
        if action_reason == "context_transmission_contradiction":
            driver = self.primary_driver_label(transmission_summary)
            return f"Detected a {setup_label} structure, but active context evidence was internally contradictory{f' around {driver}' if driver else ''}, so the trade case was not clean enough to promote.{relationship_suffix}"
        if action_reason == "context_quality_blocked":
            return f"Detected a {setup_label} structure, but context quality was blocked and the setup was not tradeable.{relationship_suffix}"
        return f"Signal quality was insufficient for an actionable trade plan.{relationship_suffix}".strip()

    def actionable_thesis(
        self,
        action: str,
        setup_family: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        direction = "bullish" if action == "long" else "bearish"
        setup_label = setup_family.replace("_", " ") if setup_family else "uncategorized"
        driver = self.primary_driver_label(transmission_summary)
        relationship_summary = self.relationship_summary(transmission_summary)
        entry_style = self.entry_style(setup_family).replace("_", " ")
        timing = self.timing_expectation(setup_family, transmission_summary=transmission_summary)
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
    def entry_style(setup_family: str) -> str:
        return {
            "continuation": "pullback_or_reclaim",
            "breakout": "break_or_retest",
            "breakdown": "break_or_failed_retest",
            "mean_reversion": "reversal_confirmation",
            "catalyst_follow_through": "post_catalyst_continuation",
            "macro_beneficiary_loser": "context_aligned_pullback",
        }.get(setup_family, "standard_entry")

    @staticmethod
    def stop_style(setup_family: str) -> str:
        return {
            "continuation": "below_pullback_structure",
            "breakout": "below_break_level_with_buffer",
            "breakdown": "above_failed_retest_level",
            "mean_reversion": "beyond_exhaustion_extreme",
            "catalyst_follow_through": "beyond_catalyst_impulse_level",
            "macro_beneficiary_loser": "below_or_above_exposure_invalidation",
        }.get(setup_family, "generic_structure_stop")

    @staticmethod
    def target_style(setup_family: str) -> str:
        return {
            "continuation": "trend_extension_or_next_level",
            "breakout": "measured_move_or_next_resistance",
            "breakdown": "measured_move_or_next_support",
            "mean_reversion": "range_midpoint_or_moving_average_retest",
            "catalyst_follow_through": "event_follow_through_extension",
            "macro_beneficiary_loser": "context_continuation_extension",
        }.get(setup_family, "generic_target")

    @staticmethod
    def timing_expectation(setup_family: str, *, transmission_summary: dict[str, object] | None = None) -> str:
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
    def evaluation_focus(setup_family: str) -> list[str]:
        return {
            "continuation": ["trend_persistence", "pullback_hold_quality", "stall_rate"],
            "breakout": ["follow_through_speed", "false_break_frequency", "retest_hold_quality"],
            "breakdown": ["support_failure_persistence", "reclaim_risk", "downside_extension_quality"],
            "mean_reversion": ["reversal_confirmation", "reversion_completion_rate", "trend_resumption_risk"],
            "catalyst_follow_through": ["catalyst_decay_speed", "day1_vs_day5_follow_through", "confirmation_quality"],
            "macro_beneficiary_loser": ["transmission_persistence", "context_regime_sensitivity", "sector_sympathy_quality"],
        }.get(setup_family, ["execution_quality", "follow_through", "risk_control"])

    def action_reason_detail(
        self,
        setup_family: str,
        action_reason: str,
        *,
        transmission_summary: dict[str, object] | None = None,
    ) -> str:
        driver = self.primary_driver_label(transmission_summary)
        relationship_summary = self.relationship_summary(transmission_summary)
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
        if action_reason == "context_quality_blocked":
            return f"Context quality was blocked, so the {family_label} setup was not tradeable.{relationship_suffix}"
        return f"The {family_label} setup was reviewed but did not earn promotion.{relationship_suffix}"

    def invalidation_summary(self, setup_family: str, *, transmission_summary: dict[str, object] | None = None) -> str:
        driver = self.primary_driver_label(transmission_summary)
        relationship_summary = self.relationship_summary(transmission_summary)
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
    def primary_driver_label(transmission_summary: dict[str, object] | None) -> str | None:
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
    def matched_ticker_relationships(transmission_summary: dict[str, object] | None) -> list[dict[str, object]]:
        if not isinstance(transmission_summary, dict):
            return []
        raw = transmission_summary.get("matched_ticker_relationships")
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def relationship_label(relationship: dict[str, object]) -> str | None:
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
    def relationship_summary(cls, transmission_summary: dict[str, object] | None) -> str | None:
        labels = [cls.relationship_label(item) for item in cls.matched_ticker_relationships(transmission_summary)[:2]]
        labels = [label for label in labels if label]
        if not labels:
            return None
        return " and ".join(labels)

    def plan_risks(
        self,
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
                if "context_quality_blocked" in conflict_flags:
                    risks.append("context quality is blocked; this setup should not be traded")
                if "context_quality_degraded" in conflict_flags:
                    risks.append("context quality is degraded; follow-through may be noisier")
            decay_state = transmission_summary.get("decay_state")
            if decay_state == "fading":
                risks.append("context support may already be fading for this horizon")
            if self.relationship_summary(transmission_summary):
                risks.append("ticker relationship read-through can break if peer, supplier, or customer confirmation fades")
        if action in {"long", "short"} and warnings == []:
            risks.append("macro/industry transmission should keep confirming the trade after entry")
        if action == "short":
            risks.append("short squeeze risk remains elevated if sentiment reverses")
        return list(dict.fromkeys(risks))
