from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from math import floor
from typing import Any

from trade_proposer_app.services.phantom_selectivity_separability import (
    PhantomSelectivityObservation,
)


@dataclass(frozen=True, slots=True)
class UpstreamSignalDriverObservation:
    base: PhantomSelectivityObservation
    signal_breakdown: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UpstreamSignalDriverAuditGates:
    min_candidate_rows: int = 100
    min_candidate_dates: int = 10
    min_feature_rows: int = 30
    min_feature_dates: int = 5
    min_reusable_feature_coverage_percent: float = 60.0
    min_feature_win_rate_lift_pct: float = 5.0
    min_feature_ev_per_observation: float = 0.0

    def payload(self) -> dict[str, object]:
        return {
            "min_candidate_rows": self.min_candidate_rows,
            "min_candidate_dates": self.min_candidate_dates,
            "min_feature_rows": self.min_feature_rows,
            "min_feature_dates": self.min_feature_dates,
            "min_reusable_feature_coverage_percent": self.min_reusable_feature_coverage_percent,
            "min_feature_win_rate_lift_pct": self.min_feature_win_rate_lift_pct,
            "min_feature_ev_per_observation": self.min_feature_ev_per_observation,
        }


REUSABLE_FEATURES: tuple[str, ...] = (
    "setup_family",
    "context_bias",
    "action",
    "effective_action",
    "confidence_bucket",
    "volatility_bucket",
    "transmission_tag",
    "expected_transmission_window",
    "catalyst_intensity_bucket",
    "decision_tier",
    "shortlisted",
    "shortlist_rank_bucket",
    "confidence_component_bucket",
    "calibration_review",
    "fundamental_coverage_status",
)


def build_upstream_signal_driver_audit_report(
    observations: list[UpstreamSignalDriverObservation],
    candidate_groups: list[dict[str, object]],
    *,
    gates: UpstreamSignalDriverAuditGates | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or UpstreamSignalDriverAuditGates()
    rows = [
        item
        for item in observations
        if item.base.outcome in {"phantom_win", "phantom_loss"}
        and item.base.reward_pct > 0
        and item.base.risk_pct > 0
    ]
    candidate_rows = _candidate_rows(rows, candidate_groups)
    population_metrics = _metric_payload(rows)
    candidate_metrics = _metric_payload(candidate_rows)
    candidate_baseline_wr = float(candidate_metrics["win_rate_percent"])
    candidate_feature_rows = [
        item for item in candidate_rows if _has_reusable_signal_feature(item)
    ]
    coverage_percent = (
        round((len(candidate_feature_rows) / len(candidate_rows)) * 100.0, 4)
        if candidate_rows
        else 0.0
    )

    blockers: list[str] = []
    if int(candidate_metrics["count"]) < gates.min_candidate_rows:
        blockers.append("candidate_rows_below_minimum")
    if int(candidate_metrics["distinct_date_count"]) < gates.min_candidate_dates:
        blockers.append("candidate_dates_below_minimum")
    if coverage_percent < gates.min_reusable_feature_coverage_percent:
        blockers.append("reusable_signal_feature_coverage_below_minimum")

    reusable_enrichment = _feature_enrichment(rows, candidate_rows, REUSABLE_FEATURES)
    reusable_win_loss = _feature_win_loss(
        candidate_rows,
        REUSABLE_FEATURES,
        baseline_win_rate=candidate_baseline_wr,
        gates=gates,
    )
    ticker_diagnostics = _feature_win_loss(
        candidate_rows,
        ("ticker",),
        baseline_win_rate=candidate_baseline_wr,
        gates=gates,
    )
    passing_reusable = [
        item for item in reusable_win_loss if bool(item["passes_feature_gates"])
    ]

    if blockers:
        verdict = "insufficient_feature_coverage"
    elif passing_reusable:
        verdict = "upstream_feature_lead"
    else:
        verdict = "ticker_artifact_only"
        blockers.append("no_reusable_signal_feature_passed_gates")

    return {
        "schema_version": "upstream-signal-driver-audit-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "blockers": sorted(set(blockers)),
        "gates": gates.payload(),
        "candidate_group_count": len(candidate_groups),
        "record_counts": {
            "population": int(population_metrics["count"]),
            "candidate": int(candidate_metrics["count"]),
            "candidate_with_reusable_signal_feature": len(candidate_feature_rows),
        },
        "metrics": {
            "population": population_metrics,
            "candidate": candidate_metrics,
        },
        "reusable_signal_feature_coverage_percent": coverage_percent,
        "top_reusable_candidate_enrichment": reusable_enrichment[:25],
        "top_reusable_candidate_win_loss_drivers": reusable_win_loss[:25],
        "ticker_diagnostics": ticker_diagnostics[:20],
        "recommendation": _recommendation(verdict),
    }


def _candidate_rows(
    rows: list[UpstreamSignalDriverObservation],
    candidate_groups: list[dict[str, object]],
) -> list[UpstreamSignalDriverObservation]:
    selected_indexes: set[int] = set()
    for group in candidate_groups:
        feature = str(group.get("feature") or "").strip()
        value = str(group.get("value") or "").strip().lower()
        if not feature or not value:
            continue
        for index, row in enumerate(rows):
            if value in _feature_values(row, feature):
                selected_indexes.add(index)
    return [row for index, row in enumerate(rows) if index in selected_indexes]


def _feature_enrichment(
    population_rows: list[UpstreamSignalDriverObservation],
    candidate_rows: list[UpstreamSignalDriverObservation],
    feature_names: tuple[str, ...],
) -> list[dict[str, object]]:
    population_count = max(1, len(population_rows))
    candidate_count = max(1, len(candidate_rows))
    population_counter = _feature_counter(population_rows, feature_names)
    candidate_counter = _feature_counter(candidate_rows, feature_names)
    payloads: list[dict[str, object]] = []
    for key, candidate_seen in candidate_counter.items():
        population_seen = population_counter.get(key, 0)
        candidate_share = candidate_seen / candidate_count
        population_share = population_seen / population_count
        feature, value = key.split("=", 1)
        payloads.append(
            {
                "feature": feature,
                "value": value,
                "candidate_count": candidate_seen,
                "population_count": population_seen,
                "candidate_share_percent": round(candidate_share * 100.0, 4),
                "population_share_percent": round(population_share * 100.0, 4),
                "share_lift_pct": round((candidate_share - population_share) * 100.0, 4),
            }
        )
    payloads.sort(
        key=lambda item: (
            float(item["share_lift_pct"]),
            int(item["candidate_count"]),
        ),
        reverse=True,
    )
    return payloads


def _feature_win_loss(
    rows: list[UpstreamSignalDriverObservation],
    feature_names: tuple[str, ...],
    *,
    baseline_win_rate: float,
    gates: UpstreamSignalDriverAuditGates,
) -> list[dict[str, object]]:
    grouped: dict[str, list[UpstreamSignalDriverObservation]] = defaultdict(list)
    for row in rows:
        for feature_name in feature_names:
            for value in _feature_values(row, feature_name):
                grouped[f"{feature_name}={value}"].append(row)
    payloads: list[dict[str, object]] = []
    for key, group_rows in grouped.items():
        metrics = _metric_payload(group_rows)
        lift = float(metrics["win_rate_percent"]) - baseline_win_rate
        feature, value = key.split("=", 1)
        passes = (
            int(metrics["count"]) >= gates.min_feature_rows
            and int(metrics["distinct_date_count"]) >= gates.min_feature_dates
            and lift >= gates.min_feature_win_rate_lift_pct
            and float(metrics["expected_value_per_observation"])
            > gates.min_feature_ev_per_observation
        )
        payloads.append(
            {
                "feature": feature,
                "value": value,
                "metrics": metrics,
                "candidate_win_rate_lift_pct": round(lift, 4),
                "passes_feature_gates": passes,
            }
        )
    payloads.sort(
        key=lambda item: (
            bool(item["passes_feature_gates"]),
            float(item["candidate_win_rate_lift_pct"]),
            float(item["metrics"]["expected_value_per_observation"]),
            int(item["metrics"]["count"]),
        ),
        reverse=True,
    )
    return payloads


def _feature_counter(
    rows: list[UpstreamSignalDriverObservation],
    feature_names: tuple[str, ...],
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        for feature_name in feature_names:
            for value in _feature_values(row, feature_name):
                counter[f"{feature_name}={value}"] += 1
    return counter


def _feature_values(row: UpstreamSignalDriverObservation, feature_name: str) -> set[str]:
    base = row.base
    signal = row.signal_breakdown
    if feature_name == "ticker":
        return {_clean(base.ticker)}
    if feature_name == "setup_family":
        return {_clean(base.setup_family)}
    if feature_name == "context_bias":
        return {_clean(base.context_bias)}
    if feature_name == "action":
        return {_clean(base.action)}
    if feature_name == "effective_action":
        return {_clean(base.effective_action)}
    if feature_name == "confidence_bucket":
        return {_numeric_bucket(base.confidence_percent, step=5.0, lower=0.0, upper=100.0)}
    if feature_name == "volatility_bucket":
        if base.volatility_score is None:
            return {"unknown"}
        return {_numeric_bucket(_normalize_percent(base.volatility_score), step=10.0, lower=0.0, upper=100.0)}
    if feature_name == "expected_transmission_window":
        return {_clean(_nested_get(signal, "transmission_summary", "expected_transmission_window") or signal.get("expected_transmission_window"))}
    if feature_name == "catalyst_intensity_bucket":
        value = _first_number(
            signal.get("catalyst_intensity_percent"),
            _nested_get(signal, "transmission_summary", "catalyst_intensity_percent"),
        )
        return {"unknown"} if value is None else {_numeric_bucket(value, step=10.0, lower=0.0, upper=100.0)}
    if feature_name == "decision_tier":
        return {_clean(signal.get("decision_tier"))}
    if feature_name == "shortlisted":
        value = signal.get("shortlisted")
        if isinstance(value, bool):
            return {str(value).lower()}
        return {"unknown"}
    if feature_name == "shortlist_rank_bucket":
        value = _first_number(signal.get("shortlist_rank"))
        if value is None:
            return {"unknown"}
        return {_numeric_bucket(value, step=5.0, lower=0.0, upper=50.0)}
    if feature_name == "calibration_review":
        review = signal.get("calibration_review")
        if isinstance(review, dict):
            return {
                _clean(review.get("direction") or review.get("action") or review.get("verdict"))
            }
        return {_clean(review)}
    if feature_name == "fundamental_coverage_status":
        return {
            _clean(
                signal.get("fundamental_coverage_status")
                or _nested_get(signal, "fundamental_snapshot", "coverage_status")
            )
        }
    if feature_name == "transmission_tag":
        return _transmission_tags(signal)
    if feature_name == "confidence_component_bucket":
        return _confidence_component_buckets(signal)
    return {"unknown"}


def _has_reusable_signal_feature(row: UpstreamSignalDriverObservation) -> bool:
    signal = row.signal_breakdown
    if not signal:
        return False
    raw_feature_names = (
        "setup_family",
        "context_bias",
        "intended_action",
        "cheap_scan_volatility_score",
        "transmission_tags",
        "expected_transmission_window",
        "catalyst_intensity_percent",
        "decision_tier",
        "shortlisted",
        "shortlist_rank",
        "confidence_components",
        "calibration_review",
        "fundamental_coverage_status",
    )
    if any(_clean(signal.get(key)) != "unknown" for key in raw_feature_names):
        return True
    transmission_summary = signal.get("transmission_summary")
    if isinstance(transmission_summary, dict) and any(transmission_summary.values()):
        return True
    fundamental_snapshot = signal.get("fundamental_snapshot")
    return bool(isinstance(fundamental_snapshot, dict) and fundamental_snapshot)
    return False


def _transmission_tags(signal: dict[str, object]) -> set[str]:
    values: list[object] = []
    for candidate in (
        signal.get("transmission_tags"),
        _nested_get(signal, "transmission_summary", "transmission_tags"),
    ):
        if isinstance(candidate, list):
            values.extend(candidate)
    cleaned = {_clean(item) for item in values if _clean(item) != "unknown"}
    return cleaned or {"unknown"}


def _confidence_component_buckets(signal: dict[str, object]) -> set[str]:
    components = signal.get("confidence_components")
    if not isinstance(components, dict):
        return {"unknown"}
    values: set[str] = set()
    for key, value in components.items():
        number = _first_number(value)
        if number is None:
            continue
        values.add(f"{_clean(key)}:{_numeric_bucket(number, step=10.0, lower=0.0, upper=100.0)}")
    return values or {"unknown"}


def _metric_payload(rows: list[UpstreamSignalDriverObservation]) -> dict[str, object]:
    count = len(rows)
    wins = sum(1 for item in rows if item.base.outcome == "phantom_win")
    losses = sum(1 for item in rows if item.base.outcome == "phantom_loss")
    ev_total = sum(
        item.base.reward_pct if item.base.outcome == "phantom_win" else -item.base.risk_pct
        for item in rows
    )
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate_percent": round((wins / count) * 100.0, 4) if count else 0.0,
        "expected_value": round(ev_total, 4),
        "expected_value_per_observation": round(ev_total / count, 6) if count else 0.0,
        "distinct_date_count": len({item.base.evidence_date for item in rows}),
        "ticker_count": len({item.base.ticker for item in rows if item.base.ticker}),
    }


def _nested_get(payload: dict[str, object], *keys: str) -> object | None:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_number(*values: object) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _normalize_percent(value: float) -> float:
    value = float(value)
    if value <= 1.0:
        value *= 100.0
    return max(0.0, min(100.0, value))


def _numeric_bucket(value: float, *, step: float, lower: float, upper: float) -> str:
    bounded = max(lower, min(upper, float(value)))
    bucket_lower = lower + (floor((bounded - lower) / step) * step)
    bucket_upper = min(upper, bucket_lower + step)
    return f"{bucket_lower:g}-{bucket_upper:g}"


def _clean(value: object) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _recommendation(verdict: str) -> str:
    if verdict == "upstream_feature_lead":
        return (
            "Inspect and improve upstream generation around the listed reusable signal "
            "features, then rerun candidate replay after more dates accumulate."
        )
    if verdict == "ticker_artifact_only":
        return (
            "Do not run more broad tuning. Inspect ticker-specific upstream generation "
            "for the passing groups before adding new knobs."
        )
    return (
        "Improve signal feature persistence and coverage before making more tuning or "
        "upstream quality claims."
    )
