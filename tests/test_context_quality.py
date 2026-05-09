from __future__ import annotations

import unittest

from trade_proposer_app.services.context_quality import assess_context_quality


class ContextQualityTests(unittest.TestCase):
    def test_usable_when_primary_evidence_is_present_and_clean(self) -> None:
        assessment = assess_context_quality(
            primary_evidence_present=True,
            primary_coverage_quality="high",
            primary_item_count=3,
            source_priority_counts={"official": 1, "major": 2},
            feed_errors=[],
            contradiction_count=0,
            summary_error=None,
        )

        self.assertEqual(assessment.status, "usable")
        self.assertGreaterEqual(assessment.score, 90.0)
        self.assertFalse(assessment.flags["hard_missing"])
        self.assertFalse(assessment.flags["provider_failure"])

    def test_blocks_when_primary_evidence_is_missing(self) -> None:
        assessment = assess_context_quality(
            primary_evidence_present=False,
            primary_coverage_quality="missing",
            primary_item_count=0,
            source_priority_counts={},
            feed_errors=[],
            contradiction_count=0,
            summary_error=None,
        )

        self.assertEqual(assessment.status, "blocked")
        self.assertTrue(assessment.flags["hard_missing"])
        self.assertLessEqual(assessment.score, 20.0)

    def test_degrades_for_provider_errors_and_contradictions(self) -> None:
        assessment = assess_context_quality(
            primary_evidence_present=True,
            primary_coverage_quality="medium",
            primary_item_count=1,
            source_priority_counts={"trade": 1},
            feed_errors=["news provider timeout"],
            contradiction_count=2,
            summary_error="summary failed",
        )

        self.assertEqual(assessment.status, "degraded")
        self.assertTrue(assessment.flags["provider_failure"])
        self.assertTrue(assessment.flags["contradictory_evidence"])
        self.assertTrue(assessment.flags["summary_failure"])
        self.assertLess(assessment.score, 80.0)


if __name__ == "__main__":
    unittest.main()
