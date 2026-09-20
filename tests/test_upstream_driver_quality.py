from __future__ import annotations

from datetime import date, timedelta

from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
)
from trade_proposer_app.services.upstream_driver_quality import (
    UpstreamDriverQualityGates,
    build_upstream_driver_quality_report,
)
from trade_proposer_app.services.upstream_signal_driver_audit import (
    UpstreamSignalDriverObservation,
)


def _obs(
    *,
    day: date,
    ticker: str,
    outcome: str,
    volatility_score: float = 35.0,
    setup_family: str = "breakout",
) -> UpstreamSignalDriverObservation:
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
            confidence_percent=47.0,
            volatility_score=volatility_score,
            reward_pct=8.0,
            risk_pct=4.0,
        ),
        signal_breakdown={
            "cheap_scan_volatility_score": volatility_score,
            "confidence_components": {"execution_clarity": 24.0},
            "transmission_summary": {"catalyst_intensity_percent": 65.0},
            "shortlist_rank": 7,
        },
    )


def test_driver_quality_marks_clean_driver_as_reusable_candidate() -> None:
    start = date(2026, 1, 1)
    rows: list[UpstreamSignalDriverObservation] = []
    tickers = ["PANW", "HUM", "AMAT", "ORCL", "LRCX"]
    for index in range(40):
        day = start + timedelta(days=index)
        for ticker in tickers:
            rows.append(_obs(day=day, ticker=ticker, outcome="phantom_win"))
        rows.append(_obs(day=day, ticker="BASE", outcome="phantom_loss", volatility_score=75.0))

    report = build_upstream_driver_quality_report(
        rows,
        [{"feature": "confidence_bucket", "value": "45-50"}],
        [{"feature": "volatility_bucket", "value": "30-40"}],
        gates=UpstreamDriverQualityGates(
            min_driver_rows=30,
            min_driver_dates=5,
            min_driver_tickers=5,
            min_selection_rows=20,
            min_selection_dates=5,
        ),
    )

    driver = report["drivers"][0]
    assert report["verdict"] == "reusable_driver_quality_candidate"
    assert driver["scorecard_status"] == "reusable_candidate"
    assert driver["lineage_quality"]["usable_lineage_share_percent"] == 100.0
    top_ticker_ablation = driver["ablations"]["without_top_ticker"]["metrics"]
    assert top_ticker_ablation["expected_value_per_observation"] > 0


def test_driver_quality_marks_ticker_carried_driver_as_diagnostic_only() -> None:
    start = date(2026, 1, 1)
    rows: list[UpstreamSignalDriverObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        for _ in range(5):
            rows.append(_obs(day=day, ticker="FTNT", outcome="phantom_win"))
        rows.append(_obs(day=day, ticker="HUM", outcome="phantom_loss"))
        rows.append(_obs(day=day, ticker="PANW", outcome="phantom_loss"))

    report = build_upstream_driver_quality_report(
        rows,
        [{"feature": "confidence_bucket", "value": "45-50"}],
        [{"feature": "volatility_bucket", "value": "30-40"}],
        gates=UpstreamDriverQualityGates(
            min_driver_rows=30,
            min_driver_dates=5,
            min_driver_tickers=2,
            min_selection_rows=5,
            min_selection_dates=3,
            max_single_ticker_share_percent=50.0,
        ),
    )

    driver = report["drivers"][0]
    assert report["verdict"] == "analysis_only_driver_leads"
    assert driver["scorecard_status"] == "diagnostic_only"
    assert "top_ticker_share_above_reusable_maximum" in driver["blockers"]
    assert "top_ticker_ablation_loses_positive_ev" in driver["blockers"]


def test_driver_quality_rejects_negative_ev_driver() -> None:
    rows = [
        _obs(
            day=date(2026, 1, 1) + timedelta(days=index),
            ticker=f"T{index}",
            outcome="phantom_loss",
        )
        for index in range(10)
    ]

    report = build_upstream_driver_quality_report(
        rows,
        [{"feature": "confidence_bucket", "value": "45-50"}],
        [{"feature": "volatility_bucket", "value": "30-40"}],
    )

    driver = report["drivers"][0]
    assert report["verdict"] == "no_reusable_driver_quality_lead"
    assert driver["scorecard_status"] == "reject"
    assert "driver_ev_per_observation_not_positive" in driver["blockers"]
