import io
import json
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
        self.assertGreater(result.metadata["prompt_char_count"], 0)
        self.assertGreater(result.metadata["prompt_line_count"], 0)

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
        self.assertGreater(result.metadata["prompt_char_count"], 0)

    @patch("trade_proposer_app.services.summary.subprocess.Popen")
    def test_pi_agent_backend_calls_cli(self, mock_popen: MagicMock) -> None:
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

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.StringIO(f"{session_line}\n{message_line}\n")
                self.stderr = io.StringIO("")
                self.returncode = None
                self.terminated = False
                self.killed = False

            def poll(self) -> int | None:
                return 0 if self.terminated or self.killed else None

            def terminate(self) -> None:
                self.terminated = True
                self.returncode = 0

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

        mock_popen.return_value = FakeProcess()
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
        self.assertTrue(result.metadata.get("pi_terminated_after_final_message"))
        self.assertEqual(result.metadata.get("news_item_count"), 1)
        self.assertGreater(result.metadata.get("prompt_char_count", 0), 0)
        self.assertGreater(result.metadata.get("prompt_line_count", 0), 0)
        self.assertEqual(result.metadata.get("pi_provider"), "openai")
        mock_popen.assert_called_once()
        called_cmd = mock_popen.call_args.kwargs["args"] if "args" in mock_popen.call_args.kwargs else mock_popen.call_args[0][0]
        self.assertIn("--mode", called_cmd)
        self.assertIn("--no-context-files", called_cmd)
        self.assertIn("pi", called_cmd[0])

    @patch("trade_proposer_app.services.summary.time.sleep", lambda *_: None)
    @patch("trade_proposer_app.services.summary.perf_counter")
    @patch("trade_proposer_app.services.summary.subprocess.Popen")
    def test_pi_agent_backend_fallbacks_to_digest_on_timeout(self, mock_popen: MagicMock, mock_perf_counter: MagicMock) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.StringIO("")
                self.stderr = io.StringIO("")
                self.returncode = None
                self.terminated = False
                self.killed = False

            def poll(self) -> int | None:
                return 0 if self.terminated or self.killed else None

            def terminate(self) -> None:
                self.terminated = True
                self.returncode = -15

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

        fake_now = {"value": 0.0}

        def fake_perf_counter() -> float:
            fake_now["value"] += 10.0
            return fake_now["value"]

        mock_perf_counter.side_effect = fake_perf_counter
        mock_popen.return_value = FakeProcess()
        service = SummaryService(summary_settings={"summary_backend": "pi_agent", "summary_timeout_seconds": "5"})
        result = service.summarize(
            SummaryRequest(ticker="AAPL", news_items=self.news_items, technical_snapshot=self.snapshot)
        )
        self.assertEqual(result.method, "news_digest")
        self.assertIsNotNone(result.llm_error)
        self.assertTrue(result.metadata.get("fallback_used"))
        self.assertEqual(result.metadata.get("fallback_mode"), "digest")
        self.assertIn("prompt_char_count", result.metadata)
        self.assertIn("pi_timeout_seconds", result.metadata)
