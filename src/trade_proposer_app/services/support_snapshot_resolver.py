from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.support_snapshots import SupportSnapshotRepository
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class SupportSnapshotResolver:
    def __init__(
        self,
        repository: SupportSnapshotRepository,
        taxonomy_service: TickerTaxonomyService | None = None,
        context_repository: ContextSnapshotRepository | None = None,
    ) -> None:
        self.repository = repository
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.context_repository = context_repository

    def resolve_macro_snapshot(self) -> dict[str, Any]:
        snapshot = self.repository.get_latest_valid_snapshot("macro", "global_macro", now=datetime.now(timezone.utc))
        context_snapshot = self.context_repository.get_latest_macro_context_snapshot() if self.context_repository is not None else None
        if snapshot is None and context_snapshot is None:
            return {
                "score": 0.0,
                "label": "NEUTRAL",
                "source": "snapshot",
                "snapshot_id": None,
                "subject_key": "global_macro",
                "subject_label": "Global Macro",
                "coverage": {},
                "source_breakdown": {},
                "drivers": [],
                "diagnostics": {"warnings": ["macro snapshot unavailable; using neutral fallback"]},
            }
        payload = self._snapshot_payload(snapshot) if snapshot is not None else {
            "score": 0.0,
            "label": "NEUTRAL",
            "source": "context_only",
            "snapshot_id": None,
            "subject_key": "global_macro",
            "subject_label": "Global Macro",
            "coverage": {},
            "source_breakdown": {},
            "drivers": [],
            "diagnostics": {"warnings": ["macro support snapshot unavailable; using context-only fallback"]},
        }
        if context_snapshot is not None:
            payload.update(self._macro_context_payload(context_snapshot))
            payload["source"] = "snapshot_plus_context" if snapshot is not None else "context_only"
        return payload

    def resolve_industry_snapshot(self, ticker: str) -> dict[str, Any]:
        industry_profile = self.taxonomy_service.get_industry_profile(ticker)
        taxonomy_metadata = self._industry_taxonomy_metadata(industry_profile)
        snapshot = self.repository.get_latest_valid_snapshot(
            "industry",
            industry_profile["subject_key"],
            now=datetime.now(timezone.utc),
        )
        context_snapshot = (
            self.context_repository.get_latest_industry_context_snapshot(industry_profile["subject_key"])
            if self.context_repository is not None
            else None
        )
        if snapshot is None and context_snapshot is None:
            resolution_mode = str(industry_profile.get("resolution_mode", "derived") or "derived")
            warning = f"industry snapshot unavailable for {industry_profile['subject_label']}; using neutral fallback"
            if resolution_mode == "sector_fallback":
                warning = f"industry snapshot unavailable for {industry_profile['subject_label']}; using sector-level fallback and neutral score"
            return {
                "score": 0.0,
                "label": "NEUTRAL",
                "source": "snapshot",
                "snapshot_id": None,
                "subject_key": industry_profile["subject_key"],
                "subject_label": industry_profile["subject_label"],
                "coverage": {},
                "source_breakdown": {},
                "drivers": [],
                "context_metadata": taxonomy_metadata,
                "diagnostics": {"warnings": [warning], "taxonomy_subject_key": industry_profile["subject_key"]},
            }
        payload = self._snapshot_payload(snapshot) if snapshot is not None else {
            "score": 0.0,
            "label": "NEUTRAL",
            "source": "context_only",
            "snapshot_id": None,
            "subject_key": industry_profile["subject_key"],
            "subject_label": industry_profile["subject_label"],
            "coverage": {},
            "source_breakdown": {},
            "drivers": [],
            "context_metadata": taxonomy_metadata,
            "diagnostics": {
                "warnings": [
                    f"industry support snapshot unavailable for {industry_profile['subject_label']}; using context-only fallback"
                ],
                "taxonomy_subject_key": industry_profile["subject_key"],
            },
        }
        if context_snapshot is not None:
            payload.update(self._industry_context_payload(context_snapshot))
            payload["source"] = "snapshot_plus_context" if snapshot is not None else "context_only"
        return payload

    def _industry_taxonomy_metadata(self, industry_profile: dict[str, Any]) -> dict[str, Any]:
        subject_key = str(industry_profile.get("subject_key", "")).strip()
        return {
            "ontology_profile": self.taxonomy_service.get_industry_definition(subject_key),
            "sector_definition": self.taxonomy_service.get_sector_definition(str(industry_profile.get("sector", ""))),
            "ontology_relationships": self.taxonomy_service.list_relationships(subject_key, direction="outbound"),
            "matched_ontology_relationships": [],
            "taxonomy_source_mode": self.taxonomy_service.taxonomy_overview().get("source_mode"),
        }

    def _snapshot_payload(self, snapshot: Any) -> dict[str, Any]:
        return {
            "score": snapshot.score,
            "label": snapshot.label,
            "source": "snapshot",
            "snapshot_id": snapshot.id,
            "subject_key": snapshot.subject_key,
            "subject_label": snapshot.subject_label,
            "coverage": self._parse_json(snapshot.coverage_json, {}),
            "source_breakdown": self._parse_json(snapshot.source_breakdown_json, {}),
            "drivers": self._parse_json(snapshot.drivers_json, []),
            "diagnostics": self._parse_json(snapshot.diagnostics_json, {}),
        }

    @staticmethod
    def _macro_context_payload(snapshot: Any) -> dict[str, Any]:
        metadata = snapshot.metadata if isinstance(snapshot.metadata, dict) else {}
        lifecycle = metadata.get("event_lifecycle_summary", {}) if isinstance(metadata, dict) else {}
        return {
            "context_snapshot_id": snapshot.id,
            "context_status": snapshot.status,
            "context_summary": snapshot.summary_text,
            "context_saliency_score": snapshot.saliency_score,
            "context_confidence_percent": snapshot.confidence_percent,
            "context_active_events": snapshot.active_themes,
            "context_regime_tags": snapshot.regime_tags,
            "context_lifecycle": lifecycle,
            "context_contradictory_event_labels": metadata.get("contradictory_event_labels", []),
            "context_source_breakdown": snapshot.source_breakdown,
            "context_metadata": metadata,
            "diagnostics": {
                **(snapshot.source_breakdown.get("upstream", {}) if isinstance(snapshot.source_breakdown, dict) and isinstance(snapshot.source_breakdown.get("upstream"), dict) else {}),
                "warnings": list(
                    dict.fromkeys(
                        list((snapshot.source_breakdown.get("upstream", {}) or {}).get("warnings", []))
                        + list(snapshot.warnings)
                    )
                ) if isinstance(snapshot.source_breakdown, dict) else list(snapshot.warnings),
            },
        }

    @staticmethod
    def _industry_context_payload(snapshot: Any) -> dict[str, Any]:
        metadata = snapshot.metadata if isinstance(snapshot.metadata, dict) else {}
        lifecycle = metadata.get("event_lifecycle_summary", {}) if isinstance(metadata, dict) else {}
        return {
            "context_snapshot_id": snapshot.id,
            "context_status": snapshot.status,
            "context_summary": snapshot.summary_text,
            "context_saliency_score": snapshot.saliency_score,
            "context_confidence_percent": snapshot.confidence_percent,
            "context_active_events": snapshot.active_drivers,
            "context_regime_tags": snapshot.linked_macro_themes,
            "context_lifecycle": lifecycle,
            "context_contradictory_event_labels": metadata.get("contradictory_event_labels", []),
            "context_source_breakdown": snapshot.source_breakdown,
            "context_metadata": metadata,
            "diagnostics": {
                **(snapshot.source_breakdown.get("upstream", {}) if isinstance(snapshot.source_breakdown, dict) and isinstance(snapshot.source_breakdown.get("upstream"), dict) else {}),
                "warnings": list(
                    dict.fromkeys(
                        list((snapshot.source_breakdown.get("upstream", {}) or {}).get("warnings", []))
                        + list(snapshot.warnings)
                    )
                ) if isinstance(snapshot.source_breakdown, dict) else list(snapshot.warnings),
            },
        }

    @staticmethod
    def _parse_json(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default


SupportSnapshotResolver = SupportSnapshotResolver
