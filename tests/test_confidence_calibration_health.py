from __future__ import annotations

from trade_proposer_app.services.confidence_calibration_health import (
    ConfidenceCalibrationObservation,
    calibration_health_report,
)


def _obs(
    confidence: float,
    outcome: str,
    *,
    date_index: int = 1,
    ticker: str = "AAPL",
) -> ConfidenceCalibrationObservation:
    return ConfidenceCalibrationObservation(
        confidence_percent=confidence,
        outcome=outcome,
        evidence_date=f"2026-06-{date_index:02d}",
        ticker=ticker,
        expected_value=1.0 if outcome == "win" else -1.0,
    )


def test_calibration_health_blocks_when_sample_is_thin() -> None:
    report = calibration_health_report([_obs(45.0, "win")], min_usable_samples=10)

    assert report["status"] == "thin"
    assert report["blocks_promotion"] is True
    assert "calibration_sample_below_usable_threshold" in report["blockers"]


def test_calibration_health_flags_large_bucket_gap() -> None:
    observations = [
        _obs(55.0, "loss", date_index=(index % 4) + 1, ticker=f"T{index}")
        for index in range(30)
    ] + [
        _obs(45.0, "win" if index < 12 else "loss", date_index=(index % 4) + 1, ticker=f"U{index}")
        for index in range(30)
    ]

    report = calibration_health_report(
        observations,
        min_usable_samples=50,
        min_bucket_samples=20,
        max_usable_bucket_gap=15.0,
    )

    assert report["status"] in {"unstable", "non_monotonic"}
    assert report["blocks_promotion"] is True
    assert any("calibration_bucket_gap_exceeds_limit" == item for item in report["blockers"])


def test_calibration_health_flags_non_monotonic_usable_buckets() -> None:
    observations = [
        _obs(42.0, "win" if index < 18 else "loss", date_index=(index % 4) + 1, ticker=f"L{index}")
        for index in range(30)
    ] + [
        _obs(52.0, "win" if index < 6 else "loss", date_index=(index % 4) + 1, ticker=f"H{index}")
        for index in range(30)
    ]

    report = calibration_health_report(
        observations,
        min_usable_samples=50,
        min_bucket_samples=20,
        max_usable_bucket_gap=100.0,
        monotonic_tolerance=5.0,
    )

    assert report["status"] == "non_monotonic"
    assert "calibration_non_monotonic_confidence_buckets" in report["blockers"]


def test_calibration_health_passes_usable_monotonic_observations() -> None:
    observations = [
        _obs(42.0, "win" if index < 10 else "loss", date_index=(index % 4) + 1, ticker=f"L{index}")
        for index in range(30)
    ] + [
        _obs(52.0, "win" if index < 15 else "loss", date_index=(index % 4) + 1, ticker=f"M{index}")
        for index in range(30)
    ] + [
        _obs(62.0, "win" if index < 20 else "loss", date_index=(index % 4) + 1, ticker=f"H{index}")
        for index in range(30)
    ]

    report = calibration_health_report(
        observations,
        min_usable_samples=50,
        min_bucket_samples=20,
        max_usable_bucket_gap=30.0,
    )

    assert report["status"] == "usable"
    assert report["blocks_promotion"] is False
    assert report["usable_bucket_count"] == 3
