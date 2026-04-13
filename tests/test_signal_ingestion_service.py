import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from trade_proposer_app.domain.models import NewsBundle, SignalBundle
from trade_proposer_app.services.signals import SignalIngestionService


class SignalIngestionServiceTests(unittest.TestCase):
    def test_fetch_passes_time_window_to_underlying_services(self) -> None:
        mock_news = MagicMock()
        mock_social = MagicMock()
        
        service = SignalIngestionService(
            news_service=mock_news,
            social_service=mock_social
        )
        
        ticker = "AAPL"
        start_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end_at = datetime(2026, 4, 2, tzinfo=timezone.utc)
        
        mock_news.fetch.return_value = NewsBundle(ticker=ticker)
        mock_social.fetch.return_value = SignalBundle(ticker=ticker)
        
        # This call was previously crashing with TypeError: fetch() got an unexpected keyword argument 'start_at'
        service.fetch(ticker, start_at=start_at, end_at=end_at)
        
        # Verify news fetch received the args
        mock_news.fetch.assert_called_once()
        _, news_kwargs = mock_news.fetch.call_args
        self.assertEqual(news_kwargs["start_at"], start_at)
        self.assertEqual(news_kwargs["end_at"], end_at)
        
        # Verify social fetch received the args
        mock_social.fetch.assert_called_once()
        _, social_kwargs = mock_social.fetch.call_args
        self.assertEqual(social_kwargs["start_at"], start_at)
        self.assertEqual(social_kwargs["end_at"], end_at)

    def test_fetch_works_without_time_window(self) -> None:
        mock_news = MagicMock()
        service = SignalIngestionService(news_service=mock_news)
        
        mock_news.fetch.return_value = NewsBundle(ticker="AAPL")
        
        # Normal live-mode call
        service.fetch("AAPL")
        
        mock_news.fetch.assert_called_once()
        _, news_kwargs = mock_news.fetch.call_args
        self.assertIsNone(news_kwargs.get("start_at"))
        self.assertIsNone(news_kwargs.get("end_at"))

if __name__ == "__main__":
    unittest.main()
