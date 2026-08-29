from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityCandidateReplayGates,
    PhantomSelectivityObservation,
    PhantomSelectivitySeparabilityGates,
    build_phantom_selectivity_candidate_replay_report,
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


def test_candidate_replay_reports_promotion_ready_for_reusable_group() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(50):
        day = start + timedelta(days=index)
        for ticker in ("PANW", "HUM", "AMAT", "ORCL", "LRCX"):
            rows.append(
                _obs(
                    day=day,
                    outcome="phantom_win",
                    ticker=ticker,
                    setup_family="breakout",
                )
            )
        rows.append(_obs(day=day, outcome="phantom_loss", ticker="PANW", setup_family="breakout"))
        for _ in range(3):
            rows.append(_obs(day=day, outcome="phantom_loss", ticker="LOWQ", setup_family="base"))
            rows.append(_obs(day=day, outcome="phantom_win", ticker="LOWQ", setup_family="base"))

    report = build_phantom_selectivity_candidate_replay_report(
        rows,
        [{"feature": "setup_family", "value": "breakout"}],
        min_selection_dates=20,
        gates=PhantomSelectivityCandidateReplayGates(
            min_selection_rows=50,
            min_selection_dates=20,
        ),
    )

    assert report["verdict"] == "promotion_candidate_ready"
    assert report["promotion_candidate_ready"] is True
    assert report["combined_union"]["promotion_ready"] is True
    assert report["candidate_group_counts"]["reusable_feature"] == 1


def test_candidate_replay_stays_research_only_when_selection_dates_are_too_thin() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        for _ in range(5):
            rows.append(_obs(day=day, outcome="phantom_win", ticker="PANW"))
        rows.append(_obs(day=day, outcome="phantom_loss", ticker="PANW"))

    report = build_phantom_selectivity_candidate_replay_report(
        rows,
        [{"feature": "ticker", "value": "panw"}],
        min_selection_dates=5,
        gates=PhantomSelectivityCandidateReplayGates(
            min_selection_rows=20,
            min_selection_dates=20,
        ),
    )

    assert report["verdict"] == "research_candidate_only"
    assert report["promotion_candidate_ready"] is False
    assert (
        "selection_dates_below_promotion_minimum"
        in report["combined_union"]["promotion_blockers"]
    )


def test_candidate_replay_reports_split_math_for_selection_date_gate() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(58):
        day = start + timedelta(days=index)
        rows.append(_obs(day=day, outcome="phantom_win", setup_family="breakout"))
        rows.append(_obs(day=day, outcome="phantom_loss", setup_family="base"))

    report = build_phantom_selectivity_candidate_replay_report(
        rows,
        [{"feature": "setup_family", "value": "breakout"}],
        min_selection_dates=10,
        gates=PhantomSelectivityCandidateReplayGates(
            min_selection_rows=1,
            min_selection_dates=20,
        ),
    )

    assert report["date_counts"]["selection"] == 15
    assert report["selection_split"] == {
        "additional_total_eligible_dates_needed": 22,
        "estimated_total_eligible_dates_for_promotion_gate": 80,
        "minimum_selection_dates": 10,
        "promotion_minimum_selection_dates": 20,
        "selection_date_fraction": 0.25,
        "selection_dates": 15,
        "total_eligible_dates": 58,
    }


def test_candidate_replay_blocks_ticker_specific_candidate_from_promotion() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(80):
        day = start + timedelta(days=index)
        for _ in range(5):
            rows.append(_obs(day=day, outcome="phantom_win", ticker="PANW"))
        rows.append(_obs(day=day, outcome="phantom_loss", ticker="PANW"))
        rows.append(_obs(day=day, outcome="phantom_win", ticker="BASE"))
        rows.append(_obs(day=day, outcome="phantom_loss", ticker="BASE"))

    report = build_phantom_selectivity_candidate_replay_report(
        rows,
        [{"feature": "ticker", "value": "panw"}],
        min_selection_dates=20,
        gates=PhantomSelectivityCandidateReplayGates(
            min_selection_rows=20,
            min_selection_dates=20,
        ),
    )

    group = report["candidate_groups"][0]
    assert group["candidate_kind"] == "ticker_specific"
    assert group["promotion_ready"] is False
    assert "ticker_specific_candidate_only" in group["promotion_blockers"]
    assert report["verdict"] == "research_candidate_only"


def test_candidate_replay_reports_union_excluding_ticker_groups() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(80):
        day = start + timedelta(days=index)
        rows.append(_obs(day=day, outcome="phantom_win", ticker="PANW", setup_family="breakout"))
        rows.append(_obs(day=day, outcome="phantom_win", ticker="HUM", setup_family="breakout"))
        rows.append(_obs(day=day, outcome="phantom_loss", ticker="BASE", setup_family="base"))

    report = build_phantom_selectivity_candidate_replay_report(
        rows,
        [
            {"feature": "ticker", "value": "panw"},
            {"feature": "setup_family", "value": "breakout"},
        ],
        min_selection_dates=20,
        gates=PhantomSelectivityCandidateReplayGates(
            min_selection_rows=1,
            min_selection_dates=20,
        ),
    )

    assert report["candidate_group_counts"] == {
        "reusable_feature": 1,
        "ticker_specific": 1,
    }
    assert "union_contains_ticker_specific_groups" in report["combined_union"]["warnings"]
    assert report["combined_union_excluding_ticker_groups"]["selection"]["count"] == 40


def test_phantom_separability_reports_baseline_shift_warning() -> None:
    start = date(2026, 1, 1)
    rows: list[PhantomSelectivityObservation] = []
    for index in range(20):
        day = start + timedelta(days=index)
        in_selection = index >= 15
        rows.append(_obs(day=day, outcome="phantom_win" if in_selection else "phantom_loss"))
        rows.append(_obs(day=day, outcome="phantom_win" if in_selection else "phantom_loss"))

    report = build_phantom_selectivity_separability_report(
        rows,
        gates=PhantomSelectivitySeparabilityGates(
            min_total_rows=10,
            min_selection_dates=5,
            min_discovery_group_rows=1,
            min_selection_group_rows=1,
            min_selection_group_dates=1,
        ),
    )

    assert "baseline_win_rate_shift_above_5pct" in report["baseline_shift"]["warnings"]
    assert "baseline_ev_sign_crossed_zero" in report["baseline_shift"]["warnings"]


def test_candidate_replay_union_keeps_distinct_duplicate_shaped_rows() -> None:
    day = date(2026, 1, 1)
    rows = [
        _obs(day=day, outcome="phantom_win", ticker="PANW"),
        _obs(day=day, outcome="phantom_win", ticker="PANW"),
        _obs(day=day, outcome="phantom_loss", ticker="PANW"),
    ]

    report = build_phantom_selectivity_candidate_replay_report(
        rows,
        [
            {"feature": "ticker", "value": "panw"},
            {"feature": "effective_action", "value": "long"},
        ],
        min_selection_dates=1,
        gates=PhantomSelectivityCandidateReplayGates(
            min_selection_rows=1,
            min_selection_dates=1,
        ),
    )

    assert report["combined_union"]["selection"]["count"] == 3
    assert report["candidate_groups"][0]["selection"]["count"] == 3
