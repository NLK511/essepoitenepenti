from __future__ import annotations

from typing import Any

from trade_proposer_app.domain.models import RecommendationDecisionSample, RecommendationPlan, TickerSignalSnapshot, Watchlist


class WatchlistDecisionSampleService:
    """Persist audit/tuning decision samples for watchlist orchestration.

    The service is a thin extraction over existing orchestration helper methods
    so sample semantics stay aligned with persisted recommendation-plan payloads.
    """

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def record_non_shortlisted_decision_sample(
        self,
        watchlist: Watchlist,
        candidate: Any,
        *,
        signal: TickerSignalSnapshot,
        calibration_summary: object | None,
        job_id: int | None,
        run_id: int | None,
        shortlist_decision: dict[str, object] | None,
    ) -> None:
        o = self._orchestration
        if o.decision_samples is None or signal.id is None:
            return
        setup_family = o._cheap_scan_setup_family(candidate, signal=signal)
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
        effective_threshold = self.float_from_mapping(calibration_review, "effective_confidence_threshold")
        confidence_gap = None
        if effective_threshold is not None:
            confidence_gap = round(calibrated_confidence - effective_threshold, 2)
        signal_breakdown = o._signal_breakdown(
            signal,
            setup_family=setup_family,
            confidence_components=confidence_components,
            calibration_review=calibration_review,
            transmission_summary=transmission_summary,
            shortlisted=False,
            shortlist_rank=None,
        )
        evidence_summary = o._evidence_summary(
            candidate.indicator_summary,
            setup_family,
            confidence_components,
            action_reason="not_shortlisted",
            calibration_review=calibration_review,
            transmission_summary=transmission_summary,
        )
        shortlist_payload = {
            "shortlisted": False,
            "shortlist_rank": None,
            "shortlist_decision": shortlist_decision or {},
            "shortlist_reasons": signal.diagnostics.get("shortlist_reasons", []),
            "shortlist_reason_details": signal.diagnostics.get("shortlist_reason_details", []),
        }
        decision_type = self.decision_type("no_action", "ok", "not_shortlisted", confidence_gap, shortlisted=False)
        review_priority = self.review_priority(decision_type, confidence_gap=confidence_gap, shortlisted=False, status="ok")
        o.decision_samples.upsert_sample(
            RecommendationDecisionSample(
                recommendation_plan_id=None,
                ticker=signal.ticker,
                horizon=watchlist.default_horizon.value,
                action="no_action",
                decision_type=decision_type,
                decision_reason="not_shortlisted",
                shortlisted=False,
                shortlist_rank=None,
                shortlist_decision=shortlist_payload,
                confidence_percent=signal.confidence_percent,
                calibrated_confidence_percent=calibrated_confidence,
                effective_threshold_percent=effective_threshold,
                confidence_gap_percent=confidence_gap,
                setup_family=setup_family,
                transmission_bias=str(signal_breakdown.get("transmission_bias") or "").strip() or None,
                context_regime=str(o._pluck(signal_breakdown, "calibration_review", "context_regime", "key") or "").strip() or None,
                review_priority=review_priority,
                decision_context={
                    "status": "ok",
                    "warnings": list(signal.warnings),
                    "shortlisted": False,
                    "shortlist_rank": None,
                    "shortlist_decision": shortlist_decision or {},
                    "confidence_percent": signal.confidence_percent,
                    "calibrated_confidence_percent": calibrated_confidence,
                    "effective_threshold_percent": effective_threshold,
                    "confidence_gap_percent": confidence_gap,
                    "action_reason": "not_shortlisted",
                    "review_priority": review_priority,
                },
                signal_breakdown=signal_breakdown,
                evidence_summary=evidence_summary,
                run_id=run_id,
                job_id=job_id,
                watchlist_id=watchlist.id,
                ticker_signal_snapshot_id=signal.id,
            )
        )

    def record_decision_sample(
        self,
        plan: RecommendationPlan,
        candidate: Any,
        *,
        signal: TickerSignalSnapshot,
        shortlisted: bool,
        shortlist_rank: int | None,
        shortlist_decision: dict[str, object] | None,
    ) -> None:
        o = self._orchestration
        if o.decision_samples is None or plan.id is None:
            return
        signal_breakdown = self.mapping(plan.signal_breakdown)
        evidence_summary = self.mapping(plan.evidence_summary)
        calibration_review = self.mapping(signal_breakdown.get("calibration_review"))
        effective_threshold = self.float_from_mapping(calibration_review, "effective_confidence_threshold")
        calibrated_confidence = self.float_from_mapping(calibration_review, "calibrated_confidence_percent")
        confidence_gap = None
        if calibrated_confidence is not None and effective_threshold is not None:
            confidence_gap = round(calibrated_confidence - effective_threshold, 2)
        action_reason = str(
            evidence_summary.get("action_reason")
            or evidence_summary.get("action_reason_label")
            or plan.action
            or "unknown"
        ).strip()
        decision_type = self.decision_type(plan.action, plan.status, action_reason, confidence_gap, shortlisted=shortlisted)
        review_priority = self.review_priority(decision_type, confidence_gap=confidence_gap, shortlisted=shortlisted, status=plan.status)
        shortlist_payload = {
            "shortlisted": shortlisted,
            "shortlist_rank": shortlist_rank,
            "shortlist_decision": shortlist_decision or {},
            "shortlist_reasons": signal.diagnostics.get("shortlist_reasons", []),
            "shortlist_reason_details": signal.diagnostics.get("shortlist_reason_details", []),
        }
        o.decision_samples.upsert_sample(
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
                context_regime=str(o._pluck(signal_breakdown, "calibration_review", "context_regime", "key") or "").strip() or None,
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
    def mapping(payload: object | None) -> dict[str, object]:
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
    def float_from_mapping(payload: object, key: str) -> float | None:
        if not hasattr(payload, "get"):
            return None
        value = payload.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def decision_type(
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
    def review_priority(
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
