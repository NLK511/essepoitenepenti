from datetime import datetime, timezone
import unittest

from trade_proposer_app.domain.models import NewsArticle
from trade_proposer_app.services.news import NewsIngestionService


class NewsWindowFilterTimezoneTests(unittest.TestCase):
    def test_filter_articles_for_window_handles_naive_window_bounds(self) -> None:
        article = NewsArticle(
            title="Windowed headline",
            summary="Coverage within the day",
            publisher="Reuters",
            link="https://example.com/windowed-headline",
            published_at=datetime(2026, 4, 27, 12, 0),
        )

        filtered = NewsIngestionService._filter_articles_for_window(
            [article],
            start_at=datetime(2026, 4, 27, 0, 0),
            end_at=datetime(2026, 4, 27, 23, 59),
        )

        self.assertEqual(filtered, [article])

    def test_filter_articles_for_window_excludes_out_of_window_articles(self) -> None:
        inside = NewsArticle(
            title="Inside",
            summary="Inside window",
            publisher="Reuters",
            link="https://example.com/inside",
            published_at=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        )
        outside = NewsArticle(
            title="Outside",
            summary="Outside window",
            publisher="Reuters",
            link="https://example.com/outside",
            published_at=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
        )

        filtered = NewsIngestionService._filter_articles_for_window(
            [inside, outside],
            start_at=datetime(2026, 4, 27, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 4, 27, 23, 59, tzinfo=timezone.utc),
        )

        self.assertEqual(filtered, [inside])


if __name__ == "__main__":
    unittest.main()
