import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from trade_proposer_app.domain.models import NewsArticle, NewsBundle, ProviderCredential
from trade_proposer_app.services.news import GoogleNewsProvider, NewsIngestionService, NaiveSentimentAnalyzer, NewsProvider, YahooFinanceProvider


class NewsIngestionServiceTests(unittest.TestCase):
    @patch("trade_proposer_app.services.news.yf.Ticker")
    @patch("trade_proposer_app.services.news.httpx.get")
    def test_fetch_uses_google_and_yahoo_by_default(self, mock_get, mock_ticker):
        google_response = MagicMock()
        google_response.status_code = 200
        google_response.text = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
            <item>
                <title>Google News Article</title>
                <link>https://example.com/gnews</link>
                <pubDate>Thu, 26 Mar 2026 00:00:00 GMT</pubDate>
                <description><![CDATA[<p>Some description</p>]]></description>
                <source url="https://reuters.com">Reuters</source>
            </item>
        </channel></rss>"""

        def google_side_effect(url, *args, **kwargs):
            self.assertEqual(url, "https://news.google.com/rss/search")
            params = kwargs["params"]
            self.assertIn("site:reuters.com", params["q"])
            self.assertIn("when:7d", params["q"])
            return google_response

        mock_get.side_effect = google_side_effect

        yahoo_ticker = MagicMock()
        yahoo_ticker.news = [
            {
                "content": {
                    "title": "Yahoo Finance Article",
                    "summary": "Yahoo summary",
                    "pubDate": "2026-03-26T00:00:00Z",
                },
                "provider": {"displayName": "Yahoo Finance"},
                "clickThroughUrl": {"url": "https://example.com/yfinance"},
            }
        ]
        mock_ticker.return_value = yahoo_ticker

        service = NewsIngestionService.from_provider_credentials({})
        bundle = service.fetch("AAPL")

        self.assertEqual(bundle.ticker, "AAPL")
        self.assertEqual(len(bundle.articles), 2)
        self.assertEqual(set(bundle.feeds_used), {"GoogleNews", "YahooFinance"})
        self.assertFalse(bundle.feed_errors)
        self.assertIn("Google News Article", [article.title for article in bundle.articles])
        self.assertIn("Yahoo Finance Article", [article.title for article in bundle.articles])

    @patch("trade_proposer_app.services.news.httpx.get")
    def test_google_news_provider_filters_to_whitelisted_sources(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.text = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
            <item>
                <title>Allowed source story</title>
                <link>https://news.google.com/rss/articles/1</link>
                <pubDate>Thu, 26 Mar 2026 00:00:00 GMT</pubDate>
                <description>Allowed</description>
                <source url="https://bloomberg.com">Bloomberg</source>
            </item>
            <item>
                <title>Blocked source story</title>
                <link>https://news.google.com/rss/articles/2</link>
                <pubDate>Thu, 26 Mar 2026 00:00:00 GMT</pubDate>
                <description>Blocked</description>
                <source url="https://example.com">Example</source>
            </item>
        </channel></rss>"""
        mock_get.return_value = response

        provider = GoogleNewsProvider(ProviderCredential(provider="googlenews"))
        articles = provider.fetch_topic("inflation", 10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Allowed source story")
        self.assertEqual(articles[0].publisher, "Bloomberg")
        called_params = mock_get.call_args.kwargs["params"]
        self.assertIn("site:bloomberg.com", called_params["q"])
        self.assertIn("site:reuters.com", called_params["q"])
        self.assertIn("when:7d", called_params["q"])

    def test_yahoo_finance_provider_parses_nested_news_payload(self):
        provider = YahooFinanceProvider(ProviderCredential(provider="yahoofinance"))
        with patch("trade_proposer_app.services.news.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.news = [
                {
                    "content": {
                        "title": "Yahoo headline",
                        "summary": "Yahoo summary",
                        "pubDate": "2026-03-26T00:00:00Z",
                    },
                    "provider": {"displayName": "Yahoo Finance"},
                    "clickThroughUrl": {"url": "https://finance.yahoo.com/news/yahoo-headline"},
                }
            ]
            articles = provider.fetch("AAPL", 10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Yahoo headline")
        self.assertEqual(articles[0].summary, "Yahoo summary")
        self.assertEqual(articles[0].publisher, "Yahoo Finance")
        self.assertEqual(articles[0].link, "https://finance.yahoo.com/news/yahoo-headline")

    @patch("trade_proposer_app.services.news.httpx.get")
    def test_newsapi_is_disabled_by_default_even_when_credentials_exist(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.text = """<?xml version="1.0" encoding="UTF-8"?><rss><channel></channel></rss>"""
        mock_get.return_value = response

        with patch("trade_proposer_app.services.news.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.news = []
            service = NewsIngestionService.from_provider_credentials(
                {"newsapi": ProviderCredential(provider="newsapi", api_key="key", api_secret="")}
            )
            bundle = service.fetch("AAPL")

        self.assertNotIn("NewsAPI", bundle.feeds_used)
        self.assertFalse(any("newsapi.org" in str(call.args[0]) for call in mock_get.call_args_list))

    @patch("trade_proposer_app.services.news.httpx.get")
    def test_finnhub_topic_queries_are_skipped(self, mock_get):
        def side_effect(url, *args, **kwargs):
            self.assertEqual(url, "https://news.google.com/rss/search")
            self.assertIn("site:reuters.com", kwargs["params"]["q"])
            response = MagicMock()
            response.status_code = 200
            response.text = """<?xml version="1.0" encoding="UTF-8"?><rss><channel><item>
                <title>Inflation headline</title>
                <link>https://news.google.com/rss/articles/1</link>
                <pubDate>Thu, 26 Mar 2026 00:00:00 GMT</pubDate>
                <description>Inflation story</description>
                <source url="https://reuters.com">Reuters</source>
            </item></channel></rss>"""
            return response

        mock_get.side_effect = side_effect

        service = NewsIngestionService.from_provider_credentials(
            {"finnhub": ProviderCredential(provider="finnhub", api_key="key", api_secret="")}
        )
        bundle = service.fetch_topic("inflation")

        self.assertEqual(bundle.ticker, "inflation")
        self.assertEqual(set(bundle.feeds_used), {"GoogleNews"})
        self.assertFalse(any("finnhub" in error.lower() for error in bundle.feed_errors))

    @patch("trade_proposer_app.services.news.yf.Ticker")
    @patch("trade_proposer_app.services.news.httpx.get")
    def test_historical_ticker_fetch_prefers_finnhub_and_skips_live_fallbacks(self, mock_get, mock_ticker):
        finnhub_response = MagicMock()
        finnhub_response.status_code = 200
        finnhub_response.json.return_value = [
            {
                "headline": "Finnhub historical article",
                "summary": "Historical company news",
                "source": "Reuters",
                "url": "https://example.com/finnhub",
                "datetime": int(datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc).timestamp()),
            }
        ]

        def side_effect(url, *args, **kwargs):
            self.assertEqual(url, "https://finnhub.io/api/v1/company-news")
            self.assertEqual(kwargs["params"]["symbol"], "AAPL")
            return finnhub_response

        mock_get.side_effect = side_effect
        mock_ticker.return_value.news = [
            {
                "content": {
                    "title": "Yahoo future article",
                    "summary": "Should not be used in historical mode",
                    "pubDate": "2026-03-27T00:00:00Z",
                }
            }
        ]

        service = NewsIngestionService.from_provider_credentials(
            {"finnhub": ProviderCredential(provider="finnhub", api_key="key", api_secret="")}
        )
        bundle = service.fetch(
            "AAPL",
            start_at=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 26, 23, 59, tzinfo=timezone.utc),
            request_mode="replay",
        )

        self.assertEqual([article.title for article in bundle.articles], ["Finnhub historical article"])
        self.assertEqual(bundle.feeds_used, ["Finnhub"])
        mock_ticker.assert_not_called()

    def test_historical_window_filters_future_and_undated_articles(self) -> None:
        class StubProvider:
            name = "Stub"
            supports_ticker = True
            supports_topic = False
            supports_live_windowed_queries = True
            supports_replay_windowed_queries = True
            counts_as_primary_news = True

            def fetch(self, ticker, limit, *, start_at=None, end_at=None):
                return [
                    NewsArticle(
                        title="In window",
                        summary="ok",
                        publisher="Stub",
                        link="https://example.com/in-window",
                        published_at=datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
                    ),
                    NewsArticle(
                        title="Future",
                        summary="future",
                        publisher="Stub",
                        link="https://example.com/future",
                        published_at=datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc),
                    ),
                    NewsArticle(
                        title="Undated",
                        summary="missing timestamp",
                        publisher="Stub",
                        link="https://example.com/undated",
                        published_at=None,
                    ),
                ]

        service = NewsIngestionService([StubProvider()], max_articles=10)
        bundle = service.fetch(
            "AAPL",
            start_at=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 26, 23, 59, tzinfo=timezone.utc),
            request_mode="replay",
        )

        self.assertEqual([article.title for article in bundle.articles], ["In window"])
        self.assertEqual(bundle.feeds_used, ["Stub"])

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

    def test_live_windowed_topic_fetch_uses_google_news_when_topic_provider_is_live_only(self) -> None:
        service = NewsIngestionService.from_provider_credentials(
            {"finnhub": ProviderCredential(provider="finnhub", api_key="key", api_secret="")}
        )
        with patch.object(GoogleNewsProvider, "fetch_topic", return_value=[
            NewsArticle(
                title="Inflation headline",
                summary="Inflation story",
                publisher="Reuters",
                link="https://example.com/google-live-topic",
                published_at=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
            )
        ]) as google_fetch:
            bundle = service.fetch_topic(
                "inflation",
                start_at=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
                end_at=datetime(2026, 3, 26, 23, 59, tzinfo=timezone.utc),
                request_mode="live",
                primary_only=True,
            )

        self.assertEqual([article.title for article in bundle.articles], ["Inflation headline"])
        self.assertEqual(bundle.feeds_used, ["GoogleNews"])
        self.assertEqual(bundle.feed_errors, [])
        google_fetch.assert_called_once()

    def test_replay_windowed_topic_fetch_explains_provider_exclusions(self) -> None:
        service = NewsIngestionService.from_provider_credentials(
            {"finnhub": ProviderCredential(provider="finnhub", api_key="key", api_secret="")}
        )
        bundle = service.fetch_topic(
            "inflation",
            start_at=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 26, 23, 59, tzinfo=timezone.utc),
            request_mode="replay",
            primary_only=True,
        )

        self.assertEqual(bundle.articles, [])
        self.assertTrue(any("no providers eligible" in error for error in bundle.feed_errors))
        self.assertTrue(any("query_type=topic" in error for error in bundle.feed_errors))
        self.assertTrue(any("mode=replay" in error for error in bundle.feed_errors))
        self.assertTrue(any("Finnhub(topic unsupported)" in error for error in bundle.feed_errors))
        self.assertTrue(any("GoogleNews(replay window unsupported)" in error for error in bundle.feed_errors))

    def test_primary_only_filters_supporting_only_providers(self) -> None:
        class PrimaryTopicProvider(NewsProvider):
            name = "PrimaryTopic"
            provider_key = "primarytopic"
            supports_ticker = False
            supports_topic = True
            supports_live_windowed_queries = True
            supports_replay_windowed_queries = False
            counts_as_primary_news = True

            def fetch(self, ticker, limit, *, start_at=None, end_at=None):
                raise AssertionError("ticker fetch should not be used")

            def fetch_topic(self, topic, limit, *, start_at=None, end_at=None):
                return [
                    NewsArticle(
                        title="Primary only article",
                        summary="Primary source coverage",
                        publisher="Reuters",
                        link="https://example.com/primary-only",
                        published_at=datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc),
                    )
                ]

        class SupportingTopicProvider(NewsProvider):
            name = "SupportingTopic"
            provider_key = "supportingtopic"
            supports_ticker = False
            supports_topic = True
            supports_live_windowed_queries = True
            supports_replay_windowed_queries = False
            counts_as_primary_news = False

            def fetch(self, ticker, limit, *, start_at=None, end_at=None):
                raise AssertionError("ticker fetch should not be used")

            def fetch_topic(self, topic, limit, *, start_at=None, end_at=None):
                raise AssertionError("supporting-only provider should be excluded by primary_only")

        service = NewsIngestionService(
            [
                SupportingTopicProvider(ProviderCredential(provider="supportingtopic")),
                PrimaryTopicProvider(ProviderCredential(provider="primarytopic")),
            ],
            max_articles=10,
        )
        bundle = service.fetch_topic(
            "inflation",
            start_at=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 26, 23, 59, tzinfo=timezone.utc),
            request_mode="live",
            primary_only=True,
        )

        self.assertEqual([article.title for article in bundle.articles], ["Primary only article"])
        self.assertEqual(bundle.feeds_used, ["PrimaryTopic"])

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
