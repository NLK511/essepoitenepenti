from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class SentimentSnapshotResolver:
    def __init__(
        self,
        repository: SentimentSnapshotRepository,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.repository = repository
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()

    def resolve_macro_snapshot(self) -> dict[str, Any]:
        snapshot = self.repository.get_latest_valid_snapshot("macro", "global_macro", now=datetime.now(timezone.utc))
        if snapshot is None:
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
        return self._snapshot_payload(snapshot)

    def resolve_industry_snapshot(self, ticker: str) -> dict[str, Any]:
        industry_profile = self.taxonomy_service.get_industry_profile(ticker)
        snapshot = self.repository.get_latest_valid_snapshot(
            "industry",
            industry_profile["subject_key"],
            now=datetime.now(timezone.utc),
        )
        if snapshot is None:
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
                "diagnostics": {
                    "warnings": [
                        f"industry snapshot unavailable for {industry_profile['subject_label']}; using neutral fallback"
                    ]
                },
            }
        return self._snapshot_payload(snapshot)

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
    def _parse_json(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
