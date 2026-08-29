from __future__ import annotations

from datetime import date, timedelta

from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
)
from trade_proposer_app.services.upstream_signal_driver_audit import (
    ProspectiveSignalDriverTagMonitorGates,
    ProspectiveSignalDriverTagObservation,
    UpstreamSignalDriverAuditGates,
    UpstreamSignalDriverDrilldownGates,
    UpstreamSignalDriverObservation,
    build_prospective_signal_driver_tag_monitor_report,
    build_upstream_signal_driver_audit_report,
    build_upstream_signal_driver_drilldown_report,
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


def _tagged_obs(
    *,
    day: date,
    ticker: str,
    outcome: str | None = None,
    tag_key: str = "volatility_30_40",
    reward_pct: float = 8.0,
    risk_pct: float = 4.0,
    label_source: str | None = None,
) -> ProspectiveSignalDriverTagObservation:
    return ProspectiveSignalDriverTagObservation(
        plan_id=None,
        evidence_date=day,
        ticker=ticker,
        action="no_action",
        setup_family="catalyst_follow_through",
        replay_outcome=outcome,
        replay_resolution_source="intraday" if outcome else None,
        label_source=label_source,
        reward_pct=reward_pct,
        risk_pct=risk_pct,
        signal_breakdown={
            "upstream_signal_quality_drivers": [
                {
                    "key": tag_key,
                    "feature": "volatility_bucket",
                    "value": "30-40",
                    "reason": "test tag",
                }
            ]
        },
    )


def test_prospective_signal_driver_tag_monitor_reports_empty_state() -> None:
    report = build_prospective_signal_driver_tag_monitor_report([])

    assert report["verdict"] == "no_prospective_tagged_evidence"
    assert "no_tagged_plans_found" in report["blockers"]
    assert report["record_counts"]["tagged_plans"] == 0


def test_prospective_signal_driver_tag_monitor_reports_accumulating_tags() -> None:
    rows = [
        _tagged_obs(
            day=date(2026, 1, 1) + timedelta(days=index),
            ticker="PANW",
            outcome="phantom_win",
        )
        for index in range(3)
    ]

    report = build_prospective_signal_driver_tag_monitor_report(
        rows,
        gates=ProspectiveSignalDriverTagMonitorGates(
            min_tagged_rows=10,
            min_tagged_dates=5,
            min_replay_labeled_rows=10,
            min_replay_labeled_dates=5,
            promotion_watch_date_floor=20,
        ),
    )

    assert report["verdict"] == "prospective_tags_accumulating"
    assert "no_tag_met_review_gates" in report["blockers"]
    tag = report["tags"][0]
    assert tag["tag_verdict"] == "accumulating"
    assert "tagged_rows_below_minimum" in tag["blockers"]


def test_prospective_signal_driver_tag_monitor_marks_review_ready_tag() -> None:
    start = date(2026, 1, 1)
    rows: list[ProspectiveSignalDriverTagObservation] = []
    tickers = ["PANW", "HUM", "AMAT", "ORCL", "LRCX"]
    for index in range(20):
        for ticker in tickers:
            rows.append(
                _tagged_obs(
                    day=start + timedelta(days=index),
                    ticker=ticker,
                    outcome="phantom_win" if ticker != "LRCX" else "phantom_loss",
                )
            )

    report = build_prospective_signal_driver_tag_monitor_report(
        rows,
        gates=ProspectiveSignalDriverTagMonitorGates(
            min_tagged_rows=30,
            min_tagged_dates=5,
            min_replay_labeled_rows=30,
            min_replay_labeled_dates=5,
            promotion_watch_date_floor=20,
        ),
    )

    assert report["verdict"] == "prospective_tags_ready_for_review"
    tag = report["tags"][0]
    assert tag["tag_verdict"] == "promotion_watchable"
    assert tag["maturity_verdict"] == "coverage_ready_for_review"
    assert tag["performance_verdict"] == "positive_phantom_evidence"
    assert tag["phantom_outcome_metrics"]["win_rate_percent"] == 80.0
    assert tag["phantom_outcome_metrics"]["expected_value_per_observation"] == 5.6


def test_tag_monitor_separates_maturity_from_negative_performance() -> None:
    start = date(2026, 1, 1)
    rows: list[ProspectiveSignalDriverTagObservation] = []
    for index in range(20):
        for ticker in ("PANW", "HUM"):
            rows.append(
                _tagged_obs(
                    day=start + timedelta(days=index),
                    ticker=ticker,
                    outcome="phantom_loss",
                )
            )

    report = build_prospective_signal_driver_tag_monitor_report(
        rows,
        gates=ProspectiveSignalDriverTagMonitorGates(
            min_tagged_rows=30,
            min_tagged_dates=5,
            min_replay_labeled_rows=30,
            min_replay_labeled_dates=5,
            promotion_watch_date_floor=20,
        ),
    )

    tag = report["tags"][0]
    assert tag["tag_verdict"] == "promotion_watchable"
    assert tag["maturity_verdict"] == "coverage_ready_for_review"
    assert tag["performance_verdict"] == "not_positive_phantom_evidence"
    assert "phantom_expected_value_not_positive" in tag["performance_warnings"]


def test_prospective_signal_driver_tag_monitor_reports_label_source_mix() -> None:
    rows = [
        _tagged_obs(
            day=date(2026, 1, 1),
            ticker="PANW",
            outcome="phantom_win",
            label_source="live_evaluation",
        ),
        _tagged_obs(
            day=date(2026, 1, 2),
            ticker="HUM",
            outcome="phantom_loss",
            label_source="historical_replay",
        ),
    ]

    report = build_prospective_signal_driver_tag_monitor_report(rows)

    assert report["metrics"]["label_source_counts"] == {
        "historical_replay": 1,
        "live_evaluation": 1,
    }
    assert report["tags"][0]["label_source_mix"] == {
        "historical_replay": 1,
        "live_evaluation": 1,
    }


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


def test_upstream_signal_drilldown_reports_reusable_driver_with_examples() -> None:
    start = date(2026, 1, 1)
    rows: list[UpstreamSignalDriverObservation] = []
    tickers = ["PANW", "HUM", "AMAT", "ORCL", "LRCX"]
    for index in range(10):
        day = start + timedelta(days=index)
        for ticker in tickers:
            rows.append(
                _obs(
                    day=day,
                    ticker=ticker,
                    outcome="phantom_win",
                    tag="clean_breakout",
                )
            )
        rows.append(_obs(day=day, ticker="PANW", outcome="phantom_loss", tag="clean_breakout"))
        rows.append(_obs(day=day, ticker="BASE", outcome="phantom_loss", tag="crowded"))

    report = build_upstream_signal_driver_drilldown_report(
        rows,
        [{"feature": "transmission_tag", "value": "clean_breakout"}],
        [{"feature": "transmission_tag", "value": "clean_breakout"}],
        gates=UpstreamSignalDriverDrilldownGates(
            min_driver_rows=30,
            min_driver_dates=5,
            min_driver_tickers=5,
        ),
        examples_per_outcome=2,
    )

    assert report["verdict"] == "reusable_driver_leads"
    driver = report["drivers"][0]
    assert driver["driver_verdict"] == "reusable_driver"
    assert driver["examples"]["phantom_win"]
    assert driver["examples"]["phantom_loss"]
    assert driver["examples"]["phantom_win"][0]["signal_excerpt"]["transmission_tags"] == [
        "clean_breakout"
    ]


def test_upstream_signal_drilldown_reports_ticker_concentration() -> None:
    start = date(2026, 1, 1)
    rows: list[UpstreamSignalDriverObservation] = []
    for index in range(10):
        day = start + timedelta(days=index)
        for _ in range(5):
            rows.append(_obs(day=day, ticker="PANW", outcome="phantom_win", tag="same"))
        rows.append(_obs(day=day, ticker="PANW", outcome="phantom_loss", tag="same"))

    report = build_upstream_signal_driver_drilldown_report(
        rows,
        [{"feature": "ticker", "value": "panw"}],
        [{"feature": "transmission_tag", "value": "same"}],
        gates=UpstreamSignalDriverDrilldownGates(
            min_driver_rows=30,
            min_driver_dates=5,
            min_driver_tickers=5,
        ),
    )

    assert report["verdict"] == "ticker_concentrated_driver_leads"
    assert report["drivers"][0]["driver_verdict"] == "ticker_concentrated_driver"
    assert "driver_top_ticker_share_above_reusable_maximum" in report["drivers"][0]["blockers"]


def test_upstream_signal_drilldown_reports_thin_driver_evidence() -> None:
    rows = [
        _obs(
            day=date(2026, 1, 1) + timedelta(days=index),
            ticker="PANW",
            outcome="phantom_win",
            tag="rare",
        )
        for index in range(3)
    ]

    report = build_upstream_signal_driver_drilldown_report(
        rows,
        [{"feature": "transmission_tag", "value": "rare"}],
        [{"feature": "transmission_tag", "value": "rare"}],
        gates=UpstreamSignalDriverDrilldownGates(
            min_driver_rows=30,
            min_driver_dates=5,
            min_driver_tickers=5,
        ),
    )

    assert report["verdict"] == "thin_driver_evidence"
    assert "driver_rows_below_minimum" in report["drivers"][0]["blockers"]
