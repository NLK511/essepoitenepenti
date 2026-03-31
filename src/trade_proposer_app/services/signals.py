from __future__ import annotations

from trade_proposer_app.domain.models import NewsBundle, SignalBundle, SignalItem
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.social import SocialIngestionService


class SignalIngestionService:
    def __init__(
        self,
        *,
        news_service: NewsIngestionService | None = None,
        social_service: SocialIngestionService | None = None,
    ) -> None:
        self.news_service = news_service
        self.social_service = social_service

    def fetch(self, ticker: str) -> SignalBundle:
        bundle = SignalBundle(ticker=ticker)
        if self.news_service is not None:
            news_bundle = self.news_service.fetch(ticker)
            bundle.items.extend(self._signal_items_from_news(news_bundle))
            bundle.feeds_used.extend(news_bundle.feeds_used)
            bundle.feed_errors.extend(news_bundle.feed_errors)
            bundle.coverage["news_count"] = len(news_bundle.articles)
        if self.social_service is not None:
            social_bundle = self.social_service.fetch(ticker)
            bundle.items.extend(social_bundle.items)
            bundle.feeds_used.extend(social_bundle.feeds_used)
            bundle.feed_errors.extend(social_bundle.feed_errors)
            bundle.coverage.update(social_bundle.coverage)
            if social_bundle.query_diagnostics:
                bundle.query_diagnostics.update(social_bundle.query_diagnostics)
        bundle.feeds_used = list(dict.fromkeys(bundle.feeds_used))
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        bundle.coverage.setdefault("news_count", 0)
        bundle.coverage.setdefault("social_count", 0)
        bundle.coverage["total_count"] = len(bundle.items)
        return bundle

    def _signal_items_from_news(self, bundle: NewsBundle) -> list[SignalItem]:
        items: list[SignalItem] = []
        for article in bundle.articles:
            items.append(
                SignalItem(
                    source_type="news",
                    provider="news_bundle",
                    title=article.title,
                    body=article.summary or "",
                    publisher=article.publisher,
                    link=article.link,
                    published_at=article.published_at,
                    scope_tags=["ticker"],
                    quality_score=0.8,
                    credibility_score=0.9,
                    dedupe_key=article.link or article.title,
                )
            )
        return items
