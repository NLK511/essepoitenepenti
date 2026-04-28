from __future__ import annotations

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
import scripts.cleanup_context_missing_primary_sources as cleanup


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class CleanupContextMissingPrimarySourcesTests(unittest.TestCase):
    def test_collect_candidates_finds_only_missing_primary_source_snapshots(self) -> None:
        session = create_session()
        try:
            repository = ContextSnapshotRepository(session)
            repository.create_macro_context_snapshot(
                MacroContextSnapshot(
                    computed_at=datetime(2026, 4, 20, 23, 59, tzinfo=timezone.utc),
                    summary_text="bad macro",
                    status="warning",
                    missing_inputs=["primary_news_evidence"],
                    source_breakdown={"primary_news_item_count": 0, "primary_news_coverage_quality": "low"},
                )
            )
            repository.create_macro_context_snapshot(
                MacroContextSnapshot(
                    computed_at=datetime(2026, 4, 21, 23, 59, tzinfo=timezone.utc),
                    summary_text="good macro",
                    status="ok",
                    missing_inputs=[],
                    source_breakdown={"primary_news_item_count": 2, "primary_news_coverage_quality": "high"},
                )
            )
            repository.create_industry_context_snapshot(
                IndustryContextSnapshot(
                    industry_key="tech",
                    industry_label="Technology",
                    computed_at=datetime(2026, 4, 20, 23, 59, tzinfo=timezone.utc),
                    summary_text="bad industry",
                    status="warning",
                    missing_inputs=[],
                    source_breakdown={"primary_news_item_count": 0, "primary_news_coverage_quality": "low"},
                )
            )
            repository.create_industry_context_snapshot(
                IndustryContextSnapshot(
                    industry_key="energy",
                    industry_label="Energy",
                    computed_at=datetime(2026, 4, 21, 23, 59, tzinfo=timezone.utc),
                    summary_text="good industry",
                    status="ok",
                    missing_inputs=["supporting_social_evidence"],
                    source_breakdown={"primary_news_item_count": 3, "primary_news_coverage_quality": "high"},
                )
            )

            candidates = cleanup.collect_candidates(session)

            self.assertEqual(2, len(candidates))
            self.assertCountEqual(["macro", "industry"], [candidate.kind for candidate in candidates])
            self.assertTrue(any(candidate.kind == "macro" and candidate.primary_news_item_count == 0 for candidate in candidates))
            self.assertTrue(any(candidate.kind == "industry" and candidate.primary_news_item_count == 0 for candidate in candidates))
        finally:
            session.close()

    def test_apply_deletes_only_flagged_snapshots(self) -> None:
        session = create_session()
        try:
            repository = ContextSnapshotRepository(session)
            bad_macro = repository.create_macro_context_snapshot(
                MacroContextSnapshot(
                    computed_at=datetime(2026, 4, 20, 23, 59, tzinfo=timezone.utc),
                    summary_text="bad macro",
                    status="warning",
                    missing_inputs=["primary_news_evidence"],
                    source_breakdown={"primary_news_item_count": 0, "primary_news_coverage_quality": "low"},
                )
            )
            good_macro = repository.create_macro_context_snapshot(
                MacroContextSnapshot(
                    computed_at=datetime(2026, 4, 21, 23, 59, tzinfo=timezone.utc),
                    summary_text="good macro",
                    status="ok",
                    missing_inputs=[],
                    source_breakdown={"primary_news_item_count": 2, "primary_news_coverage_quality": "high"},
                )
            )
            bad_industry = repository.create_industry_context_snapshot(
                IndustryContextSnapshot(
                    industry_key="tech",
                    industry_label="Technology",
                    computed_at=datetime(2026, 4, 20, 23, 59, tzinfo=timezone.utc),
                    summary_text="bad industry",
                    status="warning",
                    missing_inputs=["primary_industry_news_evidence"],
                    source_breakdown={"primary_news_item_count": 0, "primary_news_coverage_quality": "low"},
                )
            )
            good_industry = repository.create_industry_context_snapshot(
                IndustryContextSnapshot(
                    industry_key="energy",
                    industry_label="Energy",
                    computed_at=datetime(2026, 4, 21, 23, 59, tzinfo=timezone.utc),
                    summary_text="good industry",
                    status="ok",
                    missing_inputs=["supporting_social_evidence"],
                    source_breakdown={"primary_news_item_count": 3, "primary_news_coverage_quality": "high"},
                )
            )

            candidates = cleanup.collect_candidates(session)
            deleted = cleanup._delete_candidates(session, candidates)

            self.assertEqual({"macro": 1, "industry": 1}, deleted)
            self.assertIsNone(repository.get_macro_context_snapshot(bad_macro.id))
            self.assertIsNotNone(repository.get_macro_context_snapshot(good_macro.id))
            self.assertIsNone(repository.get_industry_context_snapshot(bad_industry.id))
            self.assertIsNotNone(repository.get_industry_context_snapshot(good_industry.id))
        finally:
            session.close()
