from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import json
import os
import shlex
import subprocess
from typing import Sequence

from trade_proposer_app.domain.models import ProviderCredential, TechnicalSnapshot
from trade_proposer_app.repositories.settings import DEFAULT_SUMMARY_PROMPT
from trade_proposer_app.services.news import NEWS_SUMMARY_ARTICLE_LIMIT


DEFAULT_SUMMARY_BACKEND = "news_digest"
"""Default backend used when no explicit summary engine is configured."""


@dataclass
class SummaryRequest:
    ticker: str
    news_items: list[dict[str, object]]
    technical_snapshot: TechnicalSnapshot


@dataclass
class SummaryResult:
    summary: str
    method: str
    backend: str
    model: str | None
    llm_error: str | None
    metadata: dict[str, object]
    duration_seconds: float | None


class SummaryService:
    def __init__(
        self,
        *,
        summary_settings: dict[str, str] | None = None,
        provider_credentials: dict[str, ProviderCredential] | None = None,
    ) -> None:
        self._settings = summary_settings or {}
        self._credentials = provider_credentials or {}
        self.backend = (self._settings.get("summary_backend") or DEFAULT_SUMMARY_BACKEND).strip().lower()
        self.model = (self._settings.get("summary_model") or "").strip() or None
        self.timeout = self._parse_float(self._settings.get("summary_timeout_seconds"), 60.0)
        self.max_tokens = self._parse_int(self._settings.get("summary_max_tokens"), 220)
        self.prompt = self._settings.get("summary_prompt") or DEFAULT_SUMMARY_PROMPT
        self.pi_command = self._settings.get("summary_pi_command") or "pi"
        self.pi_agent_dir = self._settings.get("summary_pi_agent_dir") or ""
        self.pi_cli_args = self._settings.get("summary_pi_cli_args") or ""

    def summarize(self, request: SummaryRequest) -> SummaryResult:
        if not request.news_items:
            return SummaryResult(
                summary="",
                method="price_only",
                backend=self.backend,
                model=self.model,
                llm_error=None,
                metadata={"reason": "no news items"},
                duration_seconds=None,
            )
        prompt = self._build_prompt(request)
        fallback_summary = self._headline_digest(request.news_items)
        return self.summarize_prompt(
            prompt,
            fallback_summary=fallback_summary,
            fallback_metadata={"news_item_count": len(request.news_items)},
        )

    def summarize_prompt(
        self,
        prompt: str,
        *,
        fallback_summary: str,
        fallback_metadata: dict[str, object] | None = None,
    ) -> SummaryResult:
        metadata = dict(fallback_metadata or {})
        if self.backend == "openai_api":
            return self._summarize_with_openai_prompt(prompt, fallback_summary=fallback_summary, fallback_metadata=metadata)
        if self.backend == "pi_agent":
            return self._summarize_with_pi_prompt(prompt, fallback_summary=fallback_summary, fallback_metadata=metadata)
        return self._fallback_result(fallback_summary, metadata=metadata)

    def _summarize_with_openai(self, request: SummaryRequest) -> SummaryResult:
        return self._summarize_with_openai_prompt(
            self._build_prompt(request),
            fallback_summary=self._headline_digest(request.news_items),
            fallback_metadata={"news_item_count": len(request.news_items)},
        )

    def _summarize_with_openai_prompt(
        self,
        prompt: str,
        *,
        fallback_summary: str,
        fallback_metadata: dict[str, object],
    ) -> SummaryResult:
        try:
            import openai
        except ImportError:  # pragma: no cover - optional dependency
            return self._fallback_result(
                fallback_summary,
                llm_error="openai package is not installed",
                metadata=fallback_metadata,
            )
        api_key = self._credentials.get("openai")
        if not api_key or not api_key.api_key:
            return self._fallback_result(
                fallback_summary,
                llm_error="openai api key is not configured",
                metadata=fallback_metadata,
            )
        openai.api_key = api_key.api_key
        start = perf_counter()
        try:
            response = openai.ChatCompletion.create(
                model=self.model or "gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )
        except Exception as exc:  # pragma: no cover - best effort
            duration = round(perf_counter() - start, 4)
            return self._fallback_result(
                fallback_summary,
                llm_error=str(exc),
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        duration = round(perf_counter() - start, 4)
        choices = response.choices if hasattr(response, "choices") else []
        if not choices:
            return self._fallback_result(
                fallback_summary,
                llm_error="openai response missing choices",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        text = (
            choices[0].message.content
            if hasattr(choices[0], "message") and hasattr(choices[0].message, "content")
            else getattr(choices[0], "text", "")
        ).strip()
        if not text:
            return self._fallback_result(
                fallback_summary,
                llm_error="openai returned an empty response",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        return SummaryResult(
            summary=text,
            method="llm_summary",
            backend=self.backend,
            model=self.model,
            llm_error=None,
            metadata=dict(fallback_metadata),
            duration_seconds=duration,
        )

    def _summarize_with_pi_agent(self, request: SummaryRequest) -> SummaryResult:
        return self._summarize_with_pi_prompt(
            self._build_prompt(request),
            fallback_summary=self._headline_digest(request.news_items),
            fallback_metadata={"news_item_count": len(request.news_items)},
        )

    def _summarize_with_pi_prompt(
        self,
        prompt: str,
        *,
        fallback_summary: str,
        fallback_metadata: dict[str, object],
    ) -> SummaryResult:
        cmd = [self.pi_command]
        if self.pi_cli_args:
            try:
                cmd.extend(shlex.split(self.pi_cli_args))
            except ValueError as exc:  # pragma: no cover - best effort
                return self._fallback_result(
                    fallback_summary,
                    llm_error=f"invalid pi CLI args: {exc}",
                    metadata=fallback_metadata,
                )
        cmd.extend(["-p", prompt, "--mode", "json", "--no-session"])
        env = os.environ.copy()
        if self.pi_agent_dir:
            env["PI_CODING_AGENT_DIR"] = self.pi_agent_dir
        start = perf_counter()
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(self.timeout, 1.0),
                env=env,
                cwd=self.pi_agent_dir or None,
            )
        except subprocess.TimeoutExpired:
            duration = round(perf_counter() - start, 4)
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI timed out after {self.timeout}s",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        except FileNotFoundError as exc:
            duration = round(perf_counter() - start, 4)
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI command not found: {exc}",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        except OSError as exc:  # pragma: no cover - best effort
            duration = round(perf_counter() - start, 4)
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI failed to start: {exc}",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        duration = round(perf_counter() - start, 4)
        if completed.returncode != 0:
            error_message = completed.stderr.strip() or f"return code {completed.returncode}"
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI failed: {error_message}",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        try:
            summary_text, metadata = self._parse_pi_output(completed.stdout)
        except json.JSONDecodeError as exc:
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent output parse failed: {exc}",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        if not summary_text:
            return self._fallback_result(
                fallback_summary,
                llm_error="pi_agent response did not include text",
                metadata=fallback_metadata,
                duration_seconds=duration,
            )
        return SummaryResult(
            summary=summary_text,
            method="llm_summary",
            backend=self.backend,
            model=metadata.get("model"),
            llm_error=None,
            metadata={
                **fallback_metadata,
                **metadata,
            },
            duration_seconds=duration,
        )

    def _parse_pi_output(self, output: str) -> tuple[str, dict[str, object]]:
        last_message: dict[str, object] | None = None
        for line in output.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("type") != "message_end":
                continue
            message = payload.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            text = self._extract_message_text(message.get("content"))
            if not text:
                continue
            last_message = {
                "text": text,
                "model": message.get("model"),
                "provider": message.get("provider"),
            }
        if last_message is None:
            return "", {}
        metadata: dict[str, object] = {}
        if last_message.get("model"):
            metadata["model"] = last_message["model"]
        if last_message.get("provider"):
            metadata["pi_provider"] = last_message["provider"]
        return last_message["text"], metadata

    @staticmethod
    def _extract_message_text(content: object | None) -> str:
        if isinstance(content, str):
            return content.strip()
        parts: list[str] = []
        if isinstance(content, Sequence):
            for entry in content:
                if isinstance(entry, dict):
                    text = entry.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(entry, str):
                    parts.append(entry)
        return "\n".join(parts).strip()

    def _news_digest_result(
        self,
        request: SummaryRequest,
        *,
        llm_error: str | None = None,
        duration_seconds: float | None = None,
    ) -> SummaryResult:
        return self._fallback_result(
            self._headline_digest(request.news_items),
            llm_error=llm_error,
            metadata={"news_item_count": len(request.news_items)},
            duration_seconds=duration_seconds,
        )

    def _fallback_result(
        self,
        fallback_summary: str,
        *,
        llm_error: str | None = None,
        metadata: dict[str, object] | None = None,
        duration_seconds: float | None = None,
    ) -> SummaryResult:
        payload = dict(metadata or {})
        payload["reason"] = llm_error or "fallback"
        return SummaryResult(
            summary=fallback_summary,
            method="news_digest",
            backend=self.backend,
            model=self.model,
            llm_error=llm_error,
            metadata=payload,
            duration_seconds=duration_seconds,
        )

    @staticmethod
    def _headline_digest(news_items: list[dict[str, object]]) -> str:
        return " | ".join(
            item.get("title", "")
            for item in news_items[:NEWS_SUMMARY_ARTICLE_LIMIT]
            if item.get("title")
        )

    def _build_prompt(self, request: SummaryRequest) -> str:
        news_lines = [
            f"{idx + 1}. {item.get('title', '').strip()}"
            + (f" - {item.get('summary', '').strip()}" if item.get("summary") else "")
            for idx, item in enumerate(request.news_items[:NEWS_SUMMARY_ARTICLE_LIMIT])
            if item.get("title")
        ]
        news_block = "\n".join(news_lines)
        snapshot = request.technical_snapshot
        snapshot_lines = []
        snapshot_lines.append(f"Price: {snapshot.price:.2f}")
        for label in ("rsi", "atr", "sma20", "sma50", "sma200"):
            value = getattr(snapshot, label, None)
            if value is not None:
                snapshot_lines.append(f"{label.upper()}: {value:.2f}")
        snapshot_block = "\n".join(snapshot_lines)
        prompt_parts = [
            self.prompt.strip(),
            f"Ticker: {request.ticker}",
            "News:",
            news_block,
            "Technical snapshot:",
            snapshot_block,
            "Summary:",
        ]
        return "\n".join(part for part in prompt_parts if part)

    @staticmethod
    def _parse_float(value: str | None, fallback: float) -> float:
        if not value:
            return fallback
        try:
            return float(value)
        except ValueError:
            return fallback

    @staticmethod
    def _parse_int(value: str | None, fallback: int) -> int:
        if not value:
            return fallback
        try:
            parsed = int(value)
        except ValueError:
            parsed = fallback
        return max(1, parsed)
