from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import httpx

from trade_proposer_app.domain.models import AppPreflightReport, PreflightCheck
from trade_proposer_app.services.taxonomy import TAXONOMY_DIR, TAXONOMY_PATH, TICKERS_PATH

WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "weights.json"
REQUIRED_MODULES = ("pandas", "yfinance")


class AppPreflightService:
    def __init__(self, social_settings: dict[str, str] | None = None) -> None:
        self.social_settings = social_settings or {}

    def run(self) -> AppPreflightReport:
        checks: list[PreflightCheck] = []
        for module_name in REQUIRED_MODULES:
            spec = importlib.util.find_spec(module_name)
            checks.append(
                PreflightCheck(
                    name=f"module:{module_name}",
                    status="ok" if spec else "failed",
                    message=(
                        f"{module_name} importable"
                        if spec
                        else f"{module_name} not importable; install it to enable the internal pipeline"
                    ),
                )
            )
        weights_exists = WEIGHTS_PATH.exists()
        checks.append(
            PreflightCheck(
                name="weights_file",
                status="ok" if weights_exists else "failed",
                message=(
                    "weights.json available"
                    if weights_exists
                    else f"weights.json not found: {WEIGHTS_PATH}"
                ),
            )
        )
        taxonomy_exists = TICKERS_PATH.exists() or TAXONOMY_PATH.exists()
        taxonomy_location = TICKERS_PATH if TICKERS_PATH.exists() else TAXONOMY_PATH
        checks.append(
            PreflightCheck(
                name="ticker_taxonomy",
                status="ok" if taxonomy_exists else "warning",
                message=(
                    f"ticker taxonomy available for macro/industry context and refresh workflows ({taxonomy_location})"
                    if taxonomy_exists
                    else f"ticker taxonomy not found yet: expected {TICKERS_PATH} or {TAXONOMY_PATH}"
                ),
                details=[f"taxonomy directory: {TAXONOMY_DIR}"] if taxonomy_exists else [],
            )
        )
        checks.append(self._check_nitter())
        status = "ok"
        if any(check.status == "failed" for check in checks):
            status = "failed"
        elif any(check.status == "warning" for check in checks):
            status = "warning"
        return AppPreflightReport(
            status=status,
            checked_at=datetime.now(timezone.utc),
            engine="internal_price_pipeline",
            checks=checks,
        )

    def _check_nitter(self) -> PreflightCheck:
        enabled = (self.social_settings.get("social_nitter_enabled") or "false").strip().lower() == "true"
        sentiment_enabled = (self.social_settings.get("social_sentiment_enabled") or "false").strip().lower() == "true"
        if not sentiment_enabled or not enabled:
            return PreflightCheck(
                name="social:nitter",
                status="warning",
                message="Nitter social ingestion disabled in app settings",
            )
        base_url = (self.social_settings.get("social_nitter_base_url") or "http://127.0.0.1:8080").strip()
        timeout = self._parse_float(self.social_settings.get("social_nitter_timeout_seconds"), 6.0)
        try:
            response = httpx.get(base_url, timeout=timeout, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            return PreflightCheck(
                name="social:nitter",
                status="failed",
                message=f"Nitter unreachable at {base_url}",
                details=[str(exc)],
            )
        if response.status_code >= 400:
            return PreflightCheck(
                name="social:nitter",
                status="failed",
                message=f"Nitter unhealthy at {base_url}",
                details=[f"unexpected status {response.status_code}"],
            )
        return PreflightCheck(
            name="social:nitter",
            status="ok",
            message=f"Nitter reachable at {base_url}",
        )

    @staticmethod
    def _parse_float(value: str | None, default: float) -> float:
        try:
            return float((value or "").strip())
        except (TypeError, ValueError):
            return default
