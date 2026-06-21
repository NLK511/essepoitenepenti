from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.models import RecommendationPlan


class BrokerSteeringEvidenceBuilder:
    """Build fresh thesis-invalidation evidence for broker steering."""

    FRESHNESS_WINDOW = timedelta(days=1)

    def build(self, plan: RecommendationPlan, *, now: datetime | None = None) -> dict[str, object]:
        reference = self._coerce_datetime(now) or datetime.now(timezone.utc)
        if isinstance(plan.signal_breakdown, dict):
            breakdown = plan.signal_breakdown
        elif hasattr(plan.signal_breakdown, "model_dump"):
            breakdown = plan.signal_breakdown.model_dump(mode="json")
        else:
            breakdown = {}
        existing = breakdown.get("steering_evidence") if isinstance(breakdown.get("steering_evidence"), dict) else {}
        computed_at = self._coerce_datetime(existing.get("computed_at") if isinstance(existing, dict) else None) or self._coerce_datetime(plan.computed_at) or reference
        warnings = self._list(existing.get("warnings") if isinstance(existing, dict) else None)
        warnings.extend(self._list(breakdown.get("market_intelligence_warnings")))
        warnings.extend([str(item) for item in plan.warnings])
        conflicts = self._list(existing.get("market_intelligence_conflict_flags") if isinstance(existing, dict) else None)
        conflicts.extend(self._list(breakdown.get("market_intelligence_conflict_flags")))
        market = breakdown.get("market_intelligence") if isinstance(breakdown.get("market_intelligence"), dict) else {}
        conflicts.extend(self._list(market.get("conflict_flags") if isinstance(market, dict) else None))
        freshness_status = "fresh" if computed_at >= reference - self.FRESHNESS_WINDOW else "stale"
        severe_reasons = self._severe_reasons(warnings, conflicts)
        return {
            "ticker": plan.ticker,
            "recommendation_plan_id": plan.id,
            "computed_at": computed_at.isoformat(),
            "warnings": list(dict.fromkeys(warnings)),
            "market_intelligence_conflict_flags": list(dict.fromkeys(conflicts)),
            "actionability": plan.action,
            "calibrated_confidence_percent": self._calibrated_confidence(breakdown),
            "analysis_direction": plan.action,
            "freshness_status": freshness_status,
            "missing_flags": [] if warnings or conflicts else ["no_current_warning_or_conflict_evidence"],
            "severe_invalidation_reasons": severe_reasons if freshness_status == "fresh" else [],
        }

    @classmethod
    def has_severe_invalidation(cls, evidence: dict[str, object]) -> bool:
        if str(evidence.get("freshness_status") or "").strip().lower() != "fresh":
            return False
        reasons = evidence.get("severe_invalidation_reasons")
        return isinstance(reasons, list) and bool(reasons)

    @staticmethod
    def _severe_reasons(warnings: list[str], conflicts: list[str]) -> list[str]:
        reasons: list[str] = []
        for value in [*warnings, *conflicts]:
            normalized = str(value or "").strip().lower().replace(" ", "_")
            if "severe_negative_news" in normalized:
                reasons.append("severe_negative_news")
            if "severe_negative_event" in normalized:
                reasons.append("severe_negative_event")
            if "thesis_invalidated" in normalized:
                reasons.append("thesis_invalidated")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _calibrated_confidence(breakdown: dict[str, object]) -> float | None:
        review = breakdown.get("calibration_review") if isinstance(breakdown.get("calibration_review"), dict) else {}
        value = review.get("calibrated_confidence_percent") if isinstance(review, dict) else None
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item or "").strip()]

    @staticmethod
    def _coerce_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, str) and value.strip():
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if result.tzinfo is None:
            return result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
