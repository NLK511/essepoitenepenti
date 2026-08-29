from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import ceil
from typing import Any


@dataclass(frozen=True, slots=True)
class PhantomSelectivityObservation:
    evidence_date: date
    outcome: str
    ticker: str
    setup_family: str
    context_bias: str | None
    action: str
    intended_action: str | None
    effective_action: str | None
    confidence_percent: float
    volatility_score: float | None
    reward_pct: float
    risk_pct: float


@dataclass(frozen=True, slots=True)
class PhantomSelectivitySeparabilityGates:
    min_total_rows: int = 500
    min_selection_dates: int = 10
    min_discovery_group_rows: int = 100
    min_selection_group_rows: int = 30
    min_selection_group_dates: int = 5
    min_discovery_win_rate_lift_pct: float = 0.0
    min_discovery_ev_per_observation: float = 0.0
    min_selection_win_rate_lift_pct: float = 5.0
    min_selection_ev_per_observation: float = 0.0
    selection_date_fraction: float = 0.25

    def payload(self) -> dict[str, object]:
        return {
            "min_total_rows": self.min_total_rows,
            "min_selection_dates": self.min_selection_dates,
            "min_discovery_group_rows": self.min_discovery_group_rows,
            "min_selection_group_rows": self.min_selection_group_rows,
            "min_selection_group_dates": self.min_selection_group_dates,
            "min_discovery_win_rate_lift_pct": self.min_discovery_win_rate_lift_pct,
            "min_discovery_ev_per_observation": self.min_discovery_ev_per_observation,
            "min_selection_win_rate_lift_pct": self.min_selection_win_rate_lift_pct,
            "min_selection_ev_per_observation": self.min_selection_ev_per_observation,
            "selection_date_fraction": self.selection_date_fraction,
        }


@dataclass(frozen=True, slots=True)
class PhantomSelectivityCandidateReplayGates:
    min_selection_rows: int = 100
    min_selection_dates: int = 20
    min_selection_ev_per_observation: float = 0.0
    min_selection_win_rate_lift_pct: float = 0.0
    max_single_ticker_share_percent: float = 50.0
    max_single_date_share_percent: float = 30.0
    max_single_setup_family_share_percent: float = 80.0

    def payload(self) -> dict[str, object]:
        return {
            "min_selection_rows": self.min_selection_rows,
            "min_selection_dates": self.min_selection_dates,
            "min_selection_ev_per_observation": self.min_selection_ev_per_observation,
            "min_selection_win_rate_lift_pct": self.min_selection_win_rate_lift_pct,
            "max_single_ticker_share_percent": self.max_single_ticker_share_percent,
            "max_single_date_share_percent": self.max_single_date_share_percent,
            "max_single_setup_family_share_percent": self.max_single_setup_family_share_percent,
        }


FEATURE_NAMES: tuple[str, ...] = (
    "setup_family",
    "ticker",
    "context_bias",
    "action",
    "effective_action",
    "confidence_bucket",
    "volatility_bucket",
    "reward_risk_bucket",
    "risk_bucket",
    "reward_bucket",
)


def build_phantom_selectivity_separability_report(
    observations: list[PhantomSelectivityObservation],
    *,
    gates: PhantomSelectivitySeparabilityGates | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or PhantomSelectivitySeparabilityGates()
    rows = [
        item
        for item in observations
        if item.outcome in {"phantom_win", "phantom_loss"}
        and item.reward_pct > 0
        and item.risk_pct > 0
    ]
    rows.sort(key=lambda item: (item.evidence_date, item.ticker, item.setup_family))
    all_dates = sorted({item.evidence_date for item in rows})
    blockers: list[str] = []
    if len(rows) < gates.min_total_rows:
        blockers.append("phantom_sample_below_minimum")
    if len(all_dates) < gates.min_selection_dates + 1:
        blockers.append("phantom_distinct_dates_below_split_minimum")

    discovery_dates, selection_dates = _chronological_split_dates(
        all_dates,
        min_selection_dates=gates.min_selection_dates,
        selection_date_fraction=gates.selection_date_fraction,
    )
    discovery_rows = [item for item in rows if item.evidence_date in discovery_dates]
    selection_rows = [item for item in rows if item.evidence_date in selection_dates]
    if len(selection_dates) < gates.min_selection_dates:
        blockers.append("selection_distinct_dates_below_minimum")

    discovery_baseline = _metric_payload(discovery_rows)
    selection_baseline = _metric_payload(selection_rows)
    feature_summaries: dict[str, dict[str, object]] = {}
    candidate_groups: list[dict[str, object]] = []
    for feature_name in FEATURE_NAMES:
        groups = _group_feature(rows, feature_name)
        group_payloads: list[dict[str, object]] = []
        for value, group_rows in groups.items():
            discovery_group = [
                item for item in group_rows if item.evidence_date in discovery_dates
            ]
            selection_group = [
                item for item in group_rows if item.evidence_date in selection_dates
            ]
            payload = {
                "feature": feature_name,
                "value": value,
                "all": _metric_payload(group_rows),
                "discovery": _metric_payload(discovery_group),
                "selection": _metric_payload(selection_group),
            }
            selection = payload["selection"]
            assert isinstance(selection, dict)
            discovery = payload["discovery"]
            assert isinstance(discovery, dict)
            discovery_lift = (
                float(discovery["win_rate_percent"])
                - float(discovery_baseline["win_rate_percent"])
            )
            selection_lift = (
                float(selection["win_rate_percent"])
                - float(selection_baseline["win_rate_percent"])
            )
            payload["discovery_win_rate_lift_pct"] = round(discovery_lift, 4)
            payload["selection_win_rate_lift_pct"] = round(selection_lift, 4)
            payload["passes_candidate_gates"] = _passes_candidate_gates(
                discovery,
                selection,
                discovery_lift=discovery_lift,
                selection_lift=selection_lift,
                gates=gates,
            )
            if payload["passes_candidate_gates"]:
                candidate_groups.append(payload)
            group_payloads.append(payload)
        group_payloads.sort(key=_group_sort_key, reverse=True)
        feature_summaries[feature_name] = {
            "group_count": len(group_payloads),
            "passing_group_count": sum(
                1 for item in group_payloads if item["passes_candidate_gates"]
            ),
            "top_groups": group_payloads[:10],
        }

    candidate_groups.sort(key=_group_sort_key, reverse=True)
    if blockers:
        verdict = "thin_evidence"
    elif candidate_groups:
        verdict = "candidate_replay_recommended"
    else:
        verdict = "stop_threshold_search"
        blockers.append("no_selection_group_passed_gates")

    return {
        "schema_version": "phantom-selectivity-separability-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "should_continue_threshold_search": False,
        "candidate_specific_replay_recommended": verdict == "candidate_replay_recommended",
        "blockers": sorted(set(blockers)),
        "gates": gates.payload(),
        "record_counts": {
            "total": len(rows),
            "discovery": len(discovery_rows),
            "selection": len(selection_rows),
        },
        "date_counts": {
            "total": len(all_dates),
            "discovery": len(discovery_dates),
            "selection": len(selection_dates),
        },
        "date_windows": {
            "all": _date_range_payload(set(all_dates)),
            "discovery": _date_range_payload(discovery_dates),
            "selection": _date_range_payload(selection_dates),
        },
        "selection_split": _selection_split_payload(
            total_date_count=len(all_dates),
            selection_date_count=len(selection_dates),
            min_selection_dates=gates.min_selection_dates,
            selection_date_fraction=gates.selection_date_fraction,
        ),
        "baseline_shift": _baseline_shift_payload(
            discovery_baseline,
            selection_baseline,
        ),
        "date_ranges": {
            "discovery": _date_range_payload(discovery_dates),
            "selection": _date_range_payload(selection_dates),
        },
        "baselines": {
            "discovery": discovery_baseline,
            "selection": selection_baseline,
        },
        "candidate_groups": candidate_groups[:20],
        "feature_summaries": feature_summaries,
        "recommendation": _recommendation(verdict),
    }


def build_phantom_selectivity_candidate_replay_report(
    observations: list[PhantomSelectivityObservation],
    candidate_groups: list[dict[str, object]],
    *,
    min_selection_dates: int = 10,
    selection_date_fraction: float = 0.25,
    gates: PhantomSelectivityCandidateReplayGates | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    gates = gates or PhantomSelectivityCandidateReplayGates()
    rows = [
        item
        for item in observations
        if item.outcome in {"phantom_win", "phantom_loss"}
        and item.reward_pct > 0
        and item.risk_pct > 0
    ]
    rows.sort(key=lambda item: (item.evidence_date, item.ticker, item.setup_family))
    all_dates = sorted({item.evidence_date for item in rows})
    discovery_dates, selection_dates = _chronological_split_dates(
        all_dates,
        min_selection_dates=min_selection_dates,
        selection_date_fraction=selection_date_fraction,
    )
    discovery_rows = [item for item in rows if item.evidence_date in discovery_dates]
    selection_rows = [item for item in rows if item.evidence_date in selection_dates]
    discovery_baseline = _metric_payload(discovery_rows)
    selection_baseline = _metric_payload(selection_rows)
    group_results: list[dict[str, object]] = []
    selected_union_indexes: set[int] = set()
    selected_non_ticker_union_indexes: set[int] = set()
    for index, group in enumerate(candidate_groups, start=1):
        feature = str(group.get("feature") or "")
        value = str(group.get("value") or "")
        if feature not in FEATURE_NAMES or not value:
            continue
        selected: list[PhantomSelectivityObservation] = []
        for row_index, item in enumerate(rows):
            if _feature_value(item, feature) == value:
                selected.append(item)
                selected_union_indexes.add(row_index)
                if feature != "ticker":
                    selected_non_ticker_union_indexes.add(row_index)
        result = _candidate_replay_payload(
            selected,
            discovery_dates=discovery_dates,
            selection_dates=selection_dates,
            selection_baseline=selection_baseline,
            gates=gates,
            feature=feature,
        )
        result.update({"rank": index, "feature": feature, "value": value})
        group_results.append(result)

    union_rows = [
        item for row_index, item in enumerate(rows) if row_index in selected_union_indexes
    ]
    non_ticker_union_rows = [
        item
        for row_index, item in enumerate(rows)
        if row_index in selected_non_ticker_union_indexes
    ]
    union_result = _candidate_replay_payload(
        union_rows,
        discovery_dates=discovery_dates,
        selection_dates=selection_dates,
        selection_baseline=selection_baseline,
        gates=gates,
        feature="combined_union",
    )
    if any(item.get("candidate_kind") == "ticker_specific" for item in group_results):
        union_warnings = set(union_result.get("warnings") or [])
        union_warnings.add("union_contains_ticker_specific_groups")
        union_result["warnings"] = sorted(union_warnings)
        union_blockers = set(union_result.get("promotion_blockers") or [])
        union_blockers.add("union_contains_ticker_specific_groups")
        union_result["promotion_blockers"] = sorted(union_blockers)
        union_result["promotion_ready"] = False
    non_ticker_union_result = _candidate_replay_payload(
        non_ticker_union_rows,
        discovery_dates=discovery_dates,
        selection_dates=selection_dates,
        selection_baseline=selection_baseline,
        gates=gates,
        feature="combined_non_ticker_union",
    )
    promotion_ready = bool(union_result["promotion_ready"]) or any(
        bool(item["promotion_ready"]) for item in group_results
    )
    verdict = "promotion_candidate_ready" if promotion_ready else "research_candidate_only"
    return {
        "schema_version": "phantom-selectivity-candidate-replay-v1",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "verdict": verdict,
        "promotion_candidate_ready": promotion_ready,
        "should_continue_threshold_search": False,
        "gates": gates.payload(),
        "record_counts": {
            "total": len(rows),
            "discovery": len(discovery_rows),
            "selection": len(selection_rows),
        },
        "date_counts": {
            "total": len(all_dates),
            "discovery": len(discovery_dates),
            "selection": len(selection_dates),
        },
        "date_windows": {
            "all": _date_range_payload(set(all_dates)),
            "discovery": _date_range_payload(discovery_dates),
            "selection": _date_range_payload(selection_dates),
        },
        "selection_split": _selection_split_payload(
            total_date_count=len(all_dates),
            selection_date_count=len(selection_dates),
            min_selection_dates=min_selection_dates,
            selection_date_fraction=selection_date_fraction,
            promotion_min_selection_dates=gates.min_selection_dates,
        ),
        "baseline_shift": _baseline_shift_payload(
            discovery_baseline,
            selection_baseline,
        ),
        "baselines": {
            "discovery": discovery_baseline,
            "selection": selection_baseline,
        },
        "candidate_group_count": len(group_results),
        "candidate_group_counts": {
            "ticker_specific": sum(
                1 for item in group_results if item["candidate_kind"] == "ticker_specific"
            ),
            "reusable_feature": sum(
                1 for item in group_results if item["candidate_kind"] == "reusable_feature"
            ),
        },
        "candidate_groups": group_results,
        "combined_union": union_result,
        "combined_union_excluding_ticker_groups": non_ticker_union_result,
        "recommendation": _candidate_replay_recommendation(verdict),
    }


def _candidate_replay_payload(
    rows: list[PhantomSelectivityObservation],
    *,
    discovery_dates: set[date],
    selection_dates: set[date],
    selection_baseline: dict[str, object],
    gates: PhantomSelectivityCandidateReplayGates,
    feature: str | None = None,
) -> dict[str, object]:
    discovery_rows = [item for item in rows if item.evidence_date in discovery_dates]
    selection_rows = [item for item in rows if item.evidence_date in selection_dates]
    discovery = _metric_payload(discovery_rows)
    selection = _metric_payload(selection_rows)
    selection_lift = (
        float(selection["win_rate_percent"])
        - float(selection_baseline["win_rate_percent"])
    )
    blockers: list[str] = []
    if int(selection["count"]) < gates.min_selection_rows:
        blockers.append("selection_rows_below_promotion_minimum")
    if int(selection["distinct_date_count"]) < gates.min_selection_dates:
        blockers.append("selection_dates_below_promotion_minimum")
    if (
        float(selection["expected_value_per_observation"])
        <= gates.min_selection_ev_per_observation
    ):
        blockers.append("selection_ev_per_observation_not_positive")
    if selection_lift < gates.min_selection_win_rate_lift_pct:
        blockers.append("selection_win_rate_lift_below_minimum")
    concentration = _concentration_payload(selection_rows)
    warnings = _concentration_warnings(concentration, gates=gates)
    candidate_kind = _candidate_kind(feature)
    if candidate_kind == "ticker_specific":
        blockers.append("ticker_specific_candidate_only")
    return {
        "candidate_kind": candidate_kind,
        "discovery": discovery,
        "selection": selection,
        "selection_win_rate_lift_pct": round(selection_lift, 4),
        "concentration": concentration,
        "warnings": warnings,
        "promotion_ready": not blockers,
        "promotion_blockers": sorted(set(blockers)),
    }

def _chronological_split_dates(
    all_dates: list[date],
    *,
    min_selection_dates: int,
    selection_date_fraction: float,
) -> tuple[set[date], set[date]]:
    if not all_dates:
        return set(), set()
    desired_selection = max(
        min_selection_dates,
        int(ceil(len(all_dates) * max(0.05, min(0.8, selection_date_fraction)))),
    )
    selection_count = min(max(1, desired_selection), max(1, len(all_dates) - 1))
    selection_dates = set(all_dates[-selection_count:])
    discovery_dates = set(all_dates[:-selection_count])
    return discovery_dates, selection_dates


def _group_feature(
    rows: list[PhantomSelectivityObservation], feature_name: str
) -> dict[str, list[PhantomSelectivityObservation]]:
    grouped: dict[str, list[PhantomSelectivityObservation]] = defaultdict(list)
    for row in rows:
        grouped[_feature_value(row, feature_name)].append(row)
    return grouped


def _feature_value(row: PhantomSelectivityObservation, feature_name: str) -> str:
    if feature_name == "confidence_bucket":
        return _numeric_bucket(row.confidence_percent, step=5.0, lower=0.0, upper=100.0)
    if feature_name == "volatility_bucket":
        if row.volatility_score is None:
            return "unknown"
        return _numeric_bucket(
            _normalize_percent(row.volatility_score),
            step=10.0,
            lower=0.0,
            upper=100.0,
        )
    if feature_name == "reward_risk_bucket":
        ratio = row.reward_pct / row.risk_pct if row.risk_pct > 0 else 0.0
        return _ratio_bucket(ratio)
    if feature_name == "risk_bucket":
        return _numeric_bucket(row.risk_pct, step=1.0, lower=0.0, upper=20.0)
    if feature_name == "reward_bucket":
        return _numeric_bucket(row.reward_pct, step=1.0, lower=0.0, upper=30.0)
    value = getattr(row, feature_name, None)
    text = str(value or "").strip().lower()
    return text or "unknown"


def _normalize_percent(value: float) -> float:
    value = float(value)
    if value <= 1.0:
        value *= 100.0
    return max(0.0, min(100.0, value))


def _numeric_bucket(value: float, *, step: float, lower: float, upper: float) -> str:
    bounded = max(lower, min(upper, float(value)))
    bucket_lower = lower + (int((bounded - lower) // step) * step)
    bucket_upper = min(upper, bucket_lower + step)
    return f"{bucket_lower:g}-{bucket_upper:g}"


def _ratio_bucket(value: float) -> str:
    if value < 1.0:
        return "lt_1"
    if value < 1.5:
        return "1_to_1_5"
    if value < 2.0:
        return "1_5_to_2"
    if value < 3.0:
        return "2_to_3"
    return "gte_3"


def _metric_payload(rows: list[PhantomSelectivityObservation]) -> dict[str, object]:
    count = len(rows)
    wins = sum(1 for item in rows if item.outcome == "phantom_win")
    losses = sum(1 for item in rows if item.outcome == "phantom_loss")
    ev_values = [
        item.reward_pct if item.outcome == "phantom_win" else -item.risk_pct
        for item in rows
    ]
    ev_total = sum(ev_values)
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate_percent": round((wins / count) * 100.0, 4) if count else 0.0,
        "expected_value": round(ev_total, 4),
        "expected_value_per_observation": round(ev_total / count, 6) if count else 0.0,
        "distinct_date_count": len({item.evidence_date for item in rows}),
        "ticker_count": len({item.ticker for item in rows if item.ticker}),
    }


def _selection_split_payload(
    *,
    total_date_count: int,
    selection_date_count: int,
    min_selection_dates: int,
    selection_date_fraction: float,
    promotion_min_selection_dates: int | None = None,
) -> dict[str, object]:
    bounded_fraction = max(0.05, min(0.8, float(selection_date_fraction)))
    payload: dict[str, object] = {
        "total_eligible_dates": total_date_count,
        "selection_date_fraction": bounded_fraction,
        "minimum_selection_dates": min_selection_dates,
        "selection_dates": selection_date_count,
    }
    if promotion_min_selection_dates is not None:
        estimated_total = int(ceil(float(promotion_min_selection_dates) / bounded_fraction))
        payload.update(
            {
                "promotion_minimum_selection_dates": promotion_min_selection_dates,
                "estimated_total_eligible_dates_for_promotion_gate": estimated_total,
                "additional_total_eligible_dates_needed": max(
                    0,
                    estimated_total - total_date_count,
                ),
            }
        )
    return payload


def _baseline_shift_payload(
    discovery: dict[str, object],
    selection: dict[str, object],
) -> dict[str, object]:
    discovery_wr = float(discovery.get("win_rate_percent") or 0.0)
    selection_wr = float(selection.get("win_rate_percent") or 0.0)
    discovery_ev = float(discovery.get("expected_value_per_observation") or 0.0)
    selection_ev = float(selection.get("expected_value_per_observation") or 0.0)
    warnings: list[str] = []
    win_rate_delta = round(selection_wr - discovery_wr, 4)
    ev_delta = round(selection_ev - discovery_ev, 6)
    if abs(win_rate_delta) > 5.0:
        warnings.append("baseline_win_rate_shift_above_5pct")
    if (discovery_ev < 0 < selection_ev) or (selection_ev < 0 < discovery_ev):
        warnings.append("baseline_ev_sign_crossed_zero")
    return {
        "discovery_win_rate_percent": discovery_wr,
        "selection_win_rate_percent": selection_wr,
        "win_rate_delta_pct": win_rate_delta,
        "discovery_ev_per_observation": discovery_ev,
        "selection_ev_per_observation": selection_ev,
        "ev_per_observation_delta": ev_delta,
        "warnings": sorted(warnings),
    }


def _candidate_kind(feature: str | None) -> str:
    if feature == "ticker":
        return "ticker_specific"
    return "reusable_feature"


def _concentration_payload(rows: list[PhantomSelectivityObservation]) -> dict[str, object]:
    return {
        "ticker": _top_concentration([item.ticker for item in rows], total=len(rows)),
        "date": _top_concentration(
            [item.evidence_date.isoformat() for item in rows],
            total=len(rows),
        ),
        "setup_family": _top_concentration([item.setup_family for item in rows], total=len(rows)),
    }


def _top_concentration(values: list[object], *, total: int) -> dict[str, object]:
    if not values:
        return {"top_value": None, "top_count": 0, "top_share_percent": 0.0}
    counter = Counter(str(item or "unknown").strip().lower() or "unknown" for item in values)
    value, count = counter.most_common(1)[0]
    return {
        "top_value": value,
        "top_count": count,
        "top_share_percent": round((count / max(1, total)) * 100.0, 4),
    }


def _concentration_warnings(
    concentration: dict[str, object],
    *,
    gates: PhantomSelectivityCandidateReplayGates,
) -> list[str]:
    warnings: list[str] = []
    ticker = concentration.get("ticker")
    date_payload = concentration.get("date")
    setup = concentration.get("setup_family")
    if (
        isinstance(ticker, dict)
        and float(ticker.get("top_share_percent") or 0.0)
        > gates.max_single_ticker_share_percent
    ):
        warnings.append("single_ticker_share_above_limit")
    if (
        isinstance(date_payload, dict)
        and float(date_payload.get("top_share_percent") or 0.0)
        > gates.max_single_date_share_percent
    ):
        warnings.append("single_date_share_above_limit")
    if (
        isinstance(setup, dict)
        and float(setup.get("top_share_percent") or 0.0)
        > gates.max_single_setup_family_share_percent
    ):
        warnings.append("single_setup_family_share_above_limit")
    return sorted(warnings)


def _passes_candidate_gates(
    discovery: dict[str, object],
    selection: dict[str, object],
    *,
    discovery_lift: float,
    selection_lift: float,
    gates: PhantomSelectivitySeparabilityGates,
) -> bool:
    return (
        int(discovery["count"]) >= gates.min_discovery_group_rows
        and int(selection["count"]) >= gates.min_selection_group_rows
        and int(selection["distinct_date_count"]) >= gates.min_selection_group_dates
        and discovery_lift >= gates.min_discovery_win_rate_lift_pct
        and float(discovery["expected_value_per_observation"])
        > gates.min_discovery_ev_per_observation
        and selection_lift >= gates.min_selection_win_rate_lift_pct
        and float(selection["expected_value_per_observation"])
        > gates.min_selection_ev_per_observation
    )


def _group_sort_key(payload: dict[str, Any]) -> tuple[float, float, int]:
    selection = payload.get("selection")
    if not isinstance(selection, dict):
        return (0.0, 0.0, 0)
    return (
        float(payload.get("discovery_win_rate_lift_pct") or 0.0),
        float(selection.get("expected_value_per_observation") or 0.0),
        float(payload.get("selection_win_rate_lift_pct") or 0.0),
        int(selection.get("count") or 0),
    )


def _date_range_payload(dates: set[date]) -> dict[str, str | None]:
    if not dates:
        return {"start": None, "end": None}
    ordered = sorted(dates)
    return {"start": ordered[0].isoformat(), "end": ordered[-1].isoformat()}


def _recommendation(verdict: str) -> str:
    if verdict == "candidate_replay_recommended":
        return (
            "Run canonical candidate-specific replay for the listed groups before "
            "any promotion or broad parameter search."
        )
    if verdict == "stop_threshold_search":
        return (
            "Stop threshold searches over the current stored phantom evidence. "
            "Improve upstream signal features before tuning this layer again."
        )
    return "Collect or repair more phantom replay evidence before making a tuning call."


def _candidate_replay_recommendation(verdict: str) -> str:
    if verdict == "promotion_candidate_ready":
        return (
            "Create a DB-backed candidate-hash replay for the passing policy and run "
            "promotion-grade preflight before any setting change."
        )
    return (
        "Do not run more broad threshold searches. Treat the passing groups as "
        "research-only until more candidate replay dates are available or upstream "
        "signal generation changes."
    )
