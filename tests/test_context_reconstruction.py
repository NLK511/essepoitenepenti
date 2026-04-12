import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import (
    MacroContextRefreshPayload,
    MacroContextSnapshot,
    NewsArticle,
    NewsBundle,
    SignalBundle,
)
from trade_proposer_app.persistence.models import Base
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.macro_context_refresh import MacroContextRefreshService


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


class ContextReconstructionTests(unittest.TestCase):
    def test_macro_context_refresh_respects_as_of(self) -> None:
        social_service = MagicMock()
        news_service = MagicMock()
        
        social_service.analyze_subject.return_value = {
            "sentiment": {"score": 0.5, "label": "POSITIVE", "item_count": 5, "items": []},
            "bundle": MagicMock(feeds_used=["twitter"])
        }
        
        service = MacroContextRefreshService(
            social_service=social_service,
            news_service=news_service,
        )
        
        as_of = datetime(2026, 4, 1, tzinfo=timezone.utc)
        service.refresh(as_of=as_of)
        
        # Verify that social service was called with the correct window
        social_service.analyze_subject.assert_called_once()
        args, kwargs = social_service.analyze_subject.call_args
        self.assertEqual(as_of, kwargs["end_at"])
        self.assertEqual(as_of - timedelta(hours=24), kwargs["start_at"])

    def test_macro_context_service_uses_as_of_for_news_fetching(self) -> None:
        session = create_session()
        try:
            repository = ContextSnapshotRepository(session)
            news_service = MagicMock()
            
            # Mock news fetching to return some articles
            news_bundle = NewsBundle(ticker="Global Macro", feeds_used=["TestProvider"])
            news_sentiment = {
                "news_items": [
                    {
                        "title": "Fed hints at rate cut",
                        "summary": "Inflation is cooling down.",
                        "publisher": "Reuters",
                        "published_at": "2026-03-31T12:00:00Z"
                    }
                ]
            }
            news_service.fetch_topics.return_value = news_bundle
            news_service.analyze_bundle.return_value = {"sentiment": news_sentiment}
            
            service = MacroContextService(repository, news_service=news_service)
            
            as_of = datetime(2026, 4, 1, tzinfo=timezone.utc)
            payload = MacroContextRefreshPayload(
                subject_key="global_macro",
                subject_label="Global Macro",
                computed_at=as_of
            )
            
            service.create_from_refresh_payload(payload)
            
            # Verify that news service was called with correct historical window
            news_service.fetch_topics.assert_called_once()
            args, kwargs = news_service.fetch_topics.call_args
            self.assertEqual(as_of, kwargs["end_at"])
            self.assertEqual(as_of - timedelta(hours=24), kwargs["start_at"])
        finally:
            session.close()

    def test_historical_snapshot_resolution(self) -> None:
        session = create_session()
        try:
            repository = ContextSnapshotRepository(session)
            
            # Create two snapshots at different times
            t1 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc)
            
            s1 = repository.create_macro_context_snapshot(MacroContextSnapshot(computed_at=t1, summary_text="s1", saliency_score=0.5, confidence_percent=80.0))
            s2 = repository.create_macro_context_snapshot(MacroContextSnapshot(computed_at=t2, summary_text="s2", saliency_score=0.6, confidence_percent=85.0))
            
            # Request latest before 12:00
            target = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
            resolved = repository.get_latest_macro_context_snapshot_before(target)
            
            self.assertIsNotNone(resolved)
            self.assertEqual(s1.id, resolved.id)
            self.assertEqual("s1", resolved.summary_text)
            
            # Request latest before 16:00
            target_later = datetime(2026, 4, 1, 16, 0, 0, tzinfo=timezone.utc)
            resolved_later = repository.get_latest_macro_context_snapshot_before(target_later)
            
            self.assertIsNotNone(resolved_later)
            self.assertEqual(s2.id, resolved_later.id)
            self.assertEqual("s2", resolved_later.summary_text)
        finally:
            session.close()
