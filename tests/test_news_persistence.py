from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import Text, create_engine
from sqlalchemy.orm import sessionmaker

from trade_proposer_app.persistence.models import Base, HistoricalNewsRecord
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.services.news import NewsIngestionService, NewsProvider, NewsArticle, ProviderCredential

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

class MockNewsProvider(NewsProvider):
    name = "Mock"
    provider_key = "mock"
    historical_replay_safe = True
    
    def fetch(self, ticker, limit, start_at=None, end_at=None):
        return [
            NewsArticle(
                title=f"Mock News for {ticker} 1",
                summary="Summary 1",
                publisher="MockPub",
                link=f"http://mock.com/{ticker}/1",
                published_at=datetime.now(timezone.utc) - timedelta(hours=1)
            ),
            NewsArticle(
                title=f"Mock News for {ticker} 2",
                summary="Summary 2",
                publisher="MockPub",
                link=f"http://mock.com/{ticker}/2",
                published_at=datetime.now(timezone.utc) - timedelta(hours=2)
            )
        ]
    
    def fetch_topic(self, topic, limit, start_at=None, end_at=None):
        return self.fetch(topic, limit, start_at, end_at)

def test_news_lazy_hydration(session):
    repo = HistoricalNewsRepository(session)
    provider = MockNewsProvider(credential=ProviderCredential(provider="mock"))
    service = NewsIngestionService(providers=[provider], historical_news=repo)
    
    ticker = "AAPL"
    start_at = datetime.now(timezone.utc) - timedelta(days=1)
    end_at = datetime.now(timezone.utc)
    
    # 1. First fetch - should call provider and save to DB
    bundle = service.fetch(ticker, start_at=start_at, end_at=end_at)
    assert len(bundle.articles) == 2
    assert "Mock" in bundle.feeds_used
    
    # Verify saved in DB
    local = repo.list_news(ticker, start_at=start_at, end_at=end_at)
    assert len(local) == 2
    
    # 2. Second fetch - should use DB (database feed)
    # We need at least 3 articles for the threshold in my implementation, or 2 for topic.
    # Actually I set 3 for ticker, 2 for topic. Let's adjust Mock to return 3.
    
    class MockNewsProvider3(MockNewsProvider):
        def fetch(self, ticker, limit, start_at=None, end_at=None):
            return super().fetch(ticker, limit, start_at, end_at) + [
                NewsArticle(title="3", summary="3", publisher="3", link="3", published_at=end_at - timedelta(minutes=1))
            ]
            
    service = NewsIngestionService(providers=[MockNewsProvider3(credential=ProviderCredential(provider="mock"))], historical_news=repo)
    bundle2 = service.fetch(ticker, start_at=start_at, end_at=end_at)
    assert len(bundle2.articles) == 3
    assert "database" in bundle2.feeds_used
    assert "Mock" in bundle2.feeds_used # Saved the 3rd one
    
    # 3. Third fetch - now should be 100% from DB
    service = NewsIngestionService(providers=[MockNewsProvider3(credential=ProviderCredential(provider="mock"))], historical_news=repo)
    bundle3 = service.fetch(ticker, start_at=start_at, end_at=end_at)
    assert len(bundle3.articles) >= 3
    assert "database" in bundle3.feeds_used
    assert "Mock" not in bundle3.feeds_used

def test_news_topic_lazy_hydration(session):
    repo = HistoricalNewsRepository(session)
    provider = MockNewsProvider(credential=ProviderCredential(provider="mock"))
    service = NewsIngestionService(providers=[provider], historical_news=repo)
    
    topic = "semiconductors"
    start_at = datetime.now(timezone.utc) - timedelta(days=1)
    end_at = datetime.now(timezone.utc)
    
    # 1. Fetch topic
    bundle = service.fetch_topic(topic, start_at=start_at, end_at=end_at)
    assert len(bundle.articles) == 2
    
    # 2. Second fetch from a fresh service instance (threshold for topic is 2)
    service = NewsIngestionService(providers=[provider], historical_news=repo)
    bundle2 = service.fetch_topic(topic, start_at=start_at, end_at=end_at)
    assert "database" in bundle2.feeds_used


def test_historical_news_link_column_is_text() -> None:
    assert isinstance(HistoricalNewsRecord.__table__.c.link.type, Text)


def test_historical_news_replay_filters_by_available_at(session):
    repo = HistoricalNewsRepository(session)
    published_at = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
    repo.save_news(
        "AAPL",
        "fixture",
        [
            NewsArticle(
                title="Known immediately",
                summary="summary",
                publisher="Reuters",
                link="known",
                published_at=published_at,
                available_at=published_at + timedelta(minutes=1),
            ),
            NewsArticle(
                title="Late provider availability",
                summary="summary",
                publisher="Reuters",
                link="late",
                published_at=published_at,
                available_at=published_at + timedelta(hours=4),
            ),
        ],
    )

    replay_articles = repo.list_news(
        "AAPL",
        start_at=published_at - timedelta(hours=1),
        end_at=published_at + timedelta(hours=1),
        available_at=published_at + timedelta(minutes=30),
    )

    assert [article.title for article in replay_articles] == ["Known immediately"]
    assert replay_articles[0].availability_metadata["available_at_inferred_from"] == "provider"


def test_save_news_persists_ingested_at_when_distinct_from_created_at(session):
    repo = HistoricalNewsRepository(session)
    published_at = datetime(2024, 1, 5, 14, 0, tzinfo=timezone.utc)
    ingested_at = published_at + timedelta(hours=2)
    repo.save_news(
        "AAPL",
        "test",
        [
            NewsArticle(
                title="Delayed ingestion",
                link="https://example.com/delayed-ingestion",
                published_at=published_at,
                available_at=published_at + timedelta(minutes=5),
                ingested_at=ingested_at,
            )
        ],
    )

    article = repo.list_news("AAPL", available_at=published_at + timedelta(hours=1), limit=1)[0]
    assert article.ingested_at == ingested_at


def test_save_news_infers_available_at_from_published_at(session):
    repo = HistoricalNewsRepository(session)
    published_at = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
    repo.save_news(
        "AAPL",
        "fixture",
        [
            NewsArticle(
                title="Inferred availability",
                summary="summary",
                publisher="Reuters",
                link="inferred",
                published_at=published_at,
            )
        ],
    )

    article = repo.list_news("AAPL", available_at=published_at, limit=1)[0]
    assert article.available_at == published_at
    assert article.availability_metadata["available_at_inferred_from"] == "published_at"
    assert article.availability_metadata["point_in_time_confidence"] == 0.6


def test_save_news_rolls_back_on_commit_failure(session, monkeypatch):
    repo = HistoricalNewsRepository(session)
    article = NewsArticle(
        title="Rollback test",
        summary="summary",
        publisher="Reuters",
        link="https://news.google.com/rss/articles/" + "a" * 700,
        published_at=datetime.now(timezone.utc),
    )

    rollback_called = []
    original_rollback = session.rollback

    def failing_commit():
        raise RuntimeError("boom")

    def rollback_spy():
        rollback_called.append(True)
        return original_rollback()

    monkeypatch.setattr(session, "commit", failing_commit)
    monkeypatch.setattr(session, "rollback", rollback_spy)

    with pytest.raises(RuntimeError):
        repo.save_news("AAPL", "googlenews", [article])

    assert rollback_called
    # Session should remain usable after rollback.
    assert session.query(HistoricalNewsRecord).count() == 0


def test_save_news_normalizes_overlong_links(session):
    repo = HistoricalNewsRepository(session)
    article = NewsArticle(
        title="Long link",
        summary="summary",
        publisher="Reuters",
        link="https://news.google.com/rss/articles/" + "a" * 700,
        published_at=datetime.now(timezone.utc),
    )

    repo.save_news("AAPL", "googlenews", [article])

    record = session.query(HistoricalNewsRecord).one()
    assert len(record.link) <= 512
    assert "__sha256__" in record.link
    assert record.link.startswith("https://news.google.com/rss/articles/")
