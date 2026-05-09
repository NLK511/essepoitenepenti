from __future__ import annotations

from dataclasses import dataclass

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import Watchlist
from trade_proposer_app.services.shortlist_selection import ShortlistSelectionConfig, ShortlistSelectionService


@dataclass
class CheapSignal:
    directional_score: float = 0.0
    breakout_score: float = 0.0


@dataclass
class Candidate:
    ticker: str
    direction: str
    confidence_percent: float
    attention_score: float
    error_message: str | None = None
    cheap_scan_signal: CheapSignal | None = None


def _watchlist(*, allow_shorts: bool = True) -> Watchlist:
    return Watchlist(
        id=1,
        name="Test",
        tickers=["AAPL", "MSFT"],
        default_horizon=StrategyHorizon.ONE_WEEK,
        allow_shorts=allow_shorts,
    )


def test_shortlist_selection_keeps_eligible_candidate_and_explains_rejections() -> None:
    service = ShortlistSelectionService(ShortlistSelectionConfig(confidence_threshold=60.0, signal_gating_tuning_config={}))

    result = service.evaluate(
        _watchlist(allow_shorts=False),
        [
            Candidate("AAPL", "long", 65.0, 60.0, cheap_scan_signal=CheapSignal(0.4, 80.0)),
            Candidate("TSLA", "short", 80.0, 90.0, cheap_scan_signal=CheapSignal(-0.5, 90.0)),
        ],
    )

    assert result["shortlist"] == ["AAPL"]
    rejected = next(item for item in result["decisions"] if item["ticker"] == "TSLA")
    assert "shorts_disabled" in rejected["reasons"]
    assert result["rejection_counts"]["shorts_disabled"] == 1


def test_shortlist_selection_can_use_catalyst_lane_for_relaxed_confidence() -> None:
    service = ShortlistSelectionService(ShortlistSelectionConfig(confidence_threshold=70.0, signal_gating_tuning_config={}))
    result = service.evaluate(
        _watchlist(),
        [Candidate("AAPL", "long", 50.0, 80.0, cheap_scan_signal=CheapSignal(0.8, 95.0))],
    )

    assert result["shortlist"] == ["AAPL"]
    decision = result["decisions"][0]
    assert decision["selection_lane"] == "catalyst"
