from __future__ import annotations

from unittest.mock import Mock

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RecommendationPlan, TickerSignalSnapshot
from trade_proposer_app.services.watchlist_decision_samples import WatchlistDecisionSampleService


def test_plan_linked_decision_sample_uses_downstream_action_threshold() -> None:
    sink = Mock()
    orchestration = Mock()
    orchestration.decision_samples = sink
    orchestration._pluck.side_effect = lambda payload, *keys: None
    service = WatchlistDecisionSampleService(orchestration)
    plan = RecommendationPlan(
        id=12,
        ticker="AAPL",
        horizon=StrategyHorizon.ONE_WEEK,
        action="no_action",
        status="ok",
        confidence_percent=52.0,
        warnings=[],
        evidence_summary={"action_reason": "below_action_confidence_threshold"},
        signal_breakdown={
            "setup_family": "breakout",
            "calibration_review": {
                "effective_confidence_threshold": 67.0,
                "calibrated_confidence_percent": 52.0,
            },
            "decision_thresholds": {
                "upstream_effective_confidence_threshold_percent": 67.0,
                "effective_action_threshold_percent": 50.0,
            },
        },
        run_id=1,
        job_id=2,
        watchlist_id=3,
        ticker_signal_snapshot_id=4,
    )
    signal = TickerSignalSnapshot(ticker="AAPL", horizon=StrategyHorizon.ONE_WEEK, direction="long", diagnostics={})

    service.record_decision_sample(
        plan,
        candidate=object(),
        signal=signal,
        shortlisted=True,
        shortlist_rank=1,
        shortlist_decision={},
    )

    sample = sink.upsert_sample.call_args.args[0]
    assert sample.effective_threshold_percent == 50.0
    assert sample.confidence_gap_percent == 2.0
    assert sample.decision_context["threshold_semantics"] == "downstream_effective_action_threshold"
