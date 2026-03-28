import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trade_proposer_app.domain.models import ProviderCredential, TechnicalSnapshot
from trade_proposer_app.services.summary import SummaryRequest, SummaryService


class SummaryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = TechnicalSnapshot(price=100.0, sma20=99.0, sma50=98.0, sma200=95.0, rsi=55.0, atr=2.0)
        self.news_items = [
            {"title": "Company beats estimates", "summary": "Revenue growth", "compound": 0.7},
        ]

    def test_openai_summary_success(self) -> None:
        credentials = {
            "openai": ProviderCredential(provider="openai", api_key="fake", api_secret=""),
        }
        stub_module = SimpleNamespace()

        class ChatCompletion:
            @staticmethod
            def create(*, model, messages, temperature, max_tokens, timeout):
                response = SimpleNamespace()
                choice = SimpleNamespace()
                choice.message = SimpleNamespace(content="Fresh LLM summary")
                response.choices = [choice]
                return response

        stub_module.ChatCompletion = ChatCompletion
        with patch.dict("sys.modules", {"openai": stub_module}):
            service = SummaryService(
                summary_settings={"summary_backend": "openai_api", "summary_prompt": "Conclude quickly."},
                provider_credentials=credentials,
            )
            result = service.summarize(
                SummaryRequest(ticker="AAPL", news_items=self.news_items, technical_snapshot=self.snapshot)
            )
        self.assertEqual(result.method, "llm_summary")
        self.assertEqual(result.summary, "Fresh LLM summary")
        self.assertEqual(result.backend, "openai_api")
        self.assertEqual(result.model, service.model)
        self.assertIsNone(result.llm_error)
        self.assertEqual(result.metadata["news_item_count"], 1)

    def test_openai_missing_key_fallbacks_to_digest(self) -> None:
        service = SummaryService(summary_settings={"summary_backend": "openai_api"})
        result = service.summarize(
            SummaryRequest(ticker="AAPL", news_items=self.news_items, technical_snapshot=self.snapshot)
        )
        self.assertEqual(result.method, "news_digest")
        self.assertIsNotNone(result.llm_error)
        self.assertIn("api key", result.llm_error)
        self.assertIn("Company beats estimates", result.summary)

    def test_digest_backend_uses_headlines(self) -> None:
        service = SummaryService(summary_settings={"summary_backend": "news_digest"})
        result = service.summarize(
            SummaryRequest(ticker="AAPL", news_items=self.news_items, technical_snapshot=self.snapshot)
        )
        self.assertEqual(result.method, "news_digest")
        self.assertIn("Company beats estimates", result.summary)
        self.assertEqual(result.backend, "news_digest")

    def test_summarize_prompt_uses_fallback_on_digest_backend(self) -> None:
        service = SummaryService(summary_settings={"summary_backend": "news_digest"})
        result = service.summarize_prompt(
            "Explain the macro setup.",
            fallback_summary="Fallback macro context summary",
            fallback_metadata={"summary_kind": "macro_context"},
        )
        self.assertEqual(result.method, "news_digest")
        self.assertEqual(result.summary, "Fallback macro context summary")
        self.assertEqual(result.metadata["summary_kind"], "macro_context")

    @patch("trade_proposer_app.services.summary.subprocess.run")
    def test_pi_agent_backend_calls_cli(self, mock_run: MagicMock) -> None:
        response = MagicMock()
        response.returncode = 0
        session_line = json.dumps({"type": "session", "version": 3})
        message_line = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Pi says hi"}],
                    "model": "openai/gpt-4o-mini",
                    "provider": "openai",
                },
            }
        )
        response.stdout = f"{session_line}\n{message_line}\n"
        response.stderr = ""
        mock_run.return_value = response
        service = SummaryService(
            summary_settings={
                "summary_backend": "pi_agent",
                "summary_pi_cli_args": "--provider openai --model gpt-4o-mini",
            }
        )
        result = service.summarize(
            SummaryRequest(ticker="AAPL", news_items=self.news_items, technical_snapshot=self.snapshot)
        )
        self.assertEqual(result.method, "llm_summary")
        self.assertEqual(result.summary, "Pi says hi")
        self.assertEqual(result.backend, "pi_agent")
        self.assertEqual(result.model, "openai/gpt-4o-mini")
        self.assertIsNone(result.llm_error)
        self.assertEqual(result.metadata.get("news_item_count"), 1)
        self.assertEqual(result.metadata.get("pi_provider"), "openai")
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("--mode", called_cmd)
        self.assertIn("pi", called_cmd[0])

    @patch("trade_proposer_app.services.summary.subprocess.run")
    def test_pi_agent_backend_fallbacks_to_digest_on_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pi", timeout=5)
        service = SummaryService(summary_settings={"summary_backend": "pi_agent"})
        result = service.summarize(
            SummaryRequest(ticker="AAPL", news_items=self.news_items, technical_snapshot=self.snapshot)
        )
        self.assertEqual(result.method, "news_digest")
        self.assertIsNotNone(result.llm_error)
