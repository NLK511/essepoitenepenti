from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import json
import os
import shlex
import subprocess
import threading
import time
from typing import Sequence

from trade_proposer_app.domain.models import ProviderCredential, TechnicalSnapshot
from trade_proposer_app.repositories.settings import DEFAULT_SUMMARY_PROMPT
from trade_proposer_app.services.news import NEWS_SUMMARY_ARTICLE_LIMIT


DEFAULT_SUMMARY_BACKEND = "news_digest"
"""Default backend used when no explicit summary engine is configured."""


def summary_fallback_warning(scope_label: str, llm_error: str) -> str:
    return f"{scope_label} summary fell back to digest/static summary because {llm_error}"


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
        self.timeout = self._parse_float(self._settings.get("summary_timeout_seconds"), 600.0)
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
            fallback_metadata={
                "news_item_count": len(request.news_items),
                **self._prompt_diagnostics(prompt),
            },
        )

    def summarize_prompt(
        self,
        prompt: str,
        *,
        fallback_summary: str,
        fallback_metadata: dict[str, object] | None = None,
    ) -> SummaryResult:
        metadata = {
            **(fallback_metadata or {}),
            **self._prompt_diagnostics(prompt),
        }
        if self.backend == "openai_api":
            return self._summarize_with_openai_prompt(prompt, fallback_summary=fallback_summary, fallback_metadata=metadata)
        if self.backend == "pi_agent":
            return self._summarize_with_pi_prompt(prompt, fallback_summary=fallback_summary, fallback_metadata=metadata)
        return self._fallback_result(fallback_summary, metadata=metadata)

    def _summarize_with_openai(self, request: SummaryRequest) -> SummaryResult:
        prompt = self._build_prompt(request)
        return self._summarize_with_openai_prompt(
            prompt,
            fallback_summary=self._headline_digest(request.news_items),
            fallback_metadata={
                "news_item_count": len(request.news_items),
                **self._prompt_diagnostics(prompt),
            },
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
        prompt = self._build_prompt(request)
        return self._summarize_with_pi_prompt(
            prompt,
            fallback_summary=self._headline_digest(request.news_items),
            fallback_metadata={
                "news_item_count": len(request.news_items),
                **self._prompt_diagnostics(prompt),
            },
        )

    def _summarize_with_pi_prompt(
        self,
        prompt: str,
        *,
        fallback_summary: str,
        fallback_metadata: dict[str, object],
    ) -> SummaryResult:
        try:
            cmd = self._pi_command(prompt)
        except ValueError as exc:  # pragma: no cover - best effort
            return self._fallback_result(
                fallback_summary,
                llm_error=f"invalid pi CLI args: {exc}",
                metadata=fallback_metadata,
            )
        run_metadata = self._pi_run_metadata(prompt, fallback_metadata)
        try:
            completed_stdout, completed_stderr, duration, terminated_after_final_message, timed_out, returncode = self._run_pi_cli(cmd)
        except FileNotFoundError as exc:
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI command not found: {exc}",
                metadata=run_metadata,
                duration_seconds=round(0.0, 4),
            )
        except OSError as exc:  # pragma: no cover - best effort
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI failed to start: {exc}",
                metadata=run_metadata,
                duration_seconds=round(0.0, 4),
            )
        if timed_out:
            timeout_metadata = {
                **run_metadata,
                "pi_timeout_seconds": self.timeout,
                "pi_partial_stdout_chars": len(completed_stdout),
                "pi_partial_stderr_chars": len(completed_stderr),
                "pi_terminated_after_final_message": terminated_after_final_message,
            }
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI timed out after {self.timeout}s",
                metadata=timeout_metadata,
                duration_seconds=duration,
            )
        if returncode not in (0, None) and not terminated_after_final_message:
            error_message = completed_stderr.strip() or f"return code {returncode}"
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent CLI failed: {error_message}",
                metadata={
                    **run_metadata,
                    "pi_terminated_after_final_message": terminated_after_final_message,
                },
                duration_seconds=duration,
            )
        try:
            summary_text, metadata = self._parse_pi_output(completed_stdout)
        except json.JSONDecodeError as exc:
            return self._fallback_result(
                fallback_summary,
                llm_error=f"pi_agent output parse failed: {exc}",
                metadata={
                    **run_metadata,
                    "pi_terminated_after_final_message": terminated_after_final_message,
                },
                duration_seconds=duration,
            )
        if not summary_text:
            return self._fallback_result(
                fallback_summary,
                llm_error="pi_agent response did not include text",
                metadata={
                    **run_metadata,
                    "pi_terminated_after_final_message": terminated_after_final_message,
                },
                duration_seconds=duration,
            )
        return SummaryResult(
            summary=summary_text,
            method="llm_summary",
            backend=self.backend,
            model=metadata.get("model"),
            llm_error=None,
            metadata={
                **run_metadata,
                "pi_terminated_after_final_message": terminated_after_final_message,
                **metadata,
            },
            duration_seconds=duration,
        )

    def _pi_command(self, prompt: str) -> list[str]:
        cmd = [self.pi_command]
        if self.pi_cli_args:
            cmd.extend(shlex.split(self.pi_cli_args))
        cmd.extend([
            "-p",
            prompt,
            "--mode",
            "json",
            "--no-session",
            "--no-context-files",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
        ])
        return cmd

    def _pi_run_metadata(self, prompt: str, fallback_metadata: dict[str, object]) -> dict[str, object]:
        return {
            **fallback_metadata,
            **self._prompt_diagnostics(prompt),
            "pi_command": self.pi_command,
            "pi_cli_args": self.pi_cli_args,
            "pi_timeout_seconds": self.timeout,
            "pi_working_directory": self.pi_agent_dir or None,
        }

    def _run_pi_cli(self, cmd: list[str]) -> tuple[str, str, float, bool, bool, int | None]:
        env = os.environ.copy()
        if self.pi_agent_dir:
            env["PI_CODING_AGENT_DIR"] = self.pi_agent_dir
        start = perf_counter()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        final_message_seen = threading.Event()
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=self.pi_agent_dir or None,
        )
        stdout_thread = threading.Thread(
            target=self._read_pi_stream,
            args=(process.stdout, stdout_chunks),
            kwargs={"final_message_seen": final_message_seen},
            daemon=True,
        )
        stderr_thread = threading.Thread(target=self._read_pi_stream, args=(process.stderr, stderr_chunks), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        terminated_after_final_message, timed_out = self._wait_for_pi_process(process, start, final_message_seen)
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        return (
            "".join(stdout_chunks),
            "".join(stderr_chunks),
            round(perf_counter() - start, 4),
            terminated_after_final_message,
            timed_out,
            process.returncode,
        )

    def _read_pi_stream(self, stream, chunks: list[str], *, final_message_seen: threading.Event | None = None) -> None:
        try:
            for line in iter(stream.readline, ""):
                chunks.append(line)
                if final_message_seen is not None and self._is_final_pi_message_line(line):
                    final_message_seen.set()
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _wait_for_pi_process(self, process: subprocess.Popen[str], start: float, final_message_seen: threading.Event) -> tuple[bool, bool]:
        terminated_after_final_message = False
        timed_out = False
        while True:
            if process.poll() is not None:
                break
            if final_message_seen.is_set():
                terminated_after_final_message = True
                self._stop_pi_process(process, force=False)
                break
            if perf_counter() - start >= max(self.timeout, 1.0):
                timed_out = True
                self._stop_pi_process(process, force=True)
                break
            time.sleep(0.05)
        return terminated_after_final_message, timed_out

    def _stop_pi_process(self, process: subprocess.Popen[str], *, force: bool = False) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except Exception:
            return
        deadline = perf_counter() + (0.5 if force else 2.0)
        while perf_counter() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.05)
        try:
            process.kill()
        except Exception:
            return

    def _is_final_pi_message_line(self, line: str) -> bool:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return False
        if payload.get("type") != "message_end":
            return False
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return False
        return bool(self._extract_message_text(message.get("content")))

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
        payload["fallback_used"] = bool(llm_error)
        payload["fallback_mode"] = "digest" if llm_error else "configured_fallback"
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
    def _prompt_diagnostics(prompt: str) -> dict[str, object]:
        lines = prompt.splitlines()
        return {
            "prompt_char_count": len(prompt),
            "prompt_line_count": len(lines),
            "prompt_nonempty_line_count": sum(1 for line in lines if line.strip()),
        }

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
