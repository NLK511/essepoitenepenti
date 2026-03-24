import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from trade_proposer_app.services.social import NitterProvider


class NitterProviderQueryTests(unittest.TestCase):
    @patch("trade_proposer_app.services.social.httpx.get")
    def test_fetch_subject_uses_all_subject_queries_when_no_limit_is_configured(self, mock_get) -> None:
        response = MagicMock()
        response.status_code = 200
        response.text = "<html></html>"
        mock_get.return_value = response

        provider = NitterProvider(base_url="http://nitter.example", timeout=1.0, max_items_per_query=10, query_window_hours=24)
        queries = ["fed", "inflation", "ecb", "war", "military tensions"]

        with patch.object(provider, "_parse_search_html", return_value=[]):
            bundle = provider.fetch_subject("global_macro", queries, scope_tag="macro")

        self.assertEqual(mock_get.call_count, len(queries))
        self.assertEqual(bundle.query_diagnostics["macro_queries"], queries)
        self.assertEqual(bundle.coverage["social_count"], 0)

    def test_parse_search_html_extracts_items_without_timeline_footer(self) -> None:
        provider = NitterProvider(base_url="http://nitter.example")
        html = (
            '<div class="timeline-item">'
            '<a class="fullname">Macro News</a>'
            '<a class="username">@macro_news</a>'
            '<a href="/macro_news/status/1234567890">status</a>'
            '<span class="tweet-date"><a title="Mar 23, 2026 · 12:30 PM UTC">Mar 23</a></span>'
            '<div class="tweet-content media-body">The ECB signals a shift in European monetary policy.</div>'
            '<span class="icon-heart"></span> 12'
            '<span class="icon-retweet"></span> 3'
            '<span class="icon-reply"></span> 1'
            '</div>'
        )

        items = provider._parse_search_html(
            html,
            ticker="global_macro",
            query_profile={"macro_queries": ["ecb"], "industry_queries": [], "ticker_queries": [], "exclude_keywords": []},
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.body, "The ECB signals a shift in European monetary policy.")
        self.assertIn("macro", item.scope_tags)
        self.assertEqual(item.author_handle, "macro_news")
        self.assertEqual(item.item_id, "1234567890")

    @patch("trade_proposer_app.services.social.httpx.get")
    def test_fetch_subject_records_raw_parsed_and_filtered_counts(self, mock_get) -> None:
        now = datetime.now(timezone.utc)
        recent = now.strftime("%b %d, %Y · %I:%M %p UTC")
        stale = (now - timedelta(hours=24)).strftime("%b %d, %Y · %I:%M %p UTC")
        response = MagicMock()
        response.status_code = 200
        response.text = (
            '<div class="timeline-item">'
            '<a class="fullname">Macro News</a>'
            '<a class="username">@macro_news</a>'
            '<a href="/macro_news/status/111">status</a>'
            f'<span class="tweet-date"><a title="{recent}">recent</a></span>'
            '<div class="tweet-content media-body">ECB guidance strengthens European monetary policy.</div>'
            '</div>'
            '<div class="timeline-item">'
            '<a class="fullname">Macro News</a>'
            '<a class="username">@macro_news</a>'
            '<a href="/macro_news/status/222">status</a>'
            f'<span class="tweet-date"><a title="{stale}">stale</a></span>'
            '<div class="tweet-content media-body">Old market noise.</div>'
            '</div>'
            '<div class="timeline-item">'
            '<a class="fullname">Macro News</a>'
            '<a class="username">@macro_news</a>'
            '<a href="/macro_news/status/333">status</a>'
            f'<span class="tweet-date"><a title="{recent}">recent</a></span>'
            '<div class="tweet-content media-body">skip this one.</div>'
            '</div>'
        )
        mock_get.return_value = response

        provider = NitterProvider(base_url="http://nitter.example", timeout=1.0, max_items_per_query=10, query_window_hours=12)
        bundle = provider._fetch_queries(  # noqa: SLF001
            subject_key="global_macro",
            queries=["ecb"],
            scope_tag="macro",
            ticker="global_macro",
            query_profile={"macro_queries": ["ecb"], "industry_queries": [], "ticker_queries": [], "exclude_keywords": ["skip"]},
        )

        stats = bundle.query_diagnostics["macro_query_stats"][0]
        self.assertEqual(stats["raw_item_count"], 3)
        self.assertEqual(stats["parsed_item_count"], 3)
        self.assertEqual(stats["filtered_item_count"], 1)
        self.assertEqual(bundle.coverage["social_count"], 1)
