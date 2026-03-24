import unittest
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
