from __future__ import annotations

from datetime import date, timedelta

from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
)
from trade_proposer_app.services.upstream_signal_driver_audit import (
    UpstreamSignalDriverAuditGates,
    UpstreamSignalDriverObservation,
    build_upstream_signal_driver_audit_report,
)


def _obs(
    *,
    day: date,
    ticker: str,
    outcome: str,
    tag: str | None = "clean_breakout",
    setup_family: str = "breakout",
    confidence_percent: float = 65.0,
) -> UpstreamSignalDriverObservation:
    signal: dict[str, object] = {
        "setup_family": setup_family,
        "context_bias": "tailwind",
        "decision_tier": "research_plan",
        "transmission_summary": {
            "transmission_tags": [tag] if tag else [],
            "expected_transmission_window": "1-3d",
        },
        "confidence_components": {"technical": 72.0},
    }
    return UpstreamSignalDriverObservation(
        base=PhantomSelectivityObservation(
            evidence_date=day,
            outcome=outcome,
            ticker=ticker,
            setup_family=setup_family,
            context_bias="tailwind",
            action="watchlist",
            intended_action="long",
            effective_action="long",
            confidence_percent=confidence_percent,
            volatility_score=50.0,
            reward_pct=8.0,
            risk_pct=4.0,
        ),
        signal_breakdown=signal,
    )


def test_upstream_signal_audit_finds_reusable_feature_lead() -> None:
    start = date(2026, 1, 1)
    rows: list[UpstreamSignalDriverObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        for _ in range(4):
            rows.append(_obs(day=day, ticker="PANW", outcome="phantom_win", tag="clean_breakout"))
        rows.append(_obs(day=day, ticker="PANW", outcome="phantom_loss", tag="crowded"))
        for _ in range(3):
            rows.append(_obs(day=day, ticker="BASE", outcome="phantom_loss", tag="crowded"))
            rows.append(_obs(day=day, ticker="BASE", outcome="phantom_win", tag="mixed"))

    report = build_upstream_signal_driver_audit_report(
        rows,
        [{"feature": "ticker", "value": "panw"}],
        gates=UpstreamSignalDriverAuditGates(
            min_candidate_rows=50,
            min_candidate_dates=10,
            min_feature_rows=20,
            min_feature_dates=5,
        ),
    )

    assert report["verdict"] == "upstream_feature_lead"
    assert report["blockers"] == []
    assert report["top_reusable_candidate_win_loss_drivers"][0]["feature"] == "transmission_tag"
    assert report["top_reusable_candidate_win_loss_drivers"][0]["value"] == "clean_breakout"


def test_upstream_signal_audit_reports_ticker_artifact_when_no_reusable_driver_passes() -> None:
    start = date(2026, 1, 1)
    rows: list[UpstreamSignalDriverObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        for _ in range(4):
            rows.append(_obs(day=day, ticker="HUM", outcome="phantom_win", tag="same"))
        rows.append(_obs(day=day, ticker="HUM", outcome="phantom_loss", tag="same"))
        for _ in range(3):
            rows.append(_obs(day=day, ticker="BASE", outcome="phantom_win", tag="same"))
            rows.append(_obs(day=day, ticker="BASE", outcome="phantom_loss", tag="same"))

    report = build_upstream_signal_driver_audit_report(
        rows,
        [{"feature": "ticker", "value": "hum"}],
        gates=UpstreamSignalDriverAuditGates(
            min_candidate_rows=50,
            min_candidate_dates=10,
            min_feature_rows=20,
            min_feature_dates=5,
        ),
    )

    assert report["verdict"] == "ticker_artifact_only"
    assert "no_reusable_signal_feature_passed_gates" in report["blockers"]


def test_upstream_signal_audit_reports_sparse_feature_coverage() -> None:
    start = date(2026, 1, 1)
    rows = [
        UpstreamSignalDriverObservation(
            base=PhantomSelectivityObservation(
                evidence_date=start + timedelta(days=index),
                outcome="phantom_win",
                ticker="ORCL",
                setup_family="unknown",
                context_bias=None,
                action="watchlist",
                intended_action=None,
                effective_action=None,
                confidence_percent=45.0,
                volatility_score=None,
                reward_pct=8.0,
                risk_pct=4.0,
            ),
            signal_breakdown={},
        )
        for index in range(12)
    ]

    report = build_upstream_signal_driver_audit_report(
        rows,
        [{"feature": "ticker", "value": "orcl"}],
        gates=UpstreamSignalDriverAuditGates(
            min_candidate_rows=10,
            min_candidate_dates=10,
            min_feature_rows=5,
            min_feature_dates=5,
            min_reusable_feature_coverage_percent=60.0,
        ),
    )

    assert report["verdict"] == "insufficient_feature_coverage"
    assert "reusable_signal_feature_coverage_below_minimum" in report["blockers"]
