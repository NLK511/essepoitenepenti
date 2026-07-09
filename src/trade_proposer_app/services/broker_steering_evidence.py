from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.models import RecommendationPlan, TickerSignalSnapshot


class BrokerSteeringEvidenceBuilder:
    """Build fresh thesis-invalidation evidence for broker steering."""

    FRESHNESS_WINDOW = timedelta(days=1)

    def build(
        self,
        plan: RecommendationPlan,
        *,
        now: datetime | None = None,
        latest_signal: TickerSignalSnapshot | None = None,
    ) -> dict[str, object]:
        reference = self._coerce_datetime(now) or datetime.now(timezone.utc)
        if isinstance(plan.signal_breakdown, dict):
            breakdown = plan.signal_breakdown
        elif hasattr(plan.signal_breakdown, "model_dump"):
            breakdown = plan.signal_breakdown.model_dump(mode="json")
        else:
            breakdown = {}
        existing = breakdown.get("steering_evidence") if isinstance(breakdown.get("steering_evidence"), dict) else {}
        signal_payload = self._signal_payload(latest_signal)
        signal_computed_at = self._coerce_datetime(signal_payload.get("computed_at"))
        computed_at = signal_computed_at or self._coerce_datetime(existing.get("computed_at") if isinstance(existing, dict) else None) or self._coerce_datetime(plan.computed_at) or reference
        warnings = self._list(existing.get("warnings") if isinstance(existing, dict) else None)
        warnings.extend(self._list(breakdown.get("market_intelligence_warnings")))
        warnings.extend(self._list(signal_payload.get("warnings")))
        warnings.extend(self._list(signal_payload.get("market_intelligence_warnings")))
        warnings.extend([str(item) for item in plan.warnings])
        conflicts = self._list(existing.get("market_intelligence_conflict_flags") if isinstance(existing, dict) else None)
        conflicts.extend(self._list(breakdown.get("market_intelligence_conflict_flags")))
        conflicts.extend(self._list(signal_payload.get("market_intelligence_conflict_flags")))
        market = breakdown.get("market_intelligence") if isinstance(breakdown.get("market_intelligence"), dict) else {}
        conflicts.extend(self._list(market.get("conflict_flags") if isinstance(market, dict) else None))
        signal_market = signal_payload.get("market_intelligence") if isinstance(signal_payload.get("market_intelligence"), dict) else {}
        conflicts.extend(self._list(signal_market.get("conflict_flags") if isinstance(signal_market, dict) else None))
        freshness_status = "fresh" if computed_at >= reference - self.FRESHNESS_WINDOW else "stale"
        severe_reasons = self._severe_reasons(warnings, conflicts)
        actionability = self._current_actionability(signal_payload, latest_signal)
        analysis_direction = self._current_analysis_direction(signal_payload, latest_signal)
        return {
            "ticker": plan.ticker,
            "recommendation_plan_id": plan.id,
            "computed_at": computed_at.isoformat(),
            "source": "ticker_signal" if latest_signal is not None else "plan_fallback",
            "ticker_signal_snapshot_id": latest_signal.id if latest_signal is not None else None,
            "warnings": list(dict.fromkeys(warnings)),
            "market_intelligence_conflict_flags": list(dict.fromkeys(conflicts)),
            "actionability": actionability if freshness_status == "fresh" else None,
            "calibrated_confidence_percent": self._signal_calibrated_confidence(signal_payload) if freshness_status == "fresh" else None,
            "confidence_percent": float(latest_signal.confidence_percent) if latest_signal is not None and freshness_status == "fresh" else None,
            "analysis_direction": analysis_direction if freshness_status == "fresh" else None,
            "freshness_status": freshness_status,
            "missing_flags": [] if latest_signal is not None or warnings or conflicts else ["no_current_warning_or_conflict_evidence"],
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

    @classmethod
    def _signal_payload(cls, signal: TickerSignalSnapshot | None) -> dict[str, object]:
        if signal is None:
            return {}
        diagnostics = signal.diagnostics.model_dump(mode="json") if hasattr(signal.diagnostics, "model_dump") else {}
        source_breakdown = signal.source_breakdown.model_dump(mode="json") if hasattr(signal.source_breakdown, "model_dump") else {}
        return {
            **source_breakdown,
            **diagnostics,
            "computed_at": signal.computed_at,
            "direction": signal.direction,
            "confidence_percent": signal.confidence_percent,
            "warnings": signal.warnings,
        }

    @staticmethod
    def _current_actionability(payload: dict[str, object], signal: TickerSignalSnapshot | None) -> str | None:
        for key in ("actionability", "current_actionability", "recommended_action", "intended_action"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
        direction = str(signal.direction if signal is not None else payload.get("direction") or "").strip().lower()
        if direction in {"long", "short"}:
            return direction
        if direction in {"neutral", "none", "no_action", "watchlist", "hold"}:
            return "no_action"
        return direction or None

    @staticmethod
    def _current_analysis_direction(payload: dict[str, object], signal: TickerSignalSnapshot | None) -> str | None:
        for key in ("analysis_direction", "current_direction", "directional_view", "direction"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
        direction = str(signal.direction if signal is not None else "").strip().lower()
        return direction or None

    @classmethod
    def _signal_calibrated_confidence(cls, payload: dict[str, object]) -> float | None:
        for key in ("calibrated_confidence_percent", "cheap_scan_confidence_percent", "base_confidence_percent"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

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
