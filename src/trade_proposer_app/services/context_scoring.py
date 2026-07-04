from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from trade_proposer_app.services.context_quality import ContextQualityAssessment

_SOURCE_PRIORITY_FACTORS = {
    "official": 1.0,
    "trade": 0.92,
    "authoritative_social": 0.88,
    "major": 0.82,
    "other": 0.58,
    "social": 0.32,
}

_POSITIVE_INTERPRETATIONS = {"relief", "supportive", "easing"}
_NEGATIVE_INTERPRETATIONS = {"fear", "adverse", "tightening", "risk"}
_POSITIVE_TRANSITIONS = {"new", "escalating"}
_FADING_TRANSITIONS = {"fading", "dropped"}


@dataclass(frozen=True)
class ContextScoreResult:
    support_score: float = 0.0
    support_label: str = "NEUTRAL"
    directional_confidence_percent: float = 0.0
    saliency_score: float = 0.0
    evidence_state: str = "missing"
    coverage_state: str = "missing"
    score_components: dict[str, object] = field(default_factory=dict)
    score_reasons: list[str] = field(default_factory=list)


class ContextSnapshotSchemaAdapter:
    """Canonical read/write helpers for macro and industry context scores.

    Historical macro snapshots used context_score/context_label while industry
    snapshots used support_score/support_label. All new downstream code should
    read through this adapter and all new snapshots should write support_* keys.
    """

    @staticmethod
    def support_label(source_breakdown: dict[str, Any], fallback: str = "NEUTRAL") -> str:
        value = source_breakdown.get("support_label")
        if value is None:
            value = source_breakdown.get("context_label")
        normalized = str(value or fallback or "NEUTRAL").strip().upper()
        return normalized or "NEUTRAL"

    @staticmethod
    def support_score(source_breakdown: dict[str, Any], fallback: float = 0.0) -> float:
        value = source_breakdown.get("support_score")
        if value is None:
            value = source_breakdown.get("context_score")
        try:
            return float(value if value is not None else fallback)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def score_source(source_breakdown: dict[str, Any]) -> str:
        if "support_score" in source_breakdown or "support_label" in source_breakdown:
            return "support_keys"
        if "context_score" in source_breakdown or "context_label" in source_breakdown:
            return "legacy_context_keys"
        return "fallback"

    @staticmethod
    def canonical_score_fields(result: ContextScoreResult) -> dict[str, object]:
        return {
            "support_score": result.support_score,
            "support_label": result.support_label,
            "directional_confidence_percent": result.directional_confidence_percent,
            "score_components": result.score_components,
            "score_reasons": result.score_reasons,
        }


class ContextEvidenceScorer:
    """Shared event-derived scoring for macro and industry context."""

    def score(
        self,
        *,
        scope: str,
        active_events: list[dict[str, object]],
        news_item_count: int,
        social_item_count: int,
        source_priority_counts: dict[str, int],
        quality: ContextQualityAssessment,
        contradiction_count: int = 0,
        legacy_score: float = 0.0,
        legacy_label: str = "NEUTRAL",
    ) -> ContextScoreResult:
        coverage_state = self.coverage_state(news_item_count=news_item_count, social_item_count=social_item_count)
        evidence_state = self.evidence_state(active_events=active_events, coverage_state=coverage_state, quality=quality)
        if not active_events:
            return ContextScoreResult(
                support_score=0.0,
                support_label="NEUTRAL",
                directional_confidence_percent=0.0,
                saliency_score=0.0,
                evidence_state=evidence_state,
                coverage_state=coverage_state,
                score_components={
                    "scope": scope,
                    "event_direction": 0.0,
                    "event_saliency": 0.0,
                    "source_quality": self._source_quality(source_priority_counts, social_item_count=social_item_count),
                    "quality_factor": self._quality_factor(quality),
                    "contradiction_penalty": 0.0,
                    "legacy_score": round(float(legacy_score or 0.0), 3),
                    "legacy_label": legacy_label,
                },
                score_reasons=["no_active_context_events"],
            )

        weighted_direction = 0.0
        total_weight = 0.0
        reasons: list[str] = []
        event_debug: list[dict[str, object]] = []
        for event in active_events:
            direction = self._event_direction(event)
            saliency = self._float(event.get("saliency_weight"), 0.0)
            priority = str(event.get("source_priority") or "other")
            priority_factor = _SOURCE_PRIORITY_FACTORS.get(priority, _SOURCE_PRIORITY_FACTORS["other"])
            news_count = self._float(event.get("news_evidence_count"), 0.0)
            social_count = self._float(event.get("social_evidence_count"), 0.0)
            primary_factor = 1.0 if news_count > 0 else 0.45 if social_count > 0 else 0.0
            transition_factor = self._transition_factor(event)
            weight = max(0.0, saliency * priority_factor * primary_factor * transition_factor)
            if direction != 0.0 and weight > 0.0:
                weighted_direction += direction * weight
                total_weight += weight
                reasons.append("event_directional_evidence")
            event_debug.append(
                {
                    "key": event.get("key"),
                    "label": event.get("label"),
                    "direction": direction,
                    "saliency": round(saliency, 3),
                    "source_priority": priority,
                    "weight": round(weight, 3),
                }
            )

        event_direction = weighted_direction / total_weight if total_weight > 0 else 0.0
        event_saliency = self._combined_saliency(active_events)
        source_quality = self._source_quality(source_priority_counts, social_item_count=social_item_count)
        quality_factor = self._quality_factor(quality)
        contradiction_penalty = min(0.85, max(0.0, contradiction_count * 0.28))
        coverage_factor = self._coverage_factor(coverage_state)
        confidence_factor = max(0.0, min(1.0, source_quality * quality_factor * coverage_factor * (1.0 - contradiction_penalty)))

        if quality.status != "usable" or evidence_state not in {"usable", "degraded"}:
            confidence_factor = min(confidence_factor, 0.25)
            reasons.append("quality_cap_applied")
        if coverage_state == "social":
            confidence_factor = min(confidence_factor, 0.35)
            reasons.append("social_only_cap_applied")
        if contradiction_count > 0:
            reasons.append("contradiction_penalty_applied")

        support_score = event_direction * event_saliency * confidence_factor
        if abs(support_score) < 0.035:
            support_score = 0.0
        support_score = round(max(-1.0, min(1.0, support_score)), 3)
        support_label = self._label(support_score, event_direction, contradiction_count)
        directional_confidence = round(max(0.0, min(100.0, abs(event_direction) * event_saliency * confidence_factor * 100.0)), 2)
        if not reasons:
            reasons.append("neutral_event_direction")

        return ContextScoreResult(
            support_score=support_score,
            support_label=support_label,
            directional_confidence_percent=directional_confidence,
            saliency_score=round(event_saliency, 3),
            evidence_state=evidence_state,
            coverage_state=coverage_state,
            score_components={
                "scope": scope,
                "event_direction": round(event_direction, 3),
                "event_saliency": round(event_saliency, 3),
                "source_quality": round(source_quality, 3),
                "coverage_factor": round(coverage_factor, 3),
                "quality_factor": round(quality_factor, 3),
                "contradiction_penalty": round(contradiction_penalty, 3),
                "confidence_factor": round(confidence_factor, 3),
                "legacy_score": round(float(legacy_score or 0.0), 3),
                "legacy_label": legacy_label,
                "events": event_debug[:5],
            },
            score_reasons=list(dict.fromkeys(reasons)),
        )

    @staticmethod
    def coverage_state(*, news_item_count: int, social_item_count: int) -> str:
        if news_item_count > 0 and social_item_count > 0:
            return "news+social"
        if news_item_count > 0:
            return "news"
        if social_item_count > 0:
            return "social"
        return "missing"

    @staticmethod
    def evidence_state(*, active_events: list[dict[str, object]], coverage_state: str, quality: ContextQualityAssessment) -> str:
        if not active_events and coverage_state == "missing":
            return "missing"
        if not active_events:
            return "thin"
        if quality.status == "usable":
            return "usable"
        if coverage_state in {"news", "news+social", "social"}:
            return "degraded"
        return "missing"

    @staticmethod
    def _event_direction(event: dict[str, object]) -> float:
        evidence = str(event.get("evidence_direction") or "neutral").strip().lower()
        if evidence == "positive":
            return 1.0
        if evidence == "negative":
            return -1.0
        if evidence == "mixed":
            return 0.0
        interpretation = str(event.get("market_interpretation") or "unknown").strip().lower()
        if interpretation in _POSITIVE_INTERPRETATIONS:
            return 0.75
        if interpretation in _NEGATIVE_INTERPRETATIONS:
            return -0.75
        transition = str(event.get("state_transition") or "unknown").strip().lower()
        if transition == "easing":
            return 0.5
        if transition == "escalating":
            return -0.5
        return 0.0

    @staticmethod
    def _transition_factor(event: dict[str, object]) -> float:
        transition = str(event.get("state_transition") or "unknown").strip().lower()
        if transition in _FADING_TRANSITIONS:
            return 0.55
        if transition in _POSITIVE_TRANSITIONS:
            return 1.0
        if transition == "persistent":
            return 0.8
        return 0.75

    @staticmethod
    def _combined_saliency(events: list[dict[str, object]]) -> float:
        if not events:
            return 0.0
        saliencies = sorted((max(0.0, min(1.0, ContextEvidenceScorer._float(event.get("saliency_weight"), 0.0))) for event in events), reverse=True)
        top = saliencies[0]
        breadth = min(0.25, math.log1p(len([value for value in saliencies if value >= 0.15])) / 8.0)
        secondary = min(0.2, sum(saliencies[1:3]) * 0.15)
        return max(0.0, min(1.0, top + breadth + secondary))

    @staticmethod
    def _source_quality(counts: dict[str, int], *, social_item_count: int) -> float:
        weighted = 0.0
        total = 0.0
        for key, count in counts.items():
            numeric_count = max(0.0, ContextEvidenceScorer._float(count, 0.0))
            if numeric_count <= 0:
                continue
            weighted += numeric_count * _SOURCE_PRIORITY_FACTORS.get(key, _SOURCE_PRIORITY_FACTORS["other"])
            total += numeric_count
        if total > 0:
            return max(0.0, min(1.0, weighted / total))
        return 0.32 if social_item_count > 0 else 0.0

    @staticmethod
    def _quality_factor(quality: ContextQualityAssessment) -> float:
        if quality.status == "blocked":
            return min(0.15, max(0.0, quality.score / 100.0))
        if quality.status == "degraded":
            return min(0.6, max(0.0, quality.score / 100.0))
        return max(0.0, min(1.0, quality.score / 100.0))

    @staticmethod
    def _coverage_factor(coverage_state: str) -> float:
        if coverage_state == "news+social":
            return 1.0
        if coverage_state == "news":
            return 0.9
        if coverage_state == "social":
            return 0.45
        return 0.0

    @staticmethod
    def _label(score: float, event_direction: float, contradiction_count: int) -> str:
        if contradiction_count > 0 and abs(event_direction) < 0.55:
            return "MIXED"
        if score >= 0.08:
            return "POSITIVE"
        if score <= -0.08:
            return "NEGATIVE"
        if abs(event_direction) >= 0.35:
            return "MIXED"
        return "NEUTRAL"

    @staticmethod
    def _float(value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
