from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceCalibrationObservation:
    confidence_percent: float
    outcome: str
    label_source: str = "unknown"
    evidence_date: str | None = None
    ticker: str | None = None
    setup_family: str | None = None
    context_bias: str | None = None
    expected_value: float | None = None


CONFIDENCE_BUCKETS: tuple[tuple[float, float], ...] = (
    (0.0, 40.0),
    (40.0, 45.0),
    (45.0, 50.0),
    (50.0, 55.0),
    (55.0, 60.0),
    (60.0, 65.0),
    (65.0, 70.0),
    (70.0, 75.0),
    (75.0, 100.000001),
)


def calibration_health_report(
    observations: Iterable[ConfidenceCalibrationObservation],
    *,
    min_usable_samples: int = 50,
    min_bucket_samples: int = 20,
    min_distinct_dates: int = 3,
    max_usable_bucket_gap: float = 15.0,
    monotonic_tolerance: float = 5.0,
) -> dict[str, object]:
    rows = [
        item
        for item in observations
        if item.outcome in {"win", "loss"}
        and isinstance(item.confidence_percent, (int, float))
    ]
    bucket_rows: dict[str, list[ConfidenceCalibrationObservation]] = defaultdict(list)
    for item in rows:
        bucket_rows[_bucket_label(float(item.confidence_percent))].append(item)

    buckets = [
        _bucket_payload(label, items)
        for label, items in sorted(bucket_rows.items(), key=lambda pair: _bucket_sort_key(pair[0]))
    ]
    usable_buckets = [
        item for item in buckets if int(item["sample_count"]) >= min_bucket_samples
    ]
    warnings: list[str] = []
    blockers: list[str] = []
    total_samples = len(rows)
    distinct_dates = len(
        {item.evidence_date for item in rows if isinstance(item.evidence_date, str)}
    )
    if total_samples <= 0:
        status = "unavailable"
        blockers.append("calibration_no_resolved_observations")
    elif total_samples < min_usable_samples:
        status = "thin"
        blockers.append("calibration_sample_below_usable_threshold")
    elif distinct_dates and distinct_dates < min_distinct_dates:
        status = "thin"
        blockers.append("calibration_distinct_dates_below_minimum")
    else:
        status = "usable"

    unstable_buckets = [
        item
        for item in usable_buckets
        if abs(float(item["calibration_gap_wr_minus_confidence"])) > max_usable_bucket_gap
    ]
    if unstable_buckets:
        status = "unstable"
        blockers.append("calibration_bucket_gap_exceeds_limit")
        warnings.append(
            "usable_confidence_bucket_gap_exceeds_limit"
        )

    if _is_non_monotonic(usable_buckets, tolerance=monotonic_tolerance):
        status = "non_monotonic"
        blockers.append("calibration_non_monotonic_confidence_buckets")
        warnings.append("higher_confidence_bucket_underperforms_lower_bucket")

    if not usable_buckets and total_samples >= min_usable_samples:
        warnings.append("calibration_has_no_usable_buckets")

    return {
        "schema_version": "confidence-calibration-health-v1",
        "label_sources": sorted(
            {str(item.label_source or "unknown") for item in rows if item.label_source}
        ),
        "status": status,
        "blocks_promotion": status != "usable",
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "sample_count": total_samples,
        "distinct_date_count": distinct_dates,
        "ticker_count": len({item.ticker for item in rows if item.ticker}),
        "bucket_count": len(buckets),
        "usable_bucket_count": len(usable_buckets),
        "min_usable_samples": min_usable_samples,
        "min_bucket_samples": min_bucket_samples,
        "min_distinct_dates": min_distinct_dates,
        "max_usable_bucket_gap": max_usable_bucket_gap,
        "monotonic_tolerance": monotonic_tolerance,
        "buckets": buckets,
    }


def _bucket_payload(
    label: str, items: list[ConfidenceCalibrationObservation]
) -> dict[str, object]:
    sample_count = len(items)
    wins = sum(1 for item in items if item.outcome == "win")
    confidence_sum = sum(float(item.confidence_percent) for item in items)
    ev_values = [
        item.expected_value
        for item in items
        if isinstance(item.expected_value, (int, float))
    ]
    avg_confidence = confidence_sum / sample_count if sample_count else 0.0
    actual_wr = (wins / sample_count) * 100.0 if sample_count else 0.0
    return {
        "bucket": label,
        "sample_count": sample_count,
        "wins": wins,
        "losses": sample_count - wins,
        "avg_confidence_percent": round(avg_confidence, 4),
        "actual_wr_percent": round(actual_wr, 4),
        "calibration_gap_wr_minus_confidence": round(actual_wr - avg_confidence, 4),
        "distinct_date_count": len({item.evidence_date for item in items if item.evidence_date}),
        "ticker_count": len({item.ticker for item in items if item.ticker}),
        "ev_total": round(sum(float(value) for value in ev_values), 4) if ev_values else None,
        "ev_per_observation": round(sum(float(value) for value in ev_values) / sample_count, 6)
        if ev_values and sample_count
        else None,
    }


def _bucket_label(confidence: float) -> str:
    bounded = max(0.0, min(100.0, confidence))
    for lower, upper in CONFIDENCE_BUCKETS:
        if lower <= bounded < upper:
            return f"{int(lower)}-{int(min(100.0, upper))}"
    return "unknown"


def _bucket_sort_key(label: str) -> float:
    try:
        return float(label.split("-", 1)[0])
    except (TypeError, ValueError):
        return 999.0


def _is_non_monotonic(buckets: list[dict[str, object]], *, tolerance: float) -> bool:
    ordered = sorted(buckets, key=lambda item: _bucket_sort_key(str(item["bucket"])))
    previous_wr: float | None = None
    for item in ordered:
        wr = float(item["actual_wr_percent"])
        if previous_wr is not None and wr + tolerance < previous_wr:
            return True
        previous_wr = wr
    return False
