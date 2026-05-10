from __future__ import annotations

from dataclasses import dataclass

from trade_proposer_app.domain.models import RunOutput
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignal


@dataclass
class CheapScanCandidate:
    ticker: str
    direction: str
    confidence_percent: float
    attention_score: float
    warnings: list[str]
    indicator_summary: str
    cheap_scan_signal: CheapScanSignal | None = None
    raw_output: RunOutput | None = None
    error_message: str | None = None
