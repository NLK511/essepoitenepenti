from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import scripts.reconstruct_context as reconstruct_context
from trade_proposer_app.domain.models import IndustryContextSnapshot, MacroContextSnapshot
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository


class FakeTaxonomyService:
    def list_industry_profiles(self) -> list[dict[str, object]]:
        return [
            {
                "subject_key": "tech",
                "subject_label": "Technology",
                "tickers": ["AAPL", "MSFT"],
                "queries": ["semiconductors", "chip demand"],
            },
            {
                "subject_key": "energy",
                "subject_label": "Energy",
                "tickers": ["XOM", "CVX"],
                "queries": ["oil prices", "opec"],
            },
        ]


class FakeMacroService:
    def __init__(self, repository: ContextSnapshotRepository) -> None:
        self.repository = repository
        self.calls: list[tuple[datetime, str, str]] = []

    def create_from_refresh_payload(self, payload, *, request_mode: str = "live") -> MacroContextSnapshot:
        self.calls.append((payload.computed_at, request_mode, payload.subject_key))
        snapshot = MacroContextSnapshot(
            computed_at=payload.computed_at,
            summary_text=f"macro snapshot for {payload.computed_at.date().isoformat()}",
            saliency_score=0.5,
            confidence_percent=80.0,
            source_breakdown=dict(payload.source_breakdown),
            metadata={"request_mode": request_mode, "subject_key": payload.subject_key},
        )
        return self.repository.create_macro_context_snapshot(snapshot)


class FakeIndustryService:
    def __init__(self, repository: ContextSnapshotRepository) -> None:
        self.repository = repository
        self.calls: list[tuple[datetime, str, str]] = []

    def create_from_refresh_payload(self, payload, *, request_mode: str = "live") -> IndustryContextSnapshot:
        self.calls.append((payload.computed_at, request_mode, payload.subject_key))
        snapshot = IndustryContextSnapshot(
            industry_key=payload.subject_key,
            industry_label=payload.subject_label,
            computed_at=payload.computed_at,
            summary_text=f"industry snapshot for {payload.subject_key} on {payload.computed_at.date().isoformat()}",
            direction="neutral",
            saliency_score=0.5,
            confidence_percent=80.0,
            source_breakdown=dict(payload.source_breakdown),
            metadata={"request_mode": request_mode, "queries": list(payload.diagnostics.get("queries", []))},
        )
        return self.repository.create_industry_context_snapshot(snapshot)


class RateLimitedIndustryService:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, str, str]] = []

    def create_from_refresh_payload(self, payload, *, request_mode: str = "live"):
        self.calls.append((payload.computed_at, request_mode, payload.subject_key))
        raise RuntimeError("HTTP 429 Too Many Requests")


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class ReconstructContextScriptTests(unittest.TestCase):
    def test_default_backfill_range_uses_latest_business_week(self) -> None:
        start, end = reconstruct_context.default_backfill_range(date(2026, 4, 26))

        self.assertEqual(date(2026, 4, 20), start)
        self.assertEqual(date(2026, 4, 24), end)

    def test_iter_business_days_skips_weekends(self) -> None:
        days = list(reconstruct_context.iter_business_days(date(2026, 4, 24), date(2026, 4, 28)))

        self.assertEqual(
            [date(2026, 4, 24), date(2026, 4, 27), date(2026, 4, 28)],
            days,
        )

    def test_run_context_backfill_uses_replay_mode_and_skips_weekends(self) -> None:
        session = create_session()
        try:
            repository = ContextSnapshotRepository(session)
            macro_service = FakeMacroService(repository)
            industry_service = FakeIndustryService(repository)
            taxonomy_service = FakeTaxonomyService()

            totals = reconstruct_context.run_context_backfill(
                session,
                date(2026, 4, 20),
                date(2026, 4, 26),
                request_mode="replay",
                macro_service=macro_service,
                industry_service=industry_service,
                taxonomy_service=taxonomy_service,
                inter_request_delay_seconds=0.0,
            )

            self.assertEqual(5, totals["days"])
            self.assertEqual(5, totals["macro_snapshots"])
            self.assertEqual(10, totals["industry_snapshots"])
            self.assertEqual(0, totals["warnings"])
            self.assertEqual(0, totals["rate_limit_errors"])
            self.assertEqual(0, totals["aborted_for_rate_limit"])

            self.assertEqual(5, len(macro_service.calls))
            self.assertTrue(all(call[1] == "replay" for call in macro_service.calls))
            self.assertEqual(
                [date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24)],
                [call[0].date() for call in macro_service.calls],
            )
            self.assertTrue(all(call[2] == "global_macro" for call in macro_service.calls))

            self.assertEqual(10, len(industry_service.calls))
            self.assertTrue(all(call[1] == "replay" for call in industry_service.calls))
            self.assertEqual(
                [
                    date(2026, 4, 20),
                    date(2026, 4, 20),
                    date(2026, 4, 21),
                    date(2026, 4, 21),
                    date(2026, 4, 22),
                    date(2026, 4, 22),
                    date(2026, 4, 23),
                    date(2026, 4, 23),
                    date(2026, 4, 24),
                    date(2026, 4, 24),
                ],
                [call[0].date() for call in industry_service.calls],
            )
            self.assertEqual(
                ["tech", "energy", "tech", "energy", "tech", "energy", "tech", "energy", "tech", "energy"],
                [call[2] for call in industry_service.calls],
            )

            self.assertEqual(5, len(repository.list_macro_context_snapshots(limit=20)))
            self.assertEqual(10, len(repository.list_industry_context_snapshots(limit=20)))
        finally:
            session.close()

    def test_run_context_backfill_stops_after_consecutive_rate_limits(self) -> None:
        session = create_session()
        try:
            repository = ContextSnapshotRepository(session)
            macro_service = FakeMacroService(repository)
            industry_service = RateLimitedIndustryService()
            taxonomy_service = FakeTaxonomyService()

            totals = reconstruct_context.run_context_backfill(
                session,
                date(2026, 4, 20),
                date(2026, 4, 20),
                request_mode="replay",
                macro_service=macro_service,
                industry_service=industry_service,
                taxonomy_service=taxonomy_service,
                inter_request_delay_seconds=0.0,
                rate_limit_backoff_seconds=0.0,
                max_consecutive_rate_limit_errors=2,
                sleep_fn=lambda *_args, **_kwargs: None,
            )

            self.assertEqual(1, totals["days"])
            self.assertEqual(1, totals["macro_snapshots"])
            self.assertEqual(0, totals["industry_snapshots"])
            self.assertEqual(2, totals["warnings"])
            self.assertEqual(2, totals["rate_limit_errors"])
            self.assertEqual(1, totals["aborted_for_rate_limit"])
            self.assertEqual(2, len(industry_service.calls))
        finally:
            session.close()
