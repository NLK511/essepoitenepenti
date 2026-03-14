import subprocess
import unittest
from unittest.mock import patch

from trade_proposer_app.domain.models import ProviderCredential
from trade_proposer_app.services.proposals import ProposalExecutionError, ProposalService


class ProposalServiceTests(unittest.TestCase):
    def test_extract_analysis_json_handles_pretty_printed_payload(self) -> None:
        raw_output = """
header
ANALYSIS_JSON::
{
  "direction": "LONG",
  "problems": ["summary: timeout"]
}
Disclaimer: example
"""
        analysis_json = ProposalService._extract_analysis_json(raw_output)
        self.assertIsNotNone(analysis_json)
        assert analysis_json is not None
        self.assertIn('"direction": "LONG"', analysis_json)
        self.assertIn('"summary: timeout"', analysis_json)

    def test_extract_warnings_collects_problems_and_errors(self) -> None:
        analysis_json = """
{
  "problems": ["summary: timeout"],
  "news_feed_errors": ["finnhub unavailable"],
  "summary_error": "summary model unavailable"
}
"""
        warnings = ProposalService._extract_warnings(analysis_json)
        self.assertIn("summary: timeout", warnings)
        self.assertIn("finnhub unavailable", warnings)
        self.assertIn("summary model unavailable", warnings)

    def test_extract_diagnostics_normalizes_structured_fields(self) -> None:
        analysis_json = """
{
  "problems": ["sentiment degraded"],
  "news_feed_errors": ["benzinga timeout"],
  "summary_error": "summary model unavailable",
  "llm_error": "provider rate limit"
}
"""
        diagnostics = ProposalService._extract_diagnostics(analysis_json, raw_output="raw")
        self.assertEqual(diagnostics.problems, ["sentiment degraded"])
        self.assertEqual(diagnostics.news_feed_errors, ["benzinga timeout"])
        self.assertEqual(diagnostics.provider_errors, ["benzinga timeout"])
        self.assertEqual(diagnostics.summary_error, "summary model unavailable")
        self.assertEqual(diagnostics.llm_error, "provider rate limit")
        self.assertEqual(diagnostics.warning_count, 4)
        self.assertEqual(diagnostics.raw_output, "raw")

    def test_build_indicator_summary_uses_main_trade_indicators(self) -> None:
        analysis_json = """
{
  "sentiment_label": "Bullish",
  "summary": "Strong product launch demand.",
  "feature_vector": {
    "rsi": 58.4,
    "atr_pct": 2.12,
    "price_above_sma200": 1
  }
}
"""
        summary = ProposalService._build_indicator_summary(analysis_json)
        self.assertIn("Sentiment Bullish", summary)
        self.assertIn("RSI 58.4", summary)
        self.assertIn("ATR 2.12%", summary)
        self.assertIn("Above SMA200", summary)

    def test_generate_passes_settings_credentials_and_news_provider_keys_to_prototype_env(self) -> None:
        result = subprocess.CompletedProcess(
            args=["python3", "propose_trade.py", "AAPL"],
            returncode=0,
            stdout='''=> DIRECTION : LONG\n=> CONFIDENCE: 81\nCurrent Price : 101\nStop Loss : 97\nTake Profit : 111\nANALYSIS_JSON::{"problems": []}''',
            stderr="",
        )
        service = ProposalService(
            summary_settings={
                "summary_backend": "openai_api",
                "summary_model": "gpt-4o-mini",
                "summary_timeout_seconds": "77",
                "summary_max_tokens": "333",
                "summary_pi_command": "pi",
                "summary_pi_agent_dir": "/tmp/pi-agent",
                "summary_prompt": "short summary prompt",
            },
            provider_credentials={
                "openai": ProviderCredential(provider="openai", api_key="sk-test", api_secret=""),
                "newsapi": ProviderCredential(provider="newsapi", api_key="news-key", api_secret=""),
                "alpha_vantage": ProviderCredential(provider="alpha_vantage", api_key="alpha-key", api_secret=""),
                "finnhub": ProviderCredential(provider="finnhub", api_key="finn-key", api_secret=""),
                "alpaca": ProviderCredential(provider="alpaca", api_key="alpaca-id", api_secret="alpaca-secret"),
            },
        )

        with patch("pathlib.Path.exists", return_value=True), patch(
            "trade_proposer_app.services.proposals.subprocess.run", return_value=result
        ) as run_mock:
            output = service.generate("AAPL")

        self.assertEqual(output.recommendation.ticker, "AAPL")
        self.assertEqual(output.recommendation.state.value, "PENDING")
        call_env = run_mock.call_args.kwargs["env"]
        self.assertEqual(call_env["NEWS_SUMMARIZER_BACKEND"], "openai_api")
        self.assertEqual(call_env["NEWS_SUMMARIZER_MODEL"], "gpt-4o-mini")
        self.assertEqual(call_env["NEWS_SUMMARIZER_TIMEOUT_SECONDS"], "77")
        self.assertEqual(call_env["NEWS_SUMMARIZER_MAX_TOKENS"], "333")
        self.assertEqual(call_env["NEWS_SUMMARIZER_PROMPT"], "short summary prompt")
        self.assertEqual(call_env["OPENAI_API_KEY"], "sk-test")
        self.assertEqual(call_env["NEWSAPI_KEY"], "news-key")
        self.assertEqual(call_env["ALPHA_VANTAGE_API_KEY"], "alpha-key")
        self.assertEqual(call_env["FINNHUB_API_KEY"], "finn-key")
        self.assertEqual(call_env["APCA_API_KEY_ID"], "alpaca-id")
        self.assertEqual(call_env["APCA_API_SECRET_KEY"], "alpaca-secret")
        self.assertEqual(call_env["PI_CODING_AGENT_DIR"], "/tmp/pi-agent")

    def test_generate_raises_when_prototype_dependency_is_missing(self) -> None:
        result = subprocess.CompletedProcess(
            args=["python3", "propose_trade.py", "AAPL"],
            returncode=1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'yfinance'",
        )

        with patch("pathlib.Path.exists", return_value=True), patch(
            "trade_proposer_app.services.proposals.subprocess.run", return_value=result
        ):
            with self.assertRaises(ProposalExecutionError) as context:
                ProposalService().generate("AAPL")

        self.assertIn("prototype dependency missing", str(context.exception))
        self.assertIn("yfinance", str(context.exception))

    def test_generate_raises_with_explicit_message_when_ticker_history_is_missing(self) -> None:
        result = subprocess.CompletedProcess(
            args=["python3", "propose_trade.py", "NOPE"],
            returncode=1,
            stdout="Error: Could not retrieve historical data for 'NOPE'.\n",
            stderr="",
        )

        with patch("pathlib.Path.exists", return_value=True), patch(
            "trade_proposer_app.services.proposals.subprocess.run", return_value=result
        ):
            with self.assertRaises(ProposalExecutionError) as context:
                ProposalService().generate("NOPE")

        self.assertIn("ticker not found or historical data unavailable", str(context.exception))
        self.assertIn("NOPE", str(context.exception))

    def test_generate_raises_when_required_output_fields_are_missing(self) -> None:
        result = subprocess.CompletedProcess(
            args=["python3", "propose_trade.py", "AAPL"],
            returncode=0,
            stdout='ANALYSIS_JSON::{"problems": []}',
            stderr="",
        )

        with patch("pathlib.Path.exists", return_value=True), patch(
            "trade_proposer_app.services.proposals.subprocess.run", return_value=result
        ):
            with self.assertRaises(ProposalExecutionError) as context:
                ProposalService().generate("AAPL")

        self.assertIn("missing direction", str(context.exception))


if __name__ == "__main__":
    unittest.main()
