import json
import unittest
from unittest.mock import MagicMock

from trade_proposer_app.domain.models import NewsArticle, NewsBundle, SentimentSnapshot
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.macro_context import MacroContextService


class StubNewsService:
    def __init__(self, bundle: NewsBundle, sentiment: dict[str, object]) -> None:
        self.bundle = bundle
        self.sentiment = sentiment
        self.fetch_topics_calls: list[tuple[str, list[str]]] = []
        self.fetch_many_calls: list[list[str]] = []

    def fetch_topics(self, subject: str, queries: list[str], *, per_query_limit: int = 4) -> NewsBundle:
        self.fetch_topics_calls.append((subject, list(queries)))
        return self.bundle

    def fetch_many(self, symbols: list[str], *, per_symbol_limit: int = 3) -> NewsBundle:
        self.fetch_many_calls.append(list(symbols))
        return self.bundle

    def analyze_bundle(self, bundle: NewsBundle) -> dict[str, object]:
        return {"bundle": bundle, "sentiment": self.sentiment}


class ContextServiceTests(unittest.TestCase):
    def test_macro_context_prefers_primary_news_evidence(self) -> None:
        repository = MagicMock()
        repository.get_latest_macro_context_snapshot.return_value = None
        repository.create_macro_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="Global Macro",
            articles=[
                NewsArticle(
                    title="ECB signals eurozone rates may stay restrictive",
                    summary="Inflation remains sticky while bond yields climb",
                    publisher="Example",
                    link="https://example.com/ecb",
                )
            ],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "ECB signals eurozone rates may stay restrictive",
                        "summary": "Inflation remains sticky while bond yields climb",
                    }
                ],
                "coverage_insights": [],
            },
        )
        snapshot = SentimentSnapshot(
            id=7,
            scope="macro",
            subject_key="global_macro",
            subject_label="Global Macro",
            score=0.1,
            label="NEUTRAL",
            signals_json=json.dumps(
                {
                    "social_items": [
                        {"title": "Traders discuss ECB and yield pressure", "body": "Markets stay focused on rates"}
                    ]
                }
            ),
            diagnostics_json=json.dumps({"providers": ["nitter"]}),
            source_breakdown_json=json.dumps({"social": {"item_count": 1}}),
        )

        context = MacroContextService(repository, news_service=news_service).create_from_sentiment_snapshot(snapshot)

        self.assertEqual(context.source_breakdown["primary_news_item_count"], 1)
        self.assertNotIn("primary_news_evidence", context.missing_inputs)
        self.assertTrue(any(theme["key"] == "european_monetary_policy" for theme in context.active_themes))
        self.assertIn("NewsAPI", context.source_breakdown["primary_news_providers"])
        self.assertTrue(news_service.fetch_topics_calls)

    def test_industry_context_uses_tracked_ticker_news_first(self) -> None:
        repository = MagicMock()
        repository.get_latest_industry_context_snapshot.return_value = None
        repository.create_industry_context_snapshot.side_effect = lambda context: context
        news_bundle = NewsBundle(
            ticker="NVDA, AMD",
            articles=[
                NewsArticle(
                    title="Chip demand stays strong as AI server backlog grows",
                    summary="Semiconductor conference highlights supply chain and pricing discipline",
                    publisher="Example",
                    link="https://example.com/chips",
                )
            ],
            feeds_used=["NewsAPI"],
        )
        news_service = StubNewsService(
            news_bundle,
            {
                "news_items": [
                    {
                        "title": "Chip demand stays strong as AI server backlog grows",
                        "summary": "Semiconductor conference highlights supply chain and pricing discipline",
                    }
                ],
                "coverage_insights": [],
            },
        )
        snapshot = SentimentSnapshot(
            id=12,
            scope="industry",
            subject_key="semiconductors",
            subject_label="Semiconductors",
            score=0.2,
            label="POSITIVE",
            coverage_json=json.dumps({"tracked_tickers": ["NVDA", "AMD"]}),
            signals_json=json.dumps(
                {
                    "social_items": [
                        {"title": "AI chip launch chatter", "body": "Conference cycle continues"}
                    ]
                }
            ),
            diagnostics_json=json.dumps({"queries": ["semiconductor", "chip demand"], "providers": ["nitter"]}),
            source_breakdown_json=json.dumps({"social": {"item_count": 1}}),
        )

        context = IndustryContextService(repository, news_service=news_service).create_from_sentiment_snapshot(snapshot)

        self.assertEqual(context.source_breakdown["primary_news_item_count"], 1)
        self.assertNotIn("primary_industry_news_evidence", context.missing_inputs)
        self.assertIn("conference_cycle", context.linked_industry_themes)
        self.assertIn("backlog", context.linked_industry_themes)
        self.assertEqual(news_service.fetch_many_calls, [["NVDA", "AMD"]])


if __name__ == "__main__":
    unittest.main()
