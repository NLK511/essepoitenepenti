from __future__ import annotations

from typing import Any

from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class ContextSnapshotResolver:
    def __init__(
        self,
        repository: ContextSnapshotRepository,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.repository = repository
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def resolve_macro_snapshot(self) -> dict[str, Any]:
        snapshot = self.repository.get_latest_macro_context_snapshot()
        if snapshot is None:
            return {
                "score": 0.0,
                "label": "NEUTRAL",
                "source": "context",
                "snapshot_id": None,
                "subject_key": "global_macro",
                "subject_label": "Global Macro",
                "coverage": {},
                "source_breakdown": {},
                "drivers": [],
                "diagnostics": {"warnings": ["macro context snapshot unavailable; using neutral fallback"]},
            }
        source_breakdown = snapshot.source_breakdown if isinstance(snapshot.source_breakdown, dict) else {}
        support_label = str(source_breakdown.get("support_label") or "NEUTRAL")
        support_score = float(source_breakdown.get("support_score", 0.0) or 0.0)
        return {
            "score": support_score,
            "label": support_label,
            "source": "context",
            "snapshot_id": None,
            "subject_key": "global_macro",
            "subject_label": "Global Macro",
            "coverage": self._context_coverage(source_breakdown),
            "source_breakdown": source_breakdown,
            "drivers": snapshot.active_themes,
            "context_snapshot_id": snapshot.id,
            "context_status": snapshot.status,
            "context_summary": snapshot.summary_text,
            "context_saliency_score": snapshot.saliency_score,
            "context_confidence_percent": snapshot.confidence_percent,
            "context_active_events": snapshot.active_themes,
            "context_active_themes": snapshot.active_themes,
            "context_regime_tags": snapshot.regime_tags,
            "context_lifecycle": self._metadata(snapshot).get("event_lifecycle_summary", {}),
            "context_contradictory_event_labels": self._metadata(snapshot).get("contradictory_event_labels", []),
            "context_source_breakdown": source_breakdown,
            "context_metadata": self._metadata(snapshot),
            "diagnostics": {"warnings": list(snapshot.warnings)},
        }

    def resolve_industry_snapshot(self, ticker: str) -> dict[str, Any]:
        industry_profile = self.taxonomy_service.get_industry_profile(ticker)
        subject_key = industry_profile["subject_key"]
        subject_label = industry_profile["subject_label"]
        snapshot = self.repository.get_latest_industry_context_snapshot(subject_key)
        taxonomy_metadata = self._industry_taxonomy_metadata(industry_profile)
        if snapshot is None:
            return {
                "score": 0.0,
                "label": "NEUTRAL",
                "source": "context",
                "snapshot_id": None,
                "subject_key": subject_key,
                "subject_label": subject_label,
                "coverage": {},
                "source_breakdown": {},
                "drivers": [],
                "context_metadata": taxonomy_metadata,
                "diagnostics": {"warnings": [f"industry context snapshot unavailable for {subject_label}; using neutral fallback"]},
            }
        source_breakdown = snapshot.source_breakdown if isinstance(snapshot.source_breakdown, dict) else {}
        support_label = str(source_breakdown.get("support_label") or self._label_from_direction(snapshot.direction))
        support_score = float(source_breakdown.get("support_score", 0.0) or 0.0)
        return {
            "score": support_score,
            "label": support_label,
            "source": "context",
            "snapshot_id": None,
            "subject_key": subject_key,
            "subject_label": subject_label,
            "coverage": self._context_coverage(source_breakdown),
            "source_breakdown": source_breakdown,
            "drivers": snapshot.active_drivers,
            "context_snapshot_id": snapshot.id,
            "context_status": snapshot.status,
            "context_summary": snapshot.summary_text,
            "context_saliency_score": snapshot.saliency_score,
            "context_confidence_percent": snapshot.confidence_percent,
            "context_active_events": snapshot.active_drivers,
            "context_active_drivers": snapshot.active_drivers,
            "context_regime_tags": snapshot.linked_macro_themes,
            "context_lifecycle": self._metadata(snapshot).get("event_lifecycle_summary", {}),
            "context_contradictory_event_labels": self._metadata(snapshot).get("contradictory_event_labels", []),
            "context_source_breakdown": source_breakdown,
            "context_metadata": {
                **taxonomy_metadata,
                **self._metadata(snapshot),
            },
            "diagnostics": {"warnings": list(snapshot.warnings)},
        }

    def _industry_taxonomy_metadata(self, industry_profile: dict[str, Any]) -> dict[str, Any]:
        subject_key = str(industry_profile.get("subject_key", "")).strip()
        ontology_profile = self.taxonomy_service.get_industry_definition(subject_key)
        transmission_channels = ontology_profile.get("transmission_channels") if isinstance(ontology_profile.get("transmission_channels"), list) else []
        ontology_profile = {
            **ontology_profile,
            "transmission_channel_details": self._channel_details(transmission_channels),
        }
        return {
            "ontology_profile": ontology_profile,
            "sector_definition": self.taxonomy_service.get_sector_definition(str(industry_profile.get("sector", ""))),
            "ontology_relationships": self.taxonomy_service.list_relationships(subject_key, direction="outbound"),
            "matched_ontology_relationships": [],
            "taxonomy_source_mode": self.taxonomy_service.taxonomy_overview().get("source_mode"),
        }

    def _channel_details(self, values: list[object]) -> list[dict[str, str]]:
        details: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            definition = self.taxonomy_service.get_transmission_channel_definition(value)
            key = str(definition.get("key", value)).strip() or value.strip()
            if key in seen:
                continue
            seen.add(key)
            label = str(definition.get("label", key.replace("_", " "))).strip() or key.replace("_", " ")
            details.append({"key": key, "label": label})
        return details

    @staticmethod
    def _context_coverage(source_breakdown: dict[str, object]) -> dict[str, object]:
        return {
            "primary_news_item_count": source_breakdown.get("primary_news_item_count", 0),
            "supporting_social_item_count": source_breakdown.get("supporting_social_item_count", 0),
            "primary_news_coverage_quality": source_breakdown.get("primary_news_coverage_quality"),
            "tracked_tickers": source_breakdown.get("tracked_tickers", []),
        }

    @staticmethod
    def _metadata(snapshot: Any) -> dict[str, Any]:
        return snapshot.metadata if isinstance(snapshot.metadata, dict) else {}

    @staticmethod
    def _label_from_direction(direction: str | None) -> str:
        normalized = (direction or "").strip().lower()
        if normalized == "long":
            return "POSITIVE"
        if normalized == "short":
            return "NEGATIVE"
        return "NEUTRAL"


ContextSnapshotResolver = ContextSnapshotResolver
