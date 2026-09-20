from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil

from trade_proposer_app.services.upstream_signal_driver_audit import (
    REUSABLE_FEATURES,
    UpstreamSignalDriverObservation,
    _candidate_rows,
    _feature_values,
    _metric_payload,
    _top_values,
)


@dataclass(frozen=True, slots=True)
class UpstreamDriverQualityGates:
    min_driver_rows: int = 30
    min_driver_dates: int = 5
    min_driver_tickers: int = 5
    min_selection_rows: int = 100
    min_selection_dates: int = 20
    max_single_ticker_share_percent: float = 50.0
    min_ev_per_observation: float = 0.0
    selection_date_fraction: float = 0.25

    def payload(self) -> dict[str, object]:
        return {
            "min_driver_rows": self.min_driver_rows,
            "min_driver_dates": self.min_driver_dates,
            "min_driver_tickers": self.min_driver_tickers,
            "min_selection_rows": self.min_selection_rows,
            "min_selection_dates": self.min_selection_dates,
            "max_single_ticker_share_percent": self.max_single_ticker_share_percent,
            "min_ev_per_observation": self.min_ev_per_observation,
            "selection_date_fraction": self.selection_date_fraction,
        }


def build_upstream_driver_quality_report(
    observations: list[UpstreamSignalDriverObservation],
    candidate_groups: list[dict[str, object]],
    driver_specs: list[dict[str, object]],
    *,
    source_artifacts: dict[str, str] | None = None,
    gates: UpstreamDriverQualityGates | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or UpstreamDriverQualityGates()
    rows = [
        item
        for item in observations
        if item.base.outcome in {"phantom_win", "phantom_loss"}
        and item.base.reward_pct > 0
        and item.base.risk_pct > 0
    ]
    candidate_rows = _candidate_rows(rows, candidate_groups)
    discovery_rows, selection_rows = _split_rows_by_date(
        candidate_rows,
        selection_date_fraction=gates.selection_date_fraction,
    )
    drivers = [
        _driver_quality_payload(
            rows=candidate_rows,
            selection_rows=selection_rows,
            discovery_rows=discovery_rows,
            spec=spec,
            gates=gates,
        )
        for spec in driver_specs
        if _valid_driver_spec(spec)
    ]
    score_counts = Counter(str(item["scorecard_status"]) for item in drivers)
    blockers = sorted(
        {
            blocker
            for driver in drivers
            for blocker in list(driver.get("blockers") or [])
            if blocker
        }
    )
    return {
        "schema_version": "upstream-driver-quality-v1",
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "verdict": _report_verdict(drivers),
        "blockers": blockers,
        "gates": gates.payload(),
        "input": {
            "source_artifacts": source_artifacts or {},
            "candidate_group_count": len(candidate_groups),
            "driver_spec_count": len(driver_specs),
            "replay_evidence_profile": "phantom_selectivity",
        },
        "record_counts": {
            "population": len(rows),
            "candidate": len(candidate_rows),
            "discovery": len(discovery_rows),
            "selection": len(selection_rows),
        },
        "metrics": {
            "population": _metric_payload(rows),
            "candidate": _metric_payload(candidate_rows),
            "discovery": _metric_payload(discovery_rows),
            "selection": _metric_payload(selection_rows),
        },
        "candidate_groups": candidate_groups,
        "drivers": drivers,
        "scorecard_counts": dict(sorted(score_counts.items())),
        "recommendation": _recommendation(drivers),
    }


def markdown_summary(report: dict[str, object]) -> str:
    lines = [
        "# Upstream driver quality",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        "## Record counts",
    ]
    counts = report.get("record_counts") or {}
    for key in ("population", "candidate", "discovery", "selection"):
        lines.append(f"- {key}: {counts.get(key, 0)}")
    lines.extend(["", "## Scorecard"])
    for driver in list(report.get("drivers") or []):
        metrics = driver.get("metrics") or {}
        selection = driver.get("selection_metrics") or {}
        lines.extend(
            [
                (
                    f"- `{driver['feature']}={driver['value']}`: "
                    f"{driver['scorecard_status']}; "
                    f"rows {metrics.get('count', 0)}, dates "
                    f"{metrics.get('distinct_date_count', 0)}, tickers "
                    f"{metrics.get('ticker_count', 0)}, EV/obs "
                    f"{metrics.get('expected_value_per_observation', 0)}"
                ),
                (
                    f"  selection rows {selection.get('count', 0)}, "
                    f"selection dates {selection.get('distinct_date_count', 0)}"
                ),
            ]
        )
        blockers = list(driver.get("blockers") or [])
        if blockers:
            lines.append(f"  blockers: {', '.join(blockers)}")
    lines.extend(["", "## Recommendation", str(report.get("recommendation") or "")])
    return "\n".join(lines) + "\n"


def _driver_quality_payload(
    *,
    rows: list[UpstreamSignalDriverObservation],
    discovery_rows: list[UpstreamSignalDriverObservation],
    selection_rows: list[UpstreamSignalDriverObservation],
    spec: dict[str, object],
    gates: UpstreamDriverQualityGates,
) -> dict[str, object]:
    feature = str(spec.get("feature") or "").strip()
    value = str(spec.get("value") or "").strip().lower()
    driver_rows = [item for item in rows if value in _feature_values(item, feature)]
    driver_discovery = [item for item in discovery_rows if value in _feature_values(item, feature)]
    driver_selection = [item for item in selection_rows if value in _feature_values(item, feature)]
    metrics = _metric_payload(driver_rows)
    selection_metrics = _metric_payload(driver_selection)
    ticker_mix = _top_values(driver_rows, "ticker", limit=10)
    top_ticker_share = float(ticker_mix[0]["share_percent"]) if ticker_mix else 0.0
    lineage = _lineage_quality(feature, driver_rows)
    ablations = _ablations(driver_rows, feature)
    neighbor_shape = _neighbor_shape(rows, feature, value)
    blockers = _driver_blockers(
        metrics=metrics,
        selection_metrics=selection_metrics,
        top_ticker_share=top_ticker_share,
        lineage=lineage,
        ablations=ablations,
        gates=gates,
    )
    status = _scorecard_status(
        metrics=metrics,
        selection_metrics=selection_metrics,
        top_ticker_share=top_ticker_share,
        lineage=lineage,
        ablations=ablations,
        blockers=blockers,
        gates=gates,
    )
    return {
        "feature": feature,
        "value": value,
        "scorecard_status": status,
        "blockers": blockers,
        "metrics": metrics,
        "discovery_metrics": _metric_payload(driver_discovery),
        "selection_metrics": selection_metrics,
        "mix": {
            "tickers": ticker_mix,
            "setup_family": _top_values(driver_rows, "setup_family", limit=8),
            "context_bias": _top_values(driver_rows, "context_bias", limit=8),
            "effective_action": _top_values(driver_rows, "effective_action", limit=8),
            "transmission_tag": _top_values(driver_rows, "transmission_tag", limit=12),
            "confidence_bucket": _top_values(driver_rows, "confidence_bucket", limit=8),
            "volatility_bucket": _top_values(driver_rows, "volatility_bucket", limit=8),
        },
        "weekly_stability": _period_metrics(driver_rows),
        "neighbor_shape": neighbor_shape,
        "lineage_quality": lineage,
        "ablations": ablations,
        "follow_up": _driver_follow_up(status, feature, value),
    }


def _driver_blockers(
    *,
    metrics: dict[str, object],
    selection_metrics: dict[str, object],
    top_ticker_share: float,
    lineage: dict[str, object],
    ablations: dict[str, object],
    gates: UpstreamDriverQualityGates,
) -> list[str]:
    blockers: list[str] = []
    if int(metrics["count"]) < gates.min_driver_rows:
        blockers.append("driver_rows_below_minimum")
    if int(metrics["distinct_date_count"]) < gates.min_driver_dates:
        blockers.append("driver_dates_below_minimum")
    if int(metrics["ticker_count"]) < gates.min_driver_tickers:
        blockers.append("driver_ticker_count_below_reusable_minimum")
    if float(metrics["expected_value_per_observation"]) <= gates.min_ev_per_observation:
        blockers.append("driver_ev_per_observation_not_positive")
    if int(selection_metrics["count"]) < gates.min_selection_rows:
        blockers.append("selection_rows_below_promotion_minimum")
    if int(selection_metrics["distinct_date_count"]) < gates.min_selection_dates:
        blockers.append("selection_dates_below_promotion_minimum")
    if top_ticker_share > gates.max_single_ticker_share_percent:
        blockers.append("top_ticker_share_above_reusable_maximum")
    if float(lineage["usable_lineage_share_percent"]) < 80.0:
        blockers.append("lineage_quality_below_review_floor")
    top_ticker_ablation = ablations["without_top_ticker"]["metrics"]
    if (
        int(top_ticker_ablation["count"]) > 0
        and float(top_ticker_ablation["expected_value_per_observation"])
        <= gates.min_ev_per_observation
    ):
        blockers.append("top_ticker_ablation_loses_positive_ev")
    return sorted(set(blockers))


def _scorecard_status(
    *,
    metrics: dict[str, object],
    selection_metrics: dict[str, object],
    top_ticker_share: float,
    lineage: dict[str, object],
    ablations: dict[str, object],
    blockers: list[str],
    gates: UpstreamDriverQualityGates,
) -> str:
    if float(metrics["expected_value_per_observation"]) <= gates.min_ev_per_observation:
        return "reject"
    if (
        int(metrics["count"]) >= gates.min_driver_rows
        and int(metrics["distinct_date_count"]) >= gates.min_driver_dates
        and int(metrics["ticker_count"]) >= gates.min_driver_tickers
        and top_ticker_share <= gates.max_single_ticker_share_percent
        and float(lineage["usable_lineage_share_percent"]) >= 80.0
        and int(selection_metrics["count"]) >= gates.min_selection_rows
        and int(selection_metrics["distinct_date_count"]) >= gates.min_selection_dates
        and "top_ticker_ablation_loses_positive_ev" not in blockers
    ):
        return "reusable_candidate"
    if (
        "top_ticker_share_above_reusable_maximum" in blockers
        or "top_ticker_ablation_loses_positive_ev" in blockers
    ):
        return "diagnostic_only"
    if int(metrics["count"]) >= gates.min_driver_rows:
        return "watch"
    return "reject"


def _ablations(
    rows: list[UpstreamSignalDriverObservation],
    feature: str,
) -> dict[str, object]:
    ticker_counts = Counter(item.base.ticker for item in rows)
    top_tickers = [ticker for ticker, _count in ticker_counts.most_common(3)]
    top_ticker = top_tickers[:1]
    strong_lineage_rows = [item for item in rows if _has_usable_lineage(feature, item)]
    without_top_ticker = [item for item in rows if item.base.ticker not in top_ticker]
    without_top_3_tickers = [item for item in rows if item.base.ticker not in top_tickers]
    return {
        "original": {"metrics": _metric_payload(rows)},
        "without_top_ticker": {
            "removed_tickers": top_ticker,
            "metrics": _metric_payload(without_top_ticker),
        },
        "without_top_3_tickers": {
            "removed_tickers": top_tickers,
            "metrics": _metric_payload(without_top_3_tickers),
        },
        "usable_lineage_only": {
            "metrics": _metric_payload(strong_lineage_rows),
        },
    }


def _lineage_quality(
    feature: str,
    rows: list[UpstreamSignalDriverObservation],
) -> dict[str, object]:
    usable = [item for item in rows if _has_usable_lineage(feature, item)]
    total = len(rows)
    missing_reasons = Counter(_lineage_reason(feature, item) for item in rows if item not in usable)
    return {
        "row_count": total,
        "usable_lineage_rows": len(usable),
        "usable_lineage_share_percent": round((len(usable) / max(1, total)) * 100.0, 4),
        "missing_or_weak_reasons": dict(sorted(missing_reasons.items())),
    }


def _has_usable_lineage(feature: str, row: UpstreamSignalDriverObservation) -> bool:
    return _lineage_reason(feature, row) == "usable"


def _lineage_reason(feature: str, row: UpstreamSignalDriverObservation) -> str:
    signal = row.signal_breakdown
    if not signal:
        return "missing_signal_breakdown"
    if feature == "volatility_bucket":
        return "usable" if row.base.volatility_score is not None else "missing_volatility_score"
    if feature == "catalyst_intensity_bucket":
        summary = signal.get("transmission_summary")
        if signal.get("catalyst_intensity_percent") is not None:
            return "usable"
        if isinstance(summary, dict) and summary.get("catalyst_intensity_percent") is not None:
            return "usable"
        return "missing_catalyst_intensity"
    if feature == "shortlist_rank_bucket":
        return "usable" if signal.get("shortlist_rank") is not None else "missing_shortlist_rank"
    if feature == "confidence_component_bucket":
        components = signal.get("confidence_components")
        if isinstance(components, dict) and bool(components):
            return "usable"
        return "missing_components"
    if feature in REUSABLE_FEATURES:
        return "usable"
    return "unsupported_feature"


def _neighbor_shape(
    rows: list[UpstreamSignalDriverObservation],
    feature: str,
    value: str,
) -> dict[str, object]:
    grouped: dict[str, list[UpstreamSignalDriverObservation]] = defaultdict(list)
    for row in rows:
        for candidate in _feature_values(row, feature):
            grouped[candidate].append(row)
    wanted = _neighbor_values(_sorted_feature_values(grouped, value), value)
    buckets = [
        {"value": item, "metrics": _metric_payload(grouped.get(item, []))}
        for item in wanted
    ]
    positive = [
        item
        for item in buckets
        if float(item["metrics"]["expected_value_per_observation"]) > 0.0
    ]
    return {
        "comparison_values": buckets,
        "shape_verdict": "coherent_or_plateau" if len(positive) >= 2 else "isolated_or_thin",
    }


def _neighbor_values(values: list[str], target: str) -> list[str]:
    if target not in values:
        return [target]
    index = values.index(target)
    return values[max(0, index - 1) : min(len(values), index + 2)]


def _sorted_feature_values(
    grouped: dict[str, list[UpstreamSignalDriverObservation]],
    target: str,
) -> list[str]:
    values = list(grouped)
    if ":" in target:
        prefix = target.split(":", 1)[0]
        values = [item for item in values if item.startswith(f"{prefix}:")]
    numeric_values = [item for item in values if _bucket_sort_key(item) is not None]
    if numeric_values:
        return sorted(numeric_values, key=lambda item: (_bucket_sort_key(item), item))
    return sorted(values)


def _bucket_sort_key(value: str) -> float | None:
    bucket = value.split(":", 1)[-1]
    lower = bucket.split("-", 1)[0]
    try:
        return float(lower)
    except ValueError:
        return None


def _period_metrics(rows: list[UpstreamSignalDriverObservation]) -> list[dict[str, object]]:
    grouped: dict[str, list[UpstreamSignalDriverObservation]] = defaultdict(list)
    for row in rows:
        iso = row.base.evidence_date.isocalendar()
        grouped[f"{iso.year}-W{iso.week:02d}"].append(row)
    return [
        {"period": period, "metrics": _metric_payload(period_rows)}
        for period, period_rows in sorted(grouped.items())
    ]


def _split_rows_by_date(
    rows: list[UpstreamSignalDriverObservation],
    *,
    selection_date_fraction: float,
) -> tuple[list[UpstreamSignalDriverObservation], list[UpstreamSignalDriverObservation]]:
    dates = sorted({item.base.evidence_date for item in rows})
    if not dates:
        return [], []
    selection_count = max(1, ceil(len(dates) * selection_date_fraction))
    selection_dates = set(dates[-selection_count:])
    discovery = [item for item in rows if item.base.evidence_date not in selection_dates]
    selection = [item for item in rows if item.base.evidence_date in selection_dates]
    return discovery, selection


def _valid_driver_spec(spec: dict[str, object]) -> bool:
    feature = str(spec.get("feature") or "").strip()
    value = str(spec.get("value") or "").strip()
    return bool(feature and value and feature in REUSABLE_FEATURES)


def _report_verdict(drivers: list[dict[str, object]]) -> str:
    statuses = {str(item.get("scorecard_status")) for item in drivers}
    if "reusable_candidate" in statuses:
        return "reusable_driver_quality_candidate"
    if "diagnostic_only" in statuses or "watch" in statuses:
        return "analysis_only_driver_leads"
    return "no_reusable_driver_quality_lead"


def _recommendation(drivers: list[dict[str, object]]) -> str:
    if any(item["scorecard_status"] == "reusable_candidate" for item in drivers):
        return (
            "Review generation code for reusable candidates, then wait for promotion-grade "
            "selection evidence before any behavior change."
        )
    if any(item["scorecard_status"] in {"diagnostic_only", "watch"} for item in drivers):
        return (
            "Use these drivers as diagnostics for upstream instrumentation and generation "
            "inspection only. Do not tune behavior from this evidence."
        )
    return "No driver is clean enough for tuning; wait or repair instrumentation."


def _driver_follow_up(status: str, feature: str, value: str) -> str:
    if status == "reusable_candidate":
        return (
            f"Inspect generation code for {feature}={value}; "
            "do not promote without replay gates."
        )
    if status == "diagnostic_only":
        return f"Treat {feature}={value} as a concentration or ablation diagnostic."
    if status == "watch":
        return f"Keep collecting evidence for {feature}={value} and rerun the scorecard."
    return f"Do not act on {feature}={value} without new evidence."
