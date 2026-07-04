from datetime import datetime, timezone

from trade_proposer_app.domain.models import NewsArticle, NewsBundle
from trade_proposer_app.services.news import NewsIngestionService, NewsProvider, ProviderCredential
from trade_proposer_app.services.signals import SignalIngestionService


class FailingReplayProvider(NewsProvider):
    name = "FailingReplay"
    provider_key = "failingreplay"
    supports_ticker = True
    supports_topic = True
    supports_live_windowed_queries = True
    supports_replay_windowed_queries = True
    counts_as_primary_news = True

    def __init__(self) -> None:
        super().__init__(ProviderCredential(provider="failingreplay"))

    def fetch(self, ticker, limit, *, start_at=None, end_at=None):
        raise AssertionError("replay must not call remote ticker providers")

    def fetch_topic(self, topic, limit, *, start_at=None, end_at=None):
        raise AssertionError("replay must not call remote topic providers")


class FakeHistoricalNews:
    def list_news(self, ticker, start_at=None, end_at=None, available_at=None, limit=10):
        return [
            NewsArticle(
                title=f"{ticker} cached article",
                summary="local cache",
                publisher="database",
                link=f"https://example.com/{ticker}",
                published_at=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
            )
        ]


class FailingSocialService:
    def fetch(self, ticker, *, start_at=None, end_at=None):
        raise AssertionError("replay must not call remote social providers")


class SparseHistoricalNews:
    def list_news(self, ticker, start_at=None, end_at=None, available_at=None, limit=10):
        return []


def test_replay_news_uses_database_even_when_provider_supports_replay() -> None:
    service = NewsIngestionService([FailingReplayProvider()], max_articles=10, historical_news=FakeHistoricalNews())

    bundle = service.fetch(
        "AAPL",
        start_at=datetime(2026, 3, 26, tzinfo=timezone.utc),
        end_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        request_mode="replay",
    )

    assert [article.title for article in bundle.articles] == ["AAPL cached article"]
    assert bundle.feeds_used == ["database"]
    assert bundle.query_diagnostics["provider_fetch_skipped"] is True


def test_replay_news_missing_database_does_not_fallback_to_provider() -> None:
    service = NewsIngestionService([FailingReplayProvider()], max_articles=10, historical_news=SparseHistoricalNews())

    bundle = service.fetch(
        "AAPL",
        start_at=datetime(2026, 3, 26, tzinfo=timezone.utc),
        end_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        request_mode="replay",
    )

    assert bundle.articles == []
    assert bundle.query_diagnostics["provider_fetch_skip_reason"] == "replay uses local historical_news only"


def test_replay_signal_fetch_skips_remote_social_service() -> None:
    news = NewsIngestionService([], max_articles=10, historical_news=FakeHistoricalNews())
    service = SignalIngestionService(news_service=news, social_service=FailingSocialService())

    bundle = service.fetch(
        "AAPL",
        start_at=datetime(2026, 3, 26, tzinfo=timezone.utc),
        end_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        request_mode="replay",
    )

    assert bundle.coverage["news_count"] == 1
    assert bundle.coverage["social_count"] == 0
    assert bundle.query_diagnostics["social"]["provider_fetch_skipped"] is True
