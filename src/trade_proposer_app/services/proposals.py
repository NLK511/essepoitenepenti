import json
import os
import re
import subprocess
from pathlib import Path

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import RecommendationState
from trade_proposer_app.domain.models import ProviderCredential, Recommendation, RunDiagnostics, RunOutput


class ProposalExecutionError(Exception):
    def __init__(self, message: str, raw_output: str | None = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class ProposalService:
    def __init__(
        self,
        summary_settings: dict[str, str] | None = None,
        provider_credentials: dict[str, ProviderCredential] | None = None,
    ) -> None:
        self.summary_settings = summary_settings or {}
        self.provider_credentials = provider_credentials or {}

    @staticmethod
    def get_prototype_script_path() -> Path:
        return (
            Path(settings.prototype_repo_path)
            / ".pi"
            / "skills"
            / "trade-proposer"
            / "scripts"
            / "propose_trade.py"
        )

    def generate(self, ticker: str) -> RunOutput:
        prototype_script = self.get_prototype_script_path()
        normalized = ticker.upper()

        if not prototype_script.exists():
            raise ProposalExecutionError(f"prototype script not found: {prototype_script}")

        command = [settings.prototype_python_executable, str(prototype_script), normalized]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                cwd=settings.prototype_repo_path,
                env=self._build_subprocess_env(),
            )
        except Exception as exc:
            raise ProposalExecutionError(f"prototype execution failed: {exc}") from exc

        raw_output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0:
            raise ProposalExecutionError(self._build_process_failure_message(result.returncode, raw_output), raw_output)

        analysis_json = self._extract_analysis_json(raw_output)
        if analysis_json is None:
            raise ProposalExecutionError("analysis payload missing", raw_output)

        diagnostics = self._extract_diagnostics(analysis_json, raw_output)
        return self._parse_recommendation(normalized, raw_output, diagnostics)

    def _build_subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        summary_backend = (self.summary_settings.get("summary_backend") or "pi_agent").strip() or "pi_agent"
        summary_model = (self.summary_settings.get("summary_model") or "").strip()
        summary_timeout = (self.summary_settings.get("summary_timeout_seconds") or "60").strip() or "60"
        summary_max_tokens = (self.summary_settings.get("summary_max_tokens") or "220").strip() or "220"
        summary_pi_command = (self.summary_settings.get("summary_pi_command") or "pi").strip() or "pi"
        summary_pi_agent_dir = (self.summary_settings.get("summary_pi_agent_dir") or "").strip()
        summary_prompt = (self.summary_settings.get("summary_prompt") or "").strip()

        env["NEWS_SUMMARIZER_BACKEND"] = summary_backend
        env["NEWS_SUMMARIZER_TIMEOUT_SECONDS"] = summary_timeout
        env["NEWS_SUMMARIZER_MAX_TOKENS"] = summary_max_tokens
        env["NEWS_SUMMARIZER_PI_COMMAND"] = summary_pi_command
        if summary_model:
            env["NEWS_SUMMARIZER_MODEL"] = summary_model
        if summary_pi_agent_dir:
            env["PI_CODING_AGENT_DIR"] = summary_pi_agent_dir
        if summary_prompt:
            env["NEWS_SUMMARIZER_PROMPT"] = summary_prompt

        openai_credential = self.provider_credentials.get("openai")
        if openai_credential and openai_credential.api_key:
            env["OPENAI_API_KEY"] = openai_credential.api_key

        anthropic_credential = self.provider_credentials.get("anthropic")
        if anthropic_credential and anthropic_credential.api_key:
            env["ANTHROPIC_API_KEY"] = anthropic_credential.api_key

        newsapi_credential = self.provider_credentials.get("newsapi")
        if newsapi_credential and newsapi_credential.api_key:
            env["NEWSAPI_KEY"] = newsapi_credential.api_key

        alpha_vantage_credential = self.provider_credentials.get("alpha_vantage")
        if alpha_vantage_credential and alpha_vantage_credential.api_key:
            env["ALPHA_VANTAGE_API_KEY"] = alpha_vantage_credential.api_key

        finnhub_credential = self.provider_credentials.get("finnhub")
        if finnhub_credential and finnhub_credential.api_key:
            env["FINNHUB_API_KEY"] = finnhub_credential.api_key

        alpaca_credential = self.provider_credentials.get("alpaca")
        if alpaca_credential:
            if alpaca_credential.api_key:
                env["APCA_API_KEY_ID"] = alpaca_credential.api_key
            if alpaca_credential.api_secret:
                env["APCA_API_SECRET_KEY"] = alpaca_credential.api_secret

        return env

    def _parse_recommendation(
        self,
        ticker: str,
        raw_output: str,
        diagnostics: RunDiagnostics,
    ) -> RunOutput:
        direction = self._require_match(r"=> DIRECTION :\s*(LONG|SHORT|NEUTRAL)", raw_output, "direction")
        confidence = self._parse_number(self._require_match(r"=> CONFIDENCE:\s*([\d.]+)", raw_output, "confidence"), "confidence")
        entry_price = self._parse_number(self._require_match(r"Current Price :\s*([\d.,]+)", raw_output, "entry price"), "entry price")
        stop_loss = self._parse_number(self._require_match(r"Stop Loss\s*:\s*([\d.,]+)", raw_output, "stop loss"), "stop loss")
        take_profit = self._parse_number(
            self._require_match(r"Take Profit\s*:\s*([\d.,]+)", raw_output, "take profit"),
            "take profit",
        )

        diagnostics.raw_output = raw_output

        recommendation = Recommendation(
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            indicator_summary=self._build_indicator_summary(diagnostics.analysis_json),
            state=RecommendationState.PENDING,
        )
        return RunOutput(recommendation=recommendation, diagnostics=diagnostics)

    @staticmethod
    def _parse_number(value: str, label: str) -> float:
        try:
            return float(value.replace(",", ""))
        except ValueError as exc:
            raise ProposalExecutionError(f"invalid {label}: {value}") from exc

    @staticmethod
    def _require_match(pattern: str, raw_output: str, label: str) -> str:
        match = re.search(pattern, raw_output)
        if match is None:
            raise ProposalExecutionError(f"missing {label} in prototype output", raw_output)
        return match.group(1)

    @staticmethod
    def _extract_analysis_json(raw_output: str) -> str | None:
        marker = "ANALYSIS_JSON::"
        if marker not in raw_output:
            return None
        tail = raw_output.split(marker, 1)[1].strip()
        disclaimer_marker = "\nDisclaimer:"
        if disclaimer_marker in tail:
            tail = tail.split(disclaimer_marker, 1)[0].strip()
        if not tail:
            return None
        try:
            parsed = json.loads(tail)
            return json.dumps(parsed, indent=2, sort_keys=True)
        except json.JSONDecodeError:
            return None

    @classmethod
    def _extract_diagnostics(cls, analysis_json: str, raw_output: str | None = None) -> RunDiagnostics:
        diagnostics = RunDiagnostics(raw_output=raw_output, analysis_json=analysis_json)
        try:
            payload = json.loads(analysis_json)
        except json.JSONDecodeError as exc:
            raise ProposalExecutionError("analysis payload invalid", raw_output) from exc

        diagnostics.problems = cls._extract_string_list(payload.get("problems"))
        diagnostics.news_feed_errors = cls._extract_string_list(payload.get("news_feed_errors"))
        diagnostics.summary_error = cls._extract_optional_string(payload.get("summary_error"))
        diagnostics.llm_error = cls._extract_optional_string(payload.get("llm_error"))

        warnings: list[str] = []
        for value in diagnostics.problems:
            if value not in warnings:
                warnings.append(value)
        for value in diagnostics.news_feed_errors:
            if value not in warnings:
                warnings.append(value)
                diagnostics.provider_errors.append(value)
        for value in (diagnostics.summary_error, diagnostics.llm_error):
            if value and value not in warnings:
                warnings.append(value)
        diagnostics.warnings = warnings
        return diagnostics

    @classmethod
    def _extract_warnings(cls, analysis_json: str) -> list[str]:
        return cls._extract_diagnostics(analysis_json).warnings

    @staticmethod
    def _extract_string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    @staticmethod
    def _extract_optional_string(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    @staticmethod
    def _build_indicator_summary(analysis_json: str | None) -> str:
        if not analysis_json:
            return ""
        try:
            payload = json.loads(analysis_json)
        except json.JSONDecodeError:
            return ""

        parts: list[str] = []
        sentiment_label = payload.get("sentiment_label")
        if isinstance(sentiment_label, str) and sentiment_label:
            parts.append(f"Sentiment {sentiment_label}")

        feature_vector = payload.get("feature_vector")
        if isinstance(feature_vector, dict):
            rsi = feature_vector.get("rsi")
            if isinstance(rsi, (int, float)):
                parts.append(f"RSI {float(rsi):.1f}")
            atr_pct = feature_vector.get("atr_pct")
            if isinstance(atr_pct, (int, float)):
                parts.append(f"ATR {float(atr_pct):.2f}%")
            price_above_sma200 = feature_vector.get("price_above_sma200")
            if isinstance(price_above_sma200, (int, float)):
                parts.append("Above SMA200" if float(price_above_sma200) >= 0.5 else "Below SMA200")

        summary = payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            parts.append(summary.strip())

        return " · ".join(parts[:4])

    @staticmethod
    def _build_process_failure_message(returncode: int, raw_output: str) -> str:
        module_error_match = re.search(r"ModuleNotFoundError:\s*(.+)", raw_output)
        if module_error_match is not None:
            return f"prototype dependency missing: {module_error_match.group(1)}"

        missing_ticker_match = re.search(r"Could not retrieve historical data for '([^']+)'", raw_output)
        if missing_ticker_match is not None:
            return f"ticker not found or historical data unavailable: {missing_ticker_match.group(1)}"

        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        summary = lines[-1] if lines else f"prototype exited with code {returncode}"
        return f"prototype exited with code {returncode}: {summary}"
