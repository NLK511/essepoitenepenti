from __future__ import annotations

import unittest
from datetime import datetime, timezone

from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot
from trade_proposer_app.services.context_snapshot_resolver import ContextSnapshotResolver


class _StubRepository:
    def __init__(self, macro_snapshot=None, industry_snapshot=None) -> None:
        self.macro_snapshot = macro_snapshot
        self.industry_snapshot = industry_snapshot

    def get_latest_macro_context_snapshot(self):
        return self.macro_snapshot

    def get_latest_macro_context_snapshot_before(self, as_of):
        return self.macro_snapshot

    def get_latest_industry_context_snapshot(self, industry_key):
        return self.industry_snapshot

    def get_latest_industry_context_snapshot_before(self, industry_key, as_of):
        return self.industry_snapshot


class ContextSnapshotResolverTests(unittest.TestCase):
    def test_macro_resolution_reads_legacy_context_score_keys(self) -> None:
        snapshot = MacroContextSnapshot(
            computed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            summary_text="Macro context",
            status="ok",
            source_breakdown={
                "context_label": "NEGATIVE",
                "context_score": -0.42,
                "context_quality_score": 91.0,
                "context_quality_status": "usable",
            },
        )
        resolver = ContextSnapshotResolver(_StubRepository(macro_snapshot=snapshot))

        payload = resolver.resolve_macro_snapshot()

        self.assertEqual(payload["label"], "NEGATIVE")
        self.assertEqual(payload["score"], -0.42)
        self.assertEqual(payload["context_score_source"], "legacy_context_keys")

    def test_macro_resolution_exposes_context_quality(self) -> None:
        snapshot = MacroContextSnapshot(
            computed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            summary_text="Macro context",
            status="warning",
            source_breakdown={
                "support_label": "NEGATIVE",
                "support_score": -0.2,
                "context_quality_score": 61.5,
                "context_quality_status": "degraded",
                "context_quality_flags": {"partial_coverage": True},
                "context_quality_notes": ["primary evidence coverage is low"],
            },
            metadata={"context_quality": {"score": 61.5, "status": "degraded", "flags": {"partial_coverage": True}, "notes": ["primary evidence coverage is low"]}},
            warnings=["macro warning"],
        )
        resolver = ContextSnapshotResolver(_StubRepository(macro_snapshot=snapshot))

        payload = resolver.resolve_macro_snapshot()

        self.assertEqual(payload["context_quality_status"], "degraded")
        self.assertEqual(payload["context_quality_score"], 61.5)
        self.assertTrue(payload["context_quality_flags"]["partial_coverage"])
        self.assertIn("primary evidence coverage is low", payload["context_quality_notes"])

    def test_industry_resolution_exposes_context_quality(self) -> None:
        snapshot = IndustryContextSnapshot(
            industry_key="semiconductors",
            industry_label="Semiconductors",
            computed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            summary_text="Industry context",
            status="warning",
            direction="positive",
            source_breakdown={
                "support_label": "POSITIVE",
                "support_score": 0.3,
                "evidence_state": "usable",
                "coverage_state": "news+social",
                "context_quality_score": 88.0,
                "context_quality_status": "usable",
                "context_quality_flags": {"hard_missing": False},
                "context_quality_notes": [],
            },
            metadata={"context_quality": {"score": 88.0, "status": "usable", "flags": {"hard_missing": False}, "notes": []}},
            warnings=[],
        )
        resolver = ContextSnapshotResolver(_StubRepository(industry_snapshot=snapshot))

        payload = resolver.resolve_industry_snapshot("NVDA")

        self.assertEqual(payload["context_quality_status"], "usable")
        self.assertEqual(payload["context_quality_score"], 88.0)
        self.assertFalse(payload["context_quality_flags"]["hard_missing"])
        self.assertEqual(payload["context_evidence_state"], "usable")
        self.assertEqual(payload["context_coverage_state"], "news+social")
        self.assertEqual(payload["label"], "POSITIVE")
    def test_industry_resolution_blocks_when_snapshot_missing(self) -> None:
        resolver = ContextSnapshotResolver(_StubRepository(industry_snapshot=None))

        payload = resolver.resolve_industry_snapshot("NVDA")

        self.assertEqual(payload["context_quality_status"], "blocked")
        self.assertEqual(payload["context_evidence_state"], "missing_snapshot")
        self.assertEqual(payload["context_coverage_state"], "missing")
        self.assertIn("blocked fallback", payload["context_quality_notes"][0])


if __name__ == "__main__":
    unittest.main()
