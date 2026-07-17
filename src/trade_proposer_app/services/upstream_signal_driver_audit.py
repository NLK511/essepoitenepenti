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
    plan_id: int | None = None


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


@dataclass(frozen=True, slots=True)
class UpstreamSignalDriverDrilldownGates:
    min_driver_rows: int = 30
    min_driver_dates: int = 5
    min_driver_tickers: int = 5
    min_driver_ev_per_observation: float = 0.0
    max_single_ticker_share_percent: float = 50.0

    def payload(self) -> dict[str, object]:
        return {
            "min_driver_rows": self.min_driver_rows,
            "min_driver_dates": self.min_driver_dates,
            "min_driver_tickers": self.min_driver_tickers,
            "min_driver_ev_per_observation": self.min_driver_ev_per_observation,
            "max_single_ticker_share_percent": self.max_single_ticker_share_percent,
        }


@dataclass(frozen=True, slots=True)
class ProspectiveSignalDriverTagObservation:
    plan_id: int | None
    evidence_date: date
    ticker: str
    action: str
    setup_family: str
    signal_breakdown: dict[str, object] = field(default_factory=dict)
    replay_outcome: str | None = None
    replay_resolution_source: str | None = None
    reward_pct: float | None = None
    risk_pct: float | None = None


@dataclass(frozen=True, slots=True)
class ProspectiveSignalDriverTagMonitorGates:
    min_tagged_rows: int = 30
    min_tagged_dates: int = 5
    min_replay_labeled_rows: int = 30
    min_replay_labeled_dates: int = 5
    promotion_watch_date_floor: int = 20
    max_single_ticker_share_percent: float = 50.0

    def payload(self) -> dict[str, object]:
        return {
            "min_tagged_rows": self.min_tagged_rows,
            "min_tagged_dates": self.min_tagged_dates,
            "min_replay_labeled_rows": self.min_replay_labeled_rows,
            "min_replay_labeled_dates": self.min_replay_labeled_dates,
            "promotion_watch_date_floor": self.promotion_watch_date_floor,
            "max_single_ticker_share_percent": self.max_single_ticker_share_percent,
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


def build_prospective_signal_driver_tag_monitor_report(
    observations: list[ProspectiveSignalDriverTagObservation],
    *,
    gates: ProspectiveSignalDriverTagMonitorGates | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or ProspectiveSignalDriverTagMonitorGates()
    tagged_rows = [item for item in observations if _prospective_driver_tags(item.signal_breakdown)]
    grouped: dict[str, list[ProspectiveSignalDriverTagObservation]] = defaultdict(list)
    tag_metadata: dict[str, dict[str, object]] = {}
    for row in tagged_rows:
        seen_keys: set[str] = set()
        for tag in _prospective_driver_tags(row.signal_breakdown):
            key = _clean(tag.get("key"))
            if key == "unknown" or key in seen_keys:
                continue
            seen_keys.add(key)
            grouped[key].append(row)
            tag_metadata.setdefault(
                key,
                {
                    "key": key,
                    "feature": _clean(tag.get("feature")),
                    "value": _clean(tag.get("value")),
                    "reason": str(tag.get("reason") or ""),
                },
            )

    tag_payloads = [
        _prospective_tag_payload(
            key=key,
            rows=rows,
            metadata=tag_metadata.get(key, {"key": key}),
            gates=gates,
        )
        for key, rows in grouped.items()
    ]
    tag_payloads.sort(
        key=lambda item: (
            item["tag_verdict"] == "promotion_watchable",
            int(item["metrics"]["distinct_date_count"]),
            int(item["metrics"]["count"]),
            str(item["key"]),
        ),
        reverse=True,
    )

    blockers: list[str] = []
    if not tagged_rows:
        verdict = "no_prospective_tagged_evidence"
        blockers.append("no_tagged_plans_found")
    elif any(item["tag_verdict"] == "promotion_watchable" for item in tag_payloads):
        verdict = "prospective_tags_ready_for_review"
    else:
        verdict = "prospective_tags_accumulating"
        blockers.append("no_tag_met_review_gates")

    replay_labeled_rows = [item for item in tagged_rows if _clean(item.replay_outcome) != "unknown"]
    return {
        "schema_version": "prospective-signal-driver-tag-monitor-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "blockers": sorted(set(blockers)),
        "gates": gates.payload(),
        "record_counts": {
            "tagged_plans": len(tagged_rows),
            "unique_tag_keys": len(grouped),
            "replay_labeled_tagged_plans": len(replay_labeled_rows),
        },
        "metrics": {
            "tagged_population": _prospective_population_metrics(tagged_rows),
            "replay_labeled_population": _prospective_population_metrics(replay_labeled_rows),
        },
        "tags": tag_payloads,
        "recommendation": _prospective_tag_monitor_recommendation(verdict),
    }


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


def build_upstream_signal_driver_drilldown_report(
    observations: list[UpstreamSignalDriverObservation],
    candidate_groups: list[dict[str, object]],
    driver_specs: list[dict[str, object]],
    *,
    gates: UpstreamSignalDriverDrilldownGates | None = None,
    examples_per_outcome: int = 3,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or UpstreamSignalDriverDrilldownGates()
    rows = [
        item
        for item in observations
        if item.base.outcome in {"phantom_win", "phantom_loss"}
        and item.base.reward_pct > 0
        and item.base.risk_pct > 0
    ]
    candidate_rows = _candidate_rows(rows, candidate_groups)
    driver_payloads: list[dict[str, object]] = []
    reusable_count = 0
    concentrated_count = 0
    for spec in driver_specs:
        feature = str(spec.get("feature") or "").strip()
        value = str(spec.get("value") or "").strip().lower()
        if feature not in REUSABLE_FEATURES or not value:
            continue
        driver_rows = [
            item for item in candidate_rows if value in _feature_values(item, feature)
        ]
        payload = _driver_payload(
            feature=feature,
            value=value,
            rows=driver_rows,
            gates=gates,
            examples_per_outcome=examples_per_outcome,
        )
        if payload["driver_verdict"] == "reusable_driver":
            reusable_count += 1
        elif payload["driver_verdict"] == "ticker_concentrated_driver":
            concentrated_count += 1
        driver_payloads.append(payload)

    blockers: list[str] = []
    if reusable_count:
        verdict = "reusable_driver_leads"
    elif concentrated_count:
        verdict = "ticker_concentrated_driver_leads"
        blockers.append("all_positive_drivers_are_ticker_concentrated")
    else:
        verdict = "thin_driver_evidence"
        blockers.append("no_driver_passed_reusable_or_concentrated_gates")

    return {
        "schema_version": "upstream-signal-driver-drilldown-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "blockers": sorted(set(blockers)),
        "gates": gates.payload(),
        "candidate_group_count": len(candidate_groups),
        "driver_count": len(driver_payloads),
        "record_counts": {
            "population": len(rows),
            "candidate": len(candidate_rows),
        },
        "drivers": driver_payloads,
        "recommendation": _drilldown_recommendation(verdict),
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


def _driver_payload(
    *,
    feature: str,
    value: str,
    rows: list[UpstreamSignalDriverObservation],
    gates: UpstreamSignalDriverDrilldownGates,
    examples_per_outcome: int,
) -> dict[str, object]:
    metrics = _metric_payload(rows)
    ticker_mix = _top_values(rows, "ticker", limit=10)
    top_ticker_share = float(ticker_mix[0]["share_percent"]) if ticker_mix else 0.0
    blockers: list[str] = []
    if int(metrics["count"]) < gates.min_driver_rows:
        blockers.append("driver_rows_below_minimum")
    if int(metrics["distinct_date_count"]) < gates.min_driver_dates:
        blockers.append("driver_dates_below_minimum")
    if float(metrics["expected_value_per_observation"]) <= gates.min_driver_ev_per_observation:
        blockers.append("driver_ev_per_observation_not_positive")
    ticker_concentrated = top_ticker_share > gates.max_single_ticker_share_percent
    if int(metrics["ticker_count"]) < gates.min_driver_tickers:
        blockers.append("driver_ticker_count_below_reusable_minimum")
    if ticker_concentrated:
        blockers.append("driver_top_ticker_share_above_reusable_maximum")

    if not blockers:
        driver_verdict = "reusable_driver"
    elif (
        int(metrics["count"]) >= gates.min_driver_rows
        and int(metrics["distinct_date_count"]) >= gates.min_driver_dates
        and float(metrics["expected_value_per_observation"])
        > gates.min_driver_ev_per_observation
        and ticker_concentrated
    ):
        driver_verdict = "ticker_concentrated_driver"
    else:
        driver_verdict = "thin_driver"

    return {
        "feature": feature,
        "value": value,
        "driver_verdict": driver_verdict,
        "blockers": sorted(set(blockers)),
        "metrics": metrics,
        "mix": {
            "tickers": ticker_mix,
            "setup_family": _top_values(rows, "setup_family", limit=8),
            "context_bias": _top_values(rows, "context_bias", limit=8),
            "effective_action": _top_values(rows, "effective_action", limit=8),
            "transmission_tag": _top_values(rows, "transmission_tag", limit=12),
            "confidence_bucket": _top_values(rows, "confidence_bucket", limit=8),
            "volatility_bucket": _top_values(rows, "volatility_bucket", limit=8),
        },
        "date_range": _date_range_payload(rows),
        "examples": {
            "phantom_win": _examples(rows, "phantom_win", limit=examples_per_outcome),
            "phantom_loss": _examples(rows, "phantom_loss", limit=examples_per_outcome),
        },
    }


def _prospective_tag_payload(
    *,
    key: str,
    rows: list[ProspectiveSignalDriverTagObservation],
    metadata: dict[str, object],
    gates: ProspectiveSignalDriverTagMonitorGates,
) -> dict[str, object]:
    metrics = _prospective_population_metrics(rows)
    replay_labeled_rows = [item for item in rows if _clean(item.replay_outcome) != "unknown"]
    replay_labeled_metrics = _prospective_population_metrics(replay_labeled_rows)
    phantom_rows = [
        item
        for item in replay_labeled_rows
        if _clean(item.replay_outcome) in {"phantom_win", "phantom_loss"}
        and isinstance(item.reward_pct, (int, float))
        and isinstance(item.risk_pct, (int, float))
        and float(item.reward_pct) > 0
        and float(item.risk_pct) > 0
    ]
    ticker_mix = _prospective_top_values([item.ticker for item in rows], total=len(rows))
    top_ticker_share = float(ticker_mix[0]["share_percent"]) if ticker_mix else 0.0
    blockers: list[str] = []
    if int(metrics["count"]) < gates.min_tagged_rows:
        blockers.append("tagged_rows_below_minimum")
    if int(metrics["distinct_date_count"]) < gates.min_tagged_dates:
        blockers.append("tagged_dates_below_minimum")
    if int(replay_labeled_metrics["count"]) < gates.min_replay_labeled_rows:
        blockers.append("replay_labeled_rows_below_minimum")
    if int(replay_labeled_metrics["distinct_date_count"]) < gates.min_replay_labeled_dates:
        blockers.append("replay_labeled_dates_below_minimum")
    if int(metrics["distinct_date_count"]) < gates.promotion_watch_date_floor:
        blockers.append("tagged_dates_below_promotion_watch_floor")
    if top_ticker_share > gates.max_single_ticker_share_percent:
        blockers.append("top_ticker_share_above_reusable_maximum")
    tag_verdict = "promotion_watchable" if not blockers else "accumulating"

    return {
        "key": key,
        "feature": metadata.get("feature", "unknown"),
        "value": metadata.get("value", "unknown"),
        "reason": metadata.get("reason", ""),
        "tag_verdict": tag_verdict,
        "blockers": sorted(set(blockers)),
        "metrics": metrics,
        "replay_labeled_metrics": replay_labeled_metrics,
        "phantom_outcome_metrics": _prospective_phantom_metrics(phantom_rows),
        "outcome_mix": _prospective_outcome_mix(rows),
        "mix": {
            "tickers": ticker_mix,
            "setup_family": _prospective_top_values(
                [item.setup_family for item in rows],
                total=len(rows),
            ),
            "action": _prospective_top_values([item.action for item in rows], total=len(rows)),
        },
        "date_range": _prospective_date_range_payload(rows),
    }


def _prospective_population_metrics(
    rows: list[ProspectiveSignalDriverTagObservation],
) -> dict[str, object]:
    return {
        "count": len(rows),
        "distinct_date_count": len({item.evidence_date for item in rows}),
        "ticker_count": len({_clean(item.ticker) for item in rows if _clean(item.ticker) != "unknown"}),
    }


def _prospective_phantom_metrics(
    rows: list[ProspectiveSignalDriverTagObservation],
) -> dict[str, object]:
    count = len(rows)
    wins = sum(1 for item in rows if _clean(item.replay_outcome) == "phantom_win")
    losses = sum(1 for item in rows if _clean(item.replay_outcome) == "phantom_loss")
    ev_total = sum(
        float(item.reward_pct or 0.0)
        if _clean(item.replay_outcome) == "phantom_win"
        else -float(item.risk_pct or 0.0)
        for item in rows
    )
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate_percent": round((wins / count) * 100.0, 4) if count else 0.0,
        "expected_value": round(ev_total, 4),
        "expected_value_per_observation": round(ev_total / count, 6) if count else 0.0,
        "distinct_date_count": len({item.evidence_date for item in rows}),
    }


def _prospective_outcome_mix(
    rows: list[ProspectiveSignalDriverTagObservation],
) -> dict[str, int]:
    counter: Counter[str] = Counter(_clean(item.replay_outcome) for item in rows)
    return dict(sorted(counter.items()))


def _prospective_top_values(
    values: list[object],
    *,
    total: int,
    limit: int = 10,
) -> list[dict[str, object]]:
    counter = Counter(_clean(item) for item in values)
    denominator = max(1, total)
    payloads = [
        {
            "value": value,
            "count": count,
            "share_percent": round((count / denominator) * 100.0, 4),
        }
        for value, count in counter.items()
    ]
    payloads.sort(key=lambda item: (int(item["count"]), str(item["value"])), reverse=True)
    return payloads[:limit]


def _prospective_date_range_payload(
    rows: list[ProspectiveSignalDriverTagObservation],
) -> dict[str, str | None]:
    dates = sorted({item.evidence_date for item in rows})
    if not dates:
        return {"start": None, "end": None}
    return {"start": dates[0].isoformat(), "end": dates[-1].isoformat()}


def _prospective_driver_tags(signal: dict[str, object]) -> list[dict[str, object]]:
    raw = signal.get("upstream_signal_quality_drivers")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _top_values(
    rows: list[UpstreamSignalDriverObservation],
    feature_name: str,
    *,
    limit: int,
) -> list[dict[str, object]]:
    counter: Counter[str] = Counter()
    for row in rows:
        for value in _feature_values(row, feature_name):
            counter[value] += 1
    total = max(1, len(rows))
    payloads = [
        {
            "value": value,
            "count": count,
            "share_percent": round((count / total) * 100.0, 4),
        }
        for value, count in counter.items()
    ]
    payloads.sort(key=lambda item: (int(item["count"]), str(item["value"])), reverse=True)
    return payloads[:limit]


def _examples(
    rows: list[UpstreamSignalDriverObservation],
    outcome: str,
    *,
    limit: int,
) -> list[dict[str, object]]:
    selected = [item for item in rows if item.base.outcome == outcome]
    selected.sort(
        key=lambda item: (
            item.base.evidence_date,
            item.base.ticker,
            -item.base.reward_pct if outcome == "phantom_win" else item.base.risk_pct,
        )
    )
    return [_example_payload(item) for item in selected[:limit]]


def _example_payload(row: UpstreamSignalDriverObservation) -> dict[str, object]:
    base = row.base
    signal = row.signal_breakdown
    return {
        "plan_id": row.plan_id,
        "date": base.evidence_date.isoformat(),
        "ticker": base.ticker,
        "outcome": base.outcome,
        "setup_family": base.setup_family,
        "context_bias": base.context_bias,
        "action": base.action,
        "effective_action": base.effective_action,
        "confidence_percent": round(base.confidence_percent, 4),
        "reward_pct": round(base.reward_pct, 6),
        "risk_pct": round(base.risk_pct, 6),
        "signal_excerpt": {
            "decision_tier": signal.get("decision_tier"),
            "shortlisted": signal.get("shortlisted"),
            "shortlist_rank": signal.get("shortlist_rank"),
            "cheap_scan_volatility_score": signal.get("cheap_scan_volatility_score"),
            "transmission_tags": sorted(_transmission_tags(signal)),
            "expected_transmission_window": next(
                iter(_feature_values(row, "expected_transmission_window"))
            ),
            "catalyst_intensity_bucket": next(
                iter(_feature_values(row, "catalyst_intensity_bucket"))
            ),
            "confidence_components": _compact_confidence_components(
                signal.get("confidence_components")
            ),
            "calibration_review": _compact_calibration_review(signal.get("calibration_review")),
            "fundamental_coverage_status": next(
                iter(_feature_values(row, "fundamental_coverage_status"))
            ),
        },
    }


def _compact_confidence_components(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    payload: dict[str, float] = {}
    for key, raw in value.items():
        number = _first_number(raw)
        if number is not None:
            payload[_clean(key)] = round(number, 4)
    return payload or None


def _compact_calibration_review(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    reasons = value.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    payload: dict[str, object] = {}
    for key in (
        "enabled",
        "review_status",
        "raw_confidence_percent",
        "calibrated_confidence_percent",
        "base_confidence_threshold",
        "effective_confidence_threshold",
        "threshold_adjustment",
    ):
        if key in value:
            payload[key] = value[key]
    payload["reasons"] = [str(item) for item in reasons[:8]]
    return payload


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


def _date_range_payload(rows: list[UpstreamSignalDriverObservation]) -> dict[str, str | None]:
    dates = sorted({item.base.evidence_date for item in rows})
    if not dates:
        return {"start": None, "end": None}
    return {"start": dates[0].isoformat(), "end": dates[-1].isoformat()}


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


def _drilldown_recommendation(verdict: str) -> str:
    if verdict == "reusable_driver_leads":
        return (
            "Inspect the generation code for reusable drivers that are positive, "
            "date-spread, and not ticker-dominated before making one upstream policy change."
        )
    if verdict == "ticker_concentrated_driver_leads":
        return (
            "Do not generalize these drivers yet. Inspect ticker-specific generation and "
            "cluster risk before changing broad signal policy."
        )
    return (
        "Do not change upstream policy from these drivers. Improve evidence volume or "
        "feature persistence first."
    )


def _prospective_tag_monitor_recommendation(verdict: str) -> str:
    if verdict == "prospective_tags_ready_for_review":
        return (
            "Review prospective tagged cohorts before any policy change. Do not run broad "
            "threshold search; inspect tag stability, date spread, concentration, and replay EV."
        )
    if verdict == "prospective_tags_accumulating":
        return (
            "Keep collecting tagged evidence. Re-run this monitor after more dates or replay "
            "labels arrive."
        )
    return (
        "No prospective tagged evidence exists yet. Generate new plans with current code, "
        "then rerun the monitor after replay labels are available."
    )
