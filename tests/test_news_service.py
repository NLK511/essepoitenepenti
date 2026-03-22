import unittest
from unittest.mock import MagicMock, patch

from trade_proposer_app.domain.models import NewsArticle, NewsBundle, ProviderCredential
from trade_proposer_app.services.news import NewsIngestionService, NaiveSentimentAnalyzer


class NewsIngestionServiceTests(unittest.TestCase):
    def test_fetch_without_providers_returns_empty_bundle(self):
        service = NewsIngestionService.from_provider_credentials({})
        bundle = service.fetch("AAPL")
        self.assertEqual(bundle.ticker, "AAPL")
        self.assertEqual(bundle.articles, [])
        self.assertTrue(bundle.feed_errors)
        self.assertIn("no providers configured", bundle.feed_errors[0])

    @patch("trade_proposer_app.services.news.httpx.get")
    def test_newsapi_provider_parses_articles(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "ok",
            "articles": [
                {
                    "title": "Company beats estimates",
                    "description": "Revenue surged ahead of guidance",
                    "source": {"name": "NewsAPI"},
                    "url": "https://example.com/news",
                    "publishedAt": "2026-03-15T12:00:00Z",
                }
            ],
        }
        mock_get.return_value = response

        credentials = {
            "newsapi": ProviderCredential(provider="newsapi", api_key="key", api_secret="")
        }
        service = NewsIngestionService.from_provider_credentials(credentials)
        bundle = service.fetch("AAPL")

        self.assertEqual(bundle.ticker, "AAPL")
        self.assertEqual(len(bundle.articles), 1)
        article = bundle.articles[0]
        self.assertEqual(article.title, "Company beats estimates")
        self.assertEqual(article.publisher, "NewsAPI")
        self.assertEqual(article.link, "https://example.com/news")
        self.assertFalse(bundle.feed_errors)
        self.assertEqual(bundle.feeds_used, ["NewsAPI"])

    def test_naive_sentiment_analyzer_scores_positive_headlines(self) -> None:
        analyzer = NaiveSentimentAnalyzer()
        article = NewsArticle(
            title="Company beats revenue and upgrades guidance",
            summary="Management expects continued growth",
            publisher="Example",
            link="https://example.com/upgrades",
            published_at=None,
        )
        bundle = NewsBundle(ticker="IME", articles=[article], feeds_used=["NewsAPI"])
        result = analyzer.analyze(bundle)
        self.assertGreater(result["score"], 0.0)
        self.assertEqual(result["label"], "POSITIVE")
        self.assertAlmostEqual(result["news_point_count"], 1)
        self.assertEqual(result["sentiment_volatility"], 0.0)
        self.assertTrue(0.0 < result["news_items"][0]["compound"] < 1.0)

    def test_naive_sentiment_analyzer_weights_summary_keywords(self) -> None:
        analyzer = NaiveSentimentAnalyzer()
        article = NewsArticle(
            title="Quiet update",
            summary="Guidance now exceeds forecasts and resilient demand keeps momentum rolling",
            publisher="Example",
            link="https://example.com/summary",
            published_at=None,
        )
        bundle = NewsBundle(ticker="IME", articles=[article], feeds_used=["NewsAPI"])
        result = analyzer.analyze(bundle)
        self.assertGreater(result["score"], 0.0)
        self.assertEqual(result["label"], "POSITIVE")
        self.assertGreater(result["keyword_hits"], 0)
        self.assertGreater(result["news_items"][0]["compound"], 0.0)

    def test_naive_sentiment_analyzer_detects_multi_word_phrases(self) -> None:
        analyzer = NaiveSentimentAnalyzer()
        article = NewsArticle(
            title="Company beats expectations",
            summary="Sales beat forecasts and record demand keeps the momentum",
            publisher="Example",
            link="https://example.com/phrase",
            published_at=None,
        )
        bundle = NewsBundle(ticker="IME", articles=[article], feeds_used=["NewsAPI"])
        result = analyzer.analyze(bundle)
        self.assertGreater(result["score"], 0.0)
        self.assertEqual(result["label"], "POSITIVE")
        self.assertGreater(result["keyword_hits"], 0)
        self.assertGreater(result["news_items"][0]["compound"], 0.0)

    def test_naive_sentiment_analyzer_records_coverage_insights_for_zero_hits(self) -> None:
        analyzer = NaiveSentimentAnalyzer()
        article = NewsArticle(
            title="Neutral update",
            summary="No material changes were reported today",
            publisher="Example",
            link="https://example.com/neutral",
            published_at=None,
        )
        bundle = NewsBundle(ticker="Z", articles=[article], feeds_used=["NewsAPI"])
        result = analyzer.analyze(bundle)
        self.assertEqual(result["keyword_hits"], 0)
        self.assertTrue(any("no sentiment keywords" in insight for insight in result["coverage_insights"]))
