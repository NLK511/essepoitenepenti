from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from trade_proposer_app.domain.models import AppPreflightReport, PreflightCheck

WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "weights.json"
REQUIRED_MODULES = ("pandas", "yfinance")


class AppPreflightService:
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
