from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.services.context_exposure_mapper import ContextExposureMapper
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class MacroContextResolver(Protocol):
    def resolve_macro_snapshot(self, *, as_of: datetime | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MacroShortlistSupport:
    score: float = 50.0
    adjustment: float = 0.0
    bias: str = "unknown"
    quality_status: str = "unknown"
    reasons: tuple[str, ...] = ()
    reason_details: tuple[dict[str, str], ...] = ()
    snapshot_id: int | None = None
    context_tags: tuple[str, ...] = ()
    raw_support_score: float = 0.0
    raw_support_percent: float = 50.0
    alignment_percent: float = 50.0
    neutral_reason: str | None = None
    matched_exposure_paths: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 2),
            "adjustment": round(self.adjustment, 2),
            "bias": self.bias,
            "quality_status": self.quality_status,
            "reasons": list(self.reasons),
            "reason_details": list(self.reason_details),
            "snapshot_id": self.snapshot_id,
            "context_tags": list(self.context_tags),
            "raw_support_score": round(self.raw_support_score, 4),
            "raw_support_percent": round(self.raw_support_percent, 2),
            "alignment_percent": round(self.alignment_percent, 2),
            "neutral_reason": self.neutral_reason,
            "matched_exposure_paths": list(self.matched_exposure_paths),
        }


@dataclass(frozen=True)
class MacroShortlistScoringConfig:
    enabled: bool = True
    max_boost: float = 5.0
    max_penalty: float = 5.0
    minimum_alignment_for_boost: float = 55.0
    maximum_alignment_for_penalty: float = 45.0


class MacroShortlistScorer:
    """Point-in-time macro shortlist support scorer.

    The scorer is intentionally resolver-only: it never refreshes providers. It maps the
    latest available macro snapshot through the ticker exposure ontology and returns a
    small bounded adjustment for shortlist ranking/lane diagnostics.
    """

    def __init__(
        self,
        resolver: MacroContextResolver | None,
        *,
        taxonomy_service: TickerTaxonomyService | None = None,
        exposure_mapper: ContextExposureMapper | None = None,
        config: MacroShortlistScoringConfig | None = None,
    ) -> None:
        self.resolver = resolver
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.exposure_mapper = exposure_mapper or ContextExposureMapper()
        self.config = config or MacroShortlistScoringConfig()

    def score(
        self,
        ticker: str,
        direction: str | RecommendationDirection,
        *,
        as_of: datetime | None = None,
        horizon: StrategyHorizon | None = None,
    ) -> MacroShortlistSupport:
        if not self.config.enabled:
            return self._neutral("macro_shortlist_disabled", quality_status="disabled")
        if self.resolver is None:
            return self._neutral("macro_context_missing", quality_status="missing")
        snapshot = self.resolver.resolve_macro_snapshot(as_of=as_of)
        snapshot_id = self._int_or_none(snapshot.get("context_snapshot_id") or snapshot.get("snapshot_id"))
        quality_status = str(snapshot.get("context_quality_status") or "unknown").strip().lower() or "unknown"
        if snapshot_id is None:
            return self._neutral("macro_context_missing", quality_status=quality_status, snapshot_id=snapshot_id)
        if quality_status not in {"usable", "ok"}:
            return self._neutral("macro_context_degraded", quality_status=quality_status, snapshot_id=snapshot_id)

        context = self._mapping_context(snapshot)
        profile = self.taxonomy_service.get_ticker_profile(ticker)
        mapping = self.exposure_mapper.map_context(
            ticker=ticker,
            context=context,
            direction=self._direction(direction),
            taxonomy_profile=profile,
        )
        reasons = self._reasons(mapping.exposure_bias, mapping.neutral_reason)
        adjustment = self._adjustment(mapping.exposure_bias, mapping.alignment_percent)
        return MacroShortlistSupport(
            score=round(mapping.alignment_percent, 2),
            adjustment=adjustment,
            bias=mapping.exposure_bias,
            quality_status=quality_status,
            reasons=tuple(reasons),
            reason_details=tuple(self._reason_details(reasons)),
            snapshot_id=snapshot_id,
            context_tags=tuple(str(item) for item in snapshot.get("context_regime_tags", []) if str(item).strip()),
            raw_support_score=mapping.raw_support_score,
            raw_support_percent=mapping.raw_support_percent,
            alignment_percent=mapping.alignment_percent,
            neutral_reason=mapping.neutral_reason,
            matched_exposure_paths=tuple(mapping.matched_exposure_paths),
        )

    def score_many(
        self,
        candidates: list[Any],
        *,
        as_of: datetime | None = None,
        horizon: StrategyHorizon | None = None,
    ) -> dict[str, MacroShortlistSupport]:
        return {
            str(candidate.ticker): self.score(str(candidate.ticker), getattr(candidate, "direction", "long"), as_of=as_of, horizon=horizon)
            for candidate in candidates
        }

    def _adjustment(self, bias: str, alignment: float) -> float:
        if bias == "tailwind" and alignment >= self.config.minimum_alignment_for_boost:
            span = max(1.0, 100.0 - self.config.minimum_alignment_for_boost)
            return round(min(self.config.max_boost, ((alignment - self.config.minimum_alignment_for_boost) / span) * self.config.max_boost), 2)
        if bias == "headwind" and alignment <= self.config.maximum_alignment_for_penalty:
            span = max(1.0, self.config.maximum_alignment_for_penalty)
            return round(max(-self.config.max_penalty, -((self.config.maximum_alignment_for_penalty - alignment) / span) * self.config.max_penalty), 2)
        return 0.0

    @staticmethod
    def _mapping_context(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "macro_context_score": snapshot.get("score", 0.0),
            "industry_context_score": 0.0,
            "macro_context_evidence_state": (snapshot.get("source_breakdown") or {}).get("evidence_state", "usable"),
            "macro_context_coverage_state": (snapshot.get("source_breakdown") or {}).get("coverage_state", "unknown"),
            "macro_context_quality_status": snapshot.get("context_quality_status", "unknown"),
            "macro_context_events": snapshot.get("context_active_events") or snapshot.get("drivers") or [],
            "macro_context_regime_tags": snapshot.get("context_regime_tags") or [],
            "market_intelligence_conflict_flags": snapshot.get("context_contradictory_event_labels") or [],
        }

    def _reason_details(self, reasons: list[str]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        for reason in reasons:
            definition = self.taxonomy_service.get_shortlist_reason_definition(reason)
            details.append({"key": str(definition.get("key", reason)), "label": str(definition.get("label", reason.replace("_", " ")))})
        return details

    @staticmethod
    def _reasons(bias: str, neutral_reason: str | None) -> list[str]:
        if bias == "tailwind":
            return ["macro_tailwind_boost"]
        if bias == "headwind":
            return ["macro_headwind_penalty"]
        if neutral_reason in {"missing_exposure_mapping", "missing_context_evidence"}:
            return ["macro_exposure_not_mapped"]
        if neutral_reason and "degraded" in neutral_reason:
            return ["macro_context_degraded"]
        return ["macro_context_neutral"]

    @staticmethod
    def _direction(direction: str | RecommendationDirection) -> RecommendationDirection:
        if isinstance(direction, RecommendationDirection):
            return direction
        return RecommendationDirection.SHORT if str(direction).lower() == "short" else RecommendationDirection.LONG

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _neutral(self, reason: str, *, quality_status: str, snapshot_id: int | None = None) -> MacroShortlistSupport:
        return MacroShortlistSupport(
            quality_status=quality_status,
            reasons=(reason,),
            reason_details=tuple(self._reason_details([reason])),
            snapshot_id=snapshot_id,
            neutral_reason=reason,
        )
