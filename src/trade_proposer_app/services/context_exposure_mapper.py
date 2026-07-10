from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trade_proposer_app.domain.enums import RecommendationDirection
from trade_proposer_app.services.ticker_exposure_ontology import TickerExposureOntologyService


@dataclass(frozen=True)
class ContextExposureMapping:
    exposure_bias: str
    alignment_percent: float
    context_strength_percent: float
    context_event_relevance_percent: float
    raw_support_score: float
    raw_support_percent: float
    macro_support_score: float
    industry_support_score: float
    macro_exposure_alignment_percent: float
    industry_exposure_alignment_percent: float
    matched_exposure_paths: list[str] = field(default_factory=list)
    relationship_edges: list[dict[str, object]] = field(default_factory=list)
    conflict_flags: list[str] = field(default_factory=list)
    expected_transmission_window: str = "unknown"
    coverage_status: str = "unknown"
    evidence_state: str = "unknown"
    quality_status: str = "unknown"
    neutral_reason: str | None = None
    ontology_context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "exposure_bias": self.exposure_bias,
            "alignment_percent": self.alignment_percent,
            "context_strength_percent": self.context_strength_percent,
            "context_event_relevance_percent": self.context_event_relevance_percent,
            "raw_support_score": self.raw_support_score,
            "raw_support_percent": self.raw_support_percent,
            "macro_support_score": self.macro_support_score,
            "industry_support_score": self.industry_support_score,
            "macro_exposure_alignment_percent": self.macro_exposure_alignment_percent,
            "industry_exposure_alignment_percent": self.industry_exposure_alignment_percent,
            "matched_exposure_paths": self.matched_exposure_paths,
            "relationship_edges": self.relationship_edges,
            "conflict_flags": self.conflict_flags,
            "expected_transmission_window": self.expected_transmission_window,
            "coverage_status": self.coverage_status,
            "evidence_state": self.evidence_state,
            "quality_status": self.quality_status,
            "neutral_reason": self.neutral_reason,
            "ontology_context": self.ontology_context,
        }


class ContextExposureMapper:
    """Map raw macro/industry support into ticker-specific exposure alignment."""

    def __init__(self, ontology: TickerExposureOntologyService | None = None) -> None:
        self.ontology = ontology or TickerExposureOntologyService()

    def map_context(
        self,
        *,
        ticker: str,
        context: dict[str, Any],
        direction: RecommendationDirection,
        taxonomy_profile: dict[str, Any] | None = None,
    ) -> ContextExposureMapping:
        macro_support = self._scoped_score(context, "macro", "macro_context_score", "macro_sentiment_score")
        industry_support = self._scoped_score(context, "industry", "industry_context_score", "industry_sentiment_score")
        raw_support = max(-1.0, min(1.0, (macro_support * 0.45) + (industry_support * 0.55)))
        raw_support_percent = self._score_to_percent(raw_support, direction=direction)
        ontology_context = self.ontology.assess_context(
            ticker,
            context,
            direction=direction,
            taxonomy_profile=taxonomy_profile,
        )
        coverage_status = str(ontology_context.get("coverage_status") or "unknown")
        quality_status = self._quality_status(context)
        evidence_state = self._evidence_state(context)
        conflict_flags = self._conflict_flags(context, ontology_context)
        ontology_adjustment = self._float(ontology_context.get("alignment_adjustment_percent"), 0.0)
        if self._cannot_map(coverage_status, evidence_state, quality_status):
            alignment = 50.0
        else:
            alignment = max(0.0, min(100.0, raw_support_percent + ontology_adjustment))
        bias = self._bias(alignment, coverage_status=coverage_status, evidence_state=evidence_state, quality_status=quality_status)
        matched_paths = [str(path) for path in ontology_context.get("transmission_paths", []) if str(path).strip()]
        matched_count = int(ontology_context.get("matched_exposure_count", 0) or 0)
        strength = max(0.0, min(100.0, abs(raw_support) * 100.0 + min(20.0, matched_count * 4.0)))
        relevance = max(0.0, min(100.0, min(1.0, matched_count / 4.0) * 70.0 + strength * 0.3))
        neutral_reason = self._neutral_reason(
            alignment=alignment,
            coverage_status=coverage_status,
            evidence_state=evidence_state,
            quality_status=quality_status,
            matched_count=matched_count,
            conflict_flags=conflict_flags,
        )
        relationship_edges = taxonomy_profile.get("relationship_edges", []) if isinstance(taxonomy_profile, dict) and isinstance(taxonomy_profile.get("relationship_edges"), list) else []
        return ContextExposureMapping(
            exposure_bias=bias,
            alignment_percent=round(alignment, 2),
            context_strength_percent=round(strength, 2),
            context_event_relevance_percent=round(relevance, 2),
            raw_support_score=round(raw_support, 4),
            raw_support_percent=round(raw_support_percent, 2),
            macro_support_score=round(macro_support, 4),
            industry_support_score=round(industry_support, 4),
            macro_exposure_alignment_percent=round(self._score_to_percent(macro_support, direction=direction), 2),
            industry_exposure_alignment_percent=round(self._score_to_percent(industry_support, direction=direction), 2),
            matched_exposure_paths=matched_paths,
            relationship_edges=relationship_edges[:8],
            conflict_flags=conflict_flags,
            expected_transmission_window=str(context.get("expected_transmission_window") or "unknown"),
            coverage_status=coverage_status,
            evidence_state=evidence_state,
            quality_status=quality_status,
            neutral_reason=neutral_reason,
            ontology_context=ontology_context,
        )

    @classmethod
    def _scoped_score(cls, context: dict[str, Any], scope: str, *keys: str) -> float:
        quality = str(context.get(f"{scope}_context_quality_status") or "").strip().lower()
        evidence = str(context.get(f"{scope}_context_evidence_state") or "").strip().lower()
        events = context.get(f"{scope}_context_events") or context.get(f"{scope}_context_active_themes") or context.get(f"{scope}_context_active_drivers")
        if quality in {"blocked", "failed", "degraded", "partial"}:
            return 0.0
        if evidence in {"missing", "missing_snapshot", "none"}:
            return 0.0
        if evidence and evidence not in {"usable", "events", "mixed", "contradictory"} and not events:
            return 0.0
        for key in keys:
            value = context.get(key)
            if value is not None:
                return max(-1.0, min(1.0, cls._float(value, 0.0)))
        return 0.0

    @staticmethod
    def _score_to_percent(score: float, *, direction: RecommendationDirection) -> float:
        signed = score if direction == RecommendationDirection.LONG else -score
        return max(0.0, min(100.0, (signed + 1.0) * 50.0))

    @staticmethod
    def _quality_status(context: dict[str, Any]) -> str:
        statuses = [
            str(context.get("macro_context_quality_status") or "").strip().lower(),
            str(context.get("industry_context_quality_status") or "").strip().lower(),
        ]
        if any(value in {"blocked", "failed"} for value in statuses):
            return "blocked"
        if any(value in {"usable", "ok"} for value in statuses):
            return "usable"
        if any(value in {"degraded", "partial"} for value in statuses):
            return "degraded"
        return "unknown"

    @staticmethod
    def _evidence_state(context: dict[str, Any]) -> str:
        states = [
            str(context.get("macro_context_evidence_state") or "").strip().lower(),
            str(context.get("industry_context_evidence_state") or "").strip().lower(),
        ]
        if any(value in {"contradictory", "mixed"} for value in states):
            return "mixed"
        if any(value in {"usable", "events"} for value in states):
            return "usable"
        if any(context.get(key) for key in ("macro_context_events", "industry_context_events", "macro_context_active_themes", "industry_context_active_drivers")):
            return "usable"
        return "missing"

    @staticmethod
    def _conflict_flags(context: dict[str, Any], ontology_context: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        for key in ("market_intelligence_conflict_flags", "conflict_flags"):
            raw = context.get(key)
            if isinstance(raw, list):
                flags.extend(str(item) for item in raw if str(item).strip())
        if str(ontology_context.get("directional_support") or "") == "mixed":
            flags.append("mixed_mapped_exposure")
        return list(dict.fromkeys(flags))

    @staticmethod
    def _cannot_map(coverage_status: str, evidence_state: str, quality_status: str) -> bool:
        return coverage_status in {"missing"} or evidence_state in {"missing"} or quality_status in {"blocked", "failed"}

    @classmethod
    def _bias(cls, alignment: float, *, coverage_status: str, evidence_state: str, quality_status: str) -> str:
        if cls._cannot_map(coverage_status, evidence_state, quality_status):
            return "unknown"
        if 45.0 <= alignment <= 55.0:
            return "neutral"
        if alignment >= 62.0:
            return "tailwind"
        if alignment <= 42.0:
            return "headwind"
        return "mixed"

    @staticmethod
    def _neutral_reason(*, alignment: float, coverage_status: str, evidence_state: str, quality_status: str, matched_count: int, conflict_flags: list[str]) -> str | None:
        if quality_status in {"blocked", "failed"}:
            return "context_quality_blocked"
        if evidence_state == "missing":
            return "missing_context_evidence"
        if coverage_status == "missing":
            return "missing_exposure_mapping"
        if conflict_flags:
            return "mixed_or_conflicting_context"
        if matched_count == 0:
            return "unmapped_ticker_exposure"
        if 45.0 <= alignment <= 55.0:
            return "true_neutral_or_balanced_context"
        return None

    @staticmethod
    def _float(value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
