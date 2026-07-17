from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
    PhantomSelectivitySeparabilityGates,
    build_phantom_selectivity_separability_report,
)


def _obs(
    *,
    day: date,
    outcome: str,
    setup_family: str = "breakout",
    ticker: str = "EOG",
    context_bias: str = "tailwind",
    confidence_percent: float = 65.0,
    volatility_score: float = 50.0,
    reward_pct: float = 8.0,
    risk_pct: float = 4.0,
) -> PhantomSelectivityObservation:
    return PhantomSelectivityObservation(
        evidence_date=day,
        outcome=outcome,
        ticker=ticker,
        setup_family=setup_family,
        context_bias=context_bias,
        action="watchlist",
        intended_action="long",
        effective_action="long",
        confidence_percent=confidence_percent,
        volatility_score=volatility_score,
        reward_pct=reward_pct,
        risk_pct=risk_pct,
    )


def test_phantom_separability_recommends_candidate_replay_for_stable_group() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        in_selection = index >= 15
        for _ in range(8):
            rows.append(_obs(day=day, outcome="phantom_win", setup_family="breakout"))
        for _ in range(2):
            rows.append(_obs(day=day, outcome="phantom_loss", setup_family="breakout"))
        for _ in range(7 if in_selection else 6):
            rows.append(_obs(day=day, outcome="phantom_loss", setup_family="mean_reversion"))
        for _ in range(3 if in_selection else 4):
            rows.append(_obs(day=day, outcome="phantom_win", setup_family="mean_reversion"))

    report = build_phantom_selectivity_separability_report(
        rows,
        gates=PhantomSelectivitySeparabilityGates(
            min_total_rows=100,
            min_selection_dates=5,
            min_discovery_group_rows=50,
            min_selection_group_rows=20,
            min_selection_group_dates=5,
            min_selection_win_rate_lift_pct=5.0,
        ),
        generated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "candidate_replay_recommended"
    assert report["candidate_specific_replay_recommended"] is True
    assert report["should_continue_threshold_search"] is False
    assert report["candidate_groups"][0]["feature"] == "setup_family"
    assert report["candidate_groups"][0]["value"] == "breakout"


def test_phantom_separability_stops_threshold_search_when_groups_do_not_hold_out() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        for _ in range(5):
            rows.append(_obs(day=day, outcome="phantom_win", setup_family="breakout"))
            rows.append(_obs(day=day, outcome="phantom_loss", setup_family="breakout"))
            rows.append(_obs(day=day, outcome="phantom_win", setup_family="mean_reversion"))
            rows.append(_obs(day=day, outcome="phantom_loss", setup_family="mean_reversion"))

    report = build_phantom_selectivity_separability_report(
        rows,
        gates=PhantomSelectivitySeparabilityGates(
            min_total_rows=100,
            min_selection_dates=5,
            min_discovery_group_rows=50,
            min_selection_group_rows=20,
            min_selection_group_dates=5,
            min_selection_win_rate_lift_pct=5.0,
        ),
    )

    assert report["verdict"] == "stop_threshold_search"
    assert report["candidate_specific_replay_recommended"] is False
    assert "no_selection_group_passed_gates" in report["blockers"]


def test_phantom_separability_reports_thin_evidence_before_making_a_stop_call() -> None:
    report = build_phantom_selectivity_separability_report(
        [_obs(day=date(2026, 1, 1), outcome="phantom_win")],
        gates=PhantomSelectivitySeparabilityGates(min_total_rows=10, min_selection_dates=3),
    )

    assert report["verdict"] == "thin_evidence"
    assert "phantom_sample_below_minimum" in report["blockers"]

